from __future__ import annotations

import dataclasses
import json
import multiprocessing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from nowcast.config import Config
from nowcast.errors import AuthError, BudgetExceeded, RateLimited
from nowcast.extraction.schema import ExtractionRecord
from nowcast.jobs import JobStore, store_for
from nowcast.llm.caller import LLMResult
from nowcast.llm.composition import make_caller
from nowcast.llm.receipts import RequestReceipts, RequestUncertain
from nowcast.llm.throttle import SharedRequestLimiter
from nowcast.scheduler import Scheduler, installation_preview

CONFIG = Path(__file__).resolve().parents[2] / 'configs/config.yaml'


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 2, 1, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Provider:
    def __init__(self):
        self.calls = 0
        self.failure = None

    def complete(self, model, messages, max_tokens=None):
        self.calls += 1
        if self.failure:
            raise self.failure
        return LLMResult(
            text=ExtractionRecord(
                schema_version='v1', document_id=messages[-1]['content']
            ).model_dump_json(),
            model=model,
        )


def configured(config: Config, limit=4):
    return dataclasses.replace(
        config,
        scope=dataclasses.replace(config.scope, profile='custom', companies=4, seasons=1),
        llm=dataclasses.replace(
            config.llm, requests_per_day=limit, requests_per_minute=100, retry_attempts=1
        ),
        scheduler=dataclasses.replace(
            config.scheduler, safety_margin=0, retry_reserve=0, bakeoff_requests=2
        ),
        runtime=dataclasses.replace(config.runtime, durable_requests=True),
        cache=dataclasses.replace(config.cache, enabled=False),
    )


def scheduler_fixture(config, monkeypatch, limit=4):
    from nowcast import operations

    monkeypatch.setattr(operations, 'doctor', lambda config: {'sec_contact': True})
    clock = Clock()
    provider = Provider()
    order = []
    local = configured(config, limit)

    def execute(store, job_id):
        assert store.claim(job_id)
        row = store.get(job_id)
        request = json.loads(row['request_json'])
        stage = request['command_id']
        store.event(job_id, stage, 'started')
        order.append(stage)
        try:
            if stage in {'extract', 'model-bakeoff'}:
                target = 4 if stage == 'extract' else 2
                caller = make_caller(local, inner=provider, clock=clock, sleep=clock.sleep)
                for index in range(target):
                    caller.complete(
                        local.llm.models[0], [{'role': 'user', 'content': stage + '-' + str(index)}]
                    )
            store.update(job_id, status='succeeded')
            store.event(job_id, stage, 'succeeded')
        except BudgetExceeded:
            store.update(job_id, status='interrupted')
            store.event(job_id, stage, 'quota_exhausted')
        except AuthError:
            store.update(job_id, status='failed')
            store.event(job_id, stage, 'authentication_failed')
        except RateLimited as exc:
            SharedRequestLimiter(
                store, local.llm.base_url, 100, limit, clock=clock, sleep=clock.sleep
            ).cooldown(exc.retry_after_seconds or 30)
            store.update(job_id, status='interrupted')
            store.event(job_id, stage, 'rate_limited')

    scheduler = Scheduler(local, CONFIG, clock=clock, execute=execute)
    scheduler.ensure_plan()
    return scheduler, clock, provider, order


def test_plan_and_estimate_share_budget_and_do_not_include_identifiers(config, monkeypatch):
    scheduler, _clock, provider, _order = scheduler_fixture(config, monkeypatch)
    snapshot = scheduler.snapshot()
    assert sum(day['planned_requests'] for day in snapshot['days']) == 6
    assert all(day['planned_requests'] <= day['budget'] for day in snapshot['days'])
    assert len(snapshot['days']) - 1 == snapshot['forecast']['model_days']
    payload = json.dumps(snapshot)
    assert not any(
        '"' + key + '"' in payload for key in ['cik', 'ticker', 'company', 'sector', 'document_id']
    )
    assert not provider.calls


def test_dependencies_human_gate_quota_rollover_and_no_duplicate_calls(config, monkeypatch):
    scheduler, clock, provider, order = scheduler_fixture(config, monkeypatch)
    scheduler.run_once()
    assert order[:6] == [
        'doctor',
        'build-constituents',
        'freeze-panel',
        'ingest',
        'validate-index',
        'estimate-scope',
    ]
    assert not provider.calls
    assert all(task['status'] == 'pending' for task in scheduler.tasks() if task['human'])
    clock.sleep(86400)
    scheduler.run_once()
    assert not provider.calls
    scheduler.set_state('models_confirmed', True)
    scheduler.run_once()
    assert scheduler.used() == 4 and provider.calls == 4
    assert {'aggregate', 'export'} <= set(order)
    scheduler.run_once()
    assert provider.calls == 4
    clock.sleep(86400)
    scheduler.run_once()
    assert provider.calls == 6
    assert scheduler.used() == 2
    assert (
        next(task for task in scheduler.tasks() if task['task_key'] == 'extract')['status']
        == 'done'
    )


def test_401_blocks_without_quota_and_does_not_repeat(config, monkeypatch):
    scheduler, clock, provider, _order = scheduler_fixture(config, monkeypatch)
    scheduler.run_once()
    clock.sleep(86400)
    scheduler.set_state('models_confirmed', True)
    provider.failure = AuthError('credential rejected')
    scheduler.run_once()
    assert scheduler.state('auth_blocked') is True
    assert scheduler.used() == 0
    assert provider.calls == 1
    scheduler.run_once()
    assert provider.calls == 1


def test_429_preserves_global_cooldown_and_stops_batch(config, monkeypatch):
    scheduler, clock, provider, _order = scheduler_fixture(config, monkeypatch)
    scheduler.run_once()
    clock.sleep(86400)
    scheduler.set_state('models_confirmed', True)
    provider.failure = RateLimited('busy', retry_after_seconds=600)
    before = clock()
    scheduler.run_once()
    assert provider.calls == 1
    with scheduler.store.engine.connect() as connection:
        until = connection.execute(
            text('SELECT resume_at FROM cooldowns WHERE scope=:scope'),
            {'scope': scheduler.config.llm.base_url},
        ).scalar_one()
    assert until >= before + 600
    scheduler.run_once()
    assert provider.calls == 1


def test_pause_resume_does_not_create_a_second_queue(config, monkeypatch):
    scheduler, _clock, _provider, order = scheduler_fixture(config, monkeypatch)
    scheduler.set_state('paused', True)
    scheduler.run_once()
    assert not order
    scheduler.set_state('paused', False)
    scheduler.run_once()
    assert len(order) == 6
    with scheduler.store.engine.connect() as connection:
        assert connection.execute(text('SELECT count(*) FROM jobs')).scalar_one() == 6
        assert connection.execute(text('SELECT count(*) FROM events')).scalar_one() >= 12


def test_completed_receipt_replays_after_worker_result_was_lost(config):
    local = configured(config)
    clock = Clock()
    provider = Provider()
    caller = make_caller(local, inner=provider, clock=clock, sleep=clock.sleep)
    messages = [{'role': 'user', 'content': 'one release'}]
    first = caller.complete(local.llm.models[0], messages)
    # No extraction artifact exists: only the durable HTTP receipt survived.
    second = make_caller(local, inner=provider, clock=clock, sleep=clock.sleep).complete(
        local.llm.models[0], messages
    )
    assert first.text == second.text and second.cached
    assert provider.calls == 1


def test_unknown_inflight_request_is_not_resent(config):
    store = store_for(config)
    receipts = RequestReceipts(store)
    assert receipts.begin('unknown') is None
    with store.transaction() as connection:
        connection.execute(
            text(
                "UPDATE request_receipts SET pid=99999999,identity='dead' WHERE request_key='unknown'"
            )
        )
    with pytest.raises(RequestUncertain):
        receipts.begin('unknown')
    with pytest.raises(RequestUncertain):
        receipts.begin('unknown')


def reserve_process(path, queue):
    store = JobStore(Path(path))
    limiter = SharedRequestLimiter(store, 'concurrent', 100, 3)
    count = 0
    for _ in range(3):
        try:
            limiter.acquire()
            count += 1
        except BudgetExceeded:
            break
    queue.put(count)


def test_two_processes_share_the_same_quota_cap(config):
    store = store_for(config)
    context = multiprocessing.get_context('fork')
    queue = context.Queue()
    processes = [
        context.Process(target=reserve_process, args=(str(store.path), queue)) for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    assert sum(queue.get(timeout=3) for _ in processes) == 3


def test_timer_preview_is_exact_and_contains_no_secrets(config, tmp_path):
    files = installation_preview(config, tmp_path / 'checkout', tmp_path / 'config')
    assert len(files) == 2
    timer = next(value for name, value in files.items() if name.endswith('.timer'))
    service = next(value for name, value in files.items() if name.endswith('.service'))
    assert 'OnCalendar=*-*-* 00:10:00 UTC' in timer
    assert 'Persistent=true' in timer
    assert ' cli schedule run --once' in service
    assert 'OPENROUTER_API_KEY=' not in service
    assert not (tmp_path / 'config').exists()


def test_install_uninstall_touch_only_owned_temporary_units(config, tmp_path, monkeypatch):
    import subprocess

    from nowcast.scheduler import install

    home = tmp_path / 'config'
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home))
    monkeypatch.setattr('shutil.which', lambda name: '/usr/bin/' + name)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='active', stderr='')

    monkeypatch.setattr('subprocess.run', run)
    root = tmp_path / 'checkout'
    other = home / 'systemd/user/other.service'
    other.parent.mkdir(parents=True)
    other.write_text('other service')
    install(config, root, confirm=True)
    files = installation_preview(config, root)
    assert all(Path(name).read_text() == body for name, body in files.items())
    install(config, root, confirm=True, remove=True)
    assert all(not Path(name).exists() for name in files)
    assert other.read_text() == 'other service'
    assert any('enable' in command for command in calls)


def test_cron_fallback_preserves_other_entries_and_is_idempotent(config, tmp_path):
    from nowcast.scheduler import cron_entry, edit_crontab

    current = '7 8 * * * existing-command\n'
    entry = cron_entry(config, tmp_path / 'checkout')
    result = edit_crontab(current, entry)
    assert result.startswith(current)
    assert edit_crontab(result, entry) == result
    assert edit_crontab(result, entry, remove=True) == current
    assert '--automatic' in entry


def completed_then_wait(config, counter, ready):
    import time

    class SharedProvider:
        def complete(self, model, messages, max_tokens=None):
            with counter.get_lock():
                counter.value += 1
            return LLMResult(
                text=ExtractionRecord(
                    schema_version='v1', document_id='crash-probe'
                ).model_dump_json(),
                model=model,
            )

    caller = make_caller(config, inner=SharedProvider(), clock=Clock(), sleep=lambda seconds: None)
    caller.complete(config.llm.models[0], [{'role': 'user', 'content': 'crash-probe'}])
    ready.send(True)
    time.sleep(60)


def test_kill_after_response_then_resume_sends_no_duplicate_request(config):
    context = multiprocessing.get_context('fork')
    counter = context.Value('i', 0)
    parent, child = context.Pipe()
    local = configured(config)
    process = context.Process(target=completed_then_wait, args=(local, counter, child))
    process.start()
    try:
        assert parent.poll(15)
        assert parent.recv()
        process.kill()
        process.join(5)
        provider = Provider()
        result = make_caller(local, inner=provider, clock=Clock()).complete(
            local.llm.models[0], [{'role': 'user', 'content': 'crash-probe'}]
        )
        assert result.cached and counter.value == 1 and provider.calls == 0
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)


def test_actual_worker_executes_canonical_doctor_and_records_artifacts(config, monkeypatch):
    from nowcast.contracts import RunRequest
    from nowcast.worker import run

    monkeypatch.delenv('NOWCAST_JOB_ID', raising=False)
    monkeypatch.delenv('NOWCAST_JOB_DATABASE', raising=False)
    store = store_for(config)
    row, _ = store.create(
        RunRequest(
            workflow_id='command', submission_id='doctor-service-check', command_id='doctor'
        ),
        config,
        CONFIG,
    )
    run(store, row['id'])
    assert store.get(row['id'])['status'] == 'succeeded'
    with store.engine.connect() as connection:
        assert (
            connection.execute(
                text('SELECT count(*) FROM artifacts WHERE job_id=:id'), {'id': row['id']}
            ).scalar_one()
            == 1
        )
    assert not __import__('os').environ.get('NOWCAST_JOB_ID')


def test_start_models_waits_for_day_zero_approval_and_acceptance(config, monkeypatch):
    from nowcast.errors import DataError

    scheduler, _clock, provider, _order = scheduler_fixture(config, monkeypatch)
    with pytest.raises(DataError):
        scheduler.start_models()
    scheduler.run_once()
    scheduler.set_state('models_confirmed', True)
    scheduler.set_state('models_hold', 'acceptance checks')
    with pytest.raises(DataError):
        scheduler.start_models()
    scheduler.set_state('models_hold', None)
    scheduler.start_models()
    plan = scheduler.snapshot()
    assert plan['days'][0]['planned_requests'] == 4
    assert len(plan['days']) == 2
    scheduler.run_once()
    assert provider.calls == 4
    assert scheduler.used() == 4


def test_changed_cap_updates_calendar_without_redrawing_scope(config, monkeypatch):
    scheduler, _clock, _provider, _order = scheduler_fixture(config, monkeypatch)
    before = scheduler.snapshot()
    scheduler.config = dataclasses.replace(
        scheduler.config, llm=dataclasses.replace(scheduler.config.llm, requests_per_day=1000)
    )
    after = scheduler.snapshot()
    assert before['forecast']['releases'] == after['forecast']['releases']
    assert after['forecast']['daily_limit'] == 1000
    assert after['forecast']['model_days'] == 1
    assert after['days'][1]['planned_requests'] == 6


def test_acceptance_hold_blocks_an_approved_due_model_day(config, monkeypatch):
    scheduler, clock, provider, _order = scheduler_fixture(config, monkeypatch)
    scheduler.run_once()
    scheduler.set_state('models_confirmed', True)
    scheduler.set_state('models_hold', 'website checks')
    clock.sleep(86400)
    scheduler.run_once()
    assert not provider.calls
    assert (
        next(t for t in scheduler.tasks() if t['task_key'] == 'bakeoff')['last_error']
        == 'website checks'
    )


def test_systemd_working_directory_is_an_absolute_value_without_quotes(config, tmp_path):
    root = tmp_path / 'checkout with spaces'
    proposal = installation_preview(config, root, tmp_path / 'config')
    service = next(value for key, value in proposal.items() if key.endswith('.service'))
    assert 'WorkingDirectory=' + str(root.resolve()) + '\n' in service
