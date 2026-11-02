"""A small mutation check over the modules whose bugs would matter most.

Each mutant is one exact textual edit to one source file. The mutant is written in
place, the module's tests are run, and the original bytes are restored in a `finally`
block. A mutant that the tests still pass is printed as SURVIVED: it marks a behaviour
the suite does not pin.

This is deliberately not a full mutation-testing tool: the mutations are the ones a
person would actually make while editing this code, and each is paired with the test
file that should catch it. Run it from the repository root:

    python scripts/mutation_check.py --verbose
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VALIDATORS = 'src/nowcast/extraction/validators.py'
EDGAR = 'src/nowcast/ingestion/edgar.py'
RUNNER = 'src/nowcast/extraction/runner.py'
AGGREGATE = 'src/nowcast/aggregation/aggregate.py'
UNITS = 'src/nowcast/extraction/units.py'
PROMPTS = 'src/nowcast/llm/prompts.py'
COMPOSITION = 'src/nowcast/llm/composition.py'
REVIEW = 'src/nowcast/extraction/review_queue.py'
THROTTLE = 'src/nowcast/llm/throttle.py'
PACKING = 'src/nowcast/parsing/packing.py'
CALLER = 'src/nowcast/llm/caller.py'

VALIDATOR_TESTS = ['tests/unit/test_validators.py']
EDGAR_TESTS = ['tests/unit/test_edgar.py']
RUNNER_TESTS = ['tests/unit/test_runner.py', 'tests/unit/test_truncation.py']
AGGREGATE_TESTS = ['tests/unit/test_aggregate.py']
UNITS_TESTS = ['tests/unit/test_units.py']
PROMPT_TESTS = ['tests/unit/test_prompts.py']
AUTH_TESTS = ['tests/unit/test_auth_errors.py']
THROTTLE_TESTS = ['tests/unit/test_throttle.py']
PACKING_TESTS = ['tests/unit/test_packing.py']
TRUNCATION_TESTS = ['tests/unit/test_truncation.py']
REBUILD_TESTS = ['tests/unit/test_rebuild.py']
REVIEW_TESTS = ['tests/unit/test_runner.py', 'tests/unit/test_review_queue.py']


@dataclass(frozen=True)
class Mutant:
    """One textual edit and the tests expected to notice it."""

    name: str
    path: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTANTS = (
    Mutant(
        'delivery: label sheet includes stale scope',
        'src/nowcast/operations.py',
        'frame = frame[frame.document_id.isin(eligible)]',
        'frame = frame',
        ('tests/integration/test_inspection.py',),
    ),
    Mutant(
        'delivery: private bakeoff sample exposed',
        'src/nowcast/inspection.py',
        "if node == 'model-bakeoff':",
        'if False:',
        ('tests/integration/test_inspection.py',),
    ),
    Mutant(
        'delivery: demo hides real releases',
        'src/nowcast/api.py',
        'show_demo = not path.is_file() and not real_releases',
        'show_demo = not path.is_file()',
        ('tests/integration/test_inspection.py',),
    ),
    Mutant(
        'delivery: paid CLI override accepted',
        'src/nowcast/cli.py',
        "if any(not model.endswith(':free') for model in models):",
        'if False:',
        ('tests/integration/test_inspection.py',),
    ),
    Mutant(
        'delivery: acceptance hold ignored',
        'src/nowcast/scheduler.py',
        "if model and self.state('models_hold'):",
        'if False:',
        ('tests/integration/test_schedule.py',),
    ),
    Mutant(
        'delivery: upstream inspector hash ignored',
        'src/nowcast/artifacts.py',
        "raise ValueError('upstream artifacts changed')",
        'pass',
        ('tests/integration/test_inspection.py',),
    ),
    Mutant(
        'network: reserved default port restored',
        'src/nowcast/cli.py',
        "sub.add_argument('--port', type=int, default=8767, help='website TCP port')",
        "sub.add_argument('--port', type=int, default=8765, help='website TCP port')",
        ('tests/unit/test_contract_properties.py',),
    ),
    Mutant(
        'network: local interface host rejected',
        'src/nowcast/api.py',
        'allowed_hosts = local_hosts | ({server[0]} if server else set())',
        'allowed_hosts = local_hosts',
        ('tests/integration/test_controls.py',),
    ),
    Mutant(
        'membership: unmapped identifiers reach SEC',
        'src/nowcast/cli.py',
        "raise DataError('membership contains unmapped CIKs; resolve them before SEC ingestion')",
        'pass',
        ('tests/unit/test_final_safeguards.py',),
    ),
    Mutant(
        'telemetry: unknown tokens reported as zero',
        'src/nowcast/api.py',
        "tokens['recorded_' + column] = int(measured.sum()) if not measured.empty else None",
        "tokens['recorded_' + column] = int(measured.sum())",
        ('tests/integration/test_controls.py',),
    ),
    Mutant(
        'scope: primary request count doubled',
        'src/nowcast/ingestion/universe/builder.py',
        'requests = self.documents',
        'requests = self.documents * 2',
        ('tests/unit/test_subset_and_estimate.py',),
    ),
    # validators.py
    Mutant(
        'quote threshold becomes <=',
        VALIDATORS,
        'if verify_quote(quote, source) < float(config.extraction.quote_match_min_ratio):',
        'if verify_quote(quote, source) <= float(config.extraction.quote_match_min_ratio):',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'confidence penalty dropped',
        VALIDATORS,
        "issues.append(Issue(field, 'quote_missing', 'value present without evidence'))\n        adjust(confidence * penalty)",
        "issues.append(Issue(field, 'quote_missing', 'value present without evidence'))\n        adjust(confidence)",
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'number-in-quote check dropped',
        VALIDATORS,
        "if field.evidence_quote and not number_in_quote(\n            float(field.value),\n            field.evidence_quote,\n            span.unit_context if span is not None and name == 'revenue' else '',\n            percent=name == 'revenue_yoy_growth',\n        ):",
        'if False:',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'empty-extraction check inverted',
        VALIDATORS,
        'return all(getattr(record, name).value is None for name in CORE_NUMERIC_FIELDS)',
        'return any(getattr(record, name).value is None for name in CORE_NUMERIC_FIELDS)',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'low-confidence boundary becomes strict',
        VALIDATORS,
        'if field.value is not None and field.confidence < minimum:',
        'if field.value is not None and field.confidence > minimum:',
        tuple(VALIDATOR_TESTS),
    ),
    # edgar.py
    Mutant(
        'earnings item filter removed',
        EDGAR,
        'if wanted_items and not item_codes.intersection(wanted_items):',
        'if False:',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'window lower bound exclusive',
        EDGAR,
        'if not lower <= filing_date <= upper:',
        'if not lower < filing_date <= upper:',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'non-text exhibits allowed',
        EDGAR,
        'if not is_text_document(filename, allowed):',
        'if False:',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'abort threshold ignores the run',
        EDGAR,
        'if active_report.consecutive_blocked >= abort_after:',
        'if active_report.consecutive_blocked > abort_after + 1000:',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'blocked counter never resets',
        EDGAR,
        '            self.consecutive_blocked = 0',
        '            pass',
        tuple(EDGAR_TESTS),
    ),
    Mutant(
        'content-length check skipped',
        EDGAR,
        'if expected and not encoding and arrived and arrived != expected:',
        'if False:',
        tuple(EDGAR_TESTS),
    ),
    # runner.py
    Mutant(
        'earnings-item index filter removed',
        RUNNER,
        'if not has_earnings_item(items, wanted_items):',
        'if False:',
        tuple(RUNNER_TESTS),
    ),
    Mutant(
        'fingerprint drops validation settings',
        RUNNER,
        "digest.update(json.dumps(validation_settings(config), sort_keys=True).encode('utf-8'))",
        'pass',
        tuple(RUNNER_TESTS),
    ),
    Mutant(
        'truncation reported as llm_failed',
        RUNNER,
        "reason = 'truncated' if isinstance(exc, TruncatedCompletion) else 'llm_failed'",
        "reason = 'llm_failed'",
        tuple(RUNNER_TESTS),
    ),
    Mutant(
        'per-document guard removed',
        RUNNER,
        "        except Exception as exc:\n            LOGGER.exception('document failed",
        "        except ZeroDivisionError as exc:\n            LOGGER.exception('document failed",
        tuple(RUNNER_TESTS),
    ),
    Mutant(
        'diagnostics claim no truncation',
        RUNNER,
        "'truncated': prepared.truncated,",
        "'truncated': False,",
        tuple(RUNNER_TESTS + UNITS_TESTS),
    ),
    # units.py
    Mutant(
        'growth fraction correction dropped',
        UNITS,
        'candidates = [value] if abs(value) >= 1 else [value, value * 100]',
        'candidates = [value]',
        tuple(UNITS_TESTS),
    ),
    Mutant(
        'units canonicalisation dropped',
        UNITS,
        "return f'{recognised_currency} {recognised_scale}'",
        'return text or None',
        tuple(UNITS_TESTS),
    ),
    Mutant(
        'number-in-source check dropped',
        VALIDATORS,
        "if not number_in_quote(\n                float(field.value),\n                window,\n                span.unit_context if span is not None and name == 'revenue' else '',\n                percent=name == 'revenue_yoy_growth',\n            ):",
        'if False:',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'vocabulary check dropped',
        VALIDATORS,
        'if vocabulary and str(field.value).lower().strip() not in set(vocabulary):',
        'if False:',
        tuple(VALIDATOR_TESTS),
    ),
    Mutant(
        'text fields drop out of the confidence check',
        VALIDATORS,
        'for name in (*NUMERIC_FIELDS, *TEXT_FIELDS):',
        'for name in NUMERIC_FIELDS:',
        tuple(VALIDATOR_TESTS),
    ),
    # composition.py
    Mutant(
        '401 retried like a transient error',
        COMPOSITION,
        'except (BudgetExceeded, AuthError, ModelNotFound):',
        'except (BudgetExceeded, ModelNotFound):',
        tuple(AUTH_TESTS),
    ),
    Mutant(
        'cache key drops reasoning settings',
        COMPOSITION,
        "'reasoning': self._config.llm.reasoning_params(),",
        "'reasoning': {},",
        tuple(AUTH_TESTS),
    ),
    # review_queue.py
    Mutant(
        'queue append instead of replace',
        REVIEW,
        "    kept = existing[keep['_merge'] == 'left_only'].reset_index(drop=True)",
        '    kept = existing.reset_index(drop=True)',
        tuple(REVIEW_TESTS),
    ),
    # edgar.py gzip
    Mutant(
        'gzip body length compared to its decoded size',
        EDGAR,
        '    if expected and not encoding and arrived and arrived != expected:',
        '    if expected and arrived and arrived != expected:',
        tuple(EDGAR_TESTS),
    ),
    # aggregate.py
    Mutant(
        'per-metric observation minimum ignored',
        AGGREGATE,
        "if suppressed or count < metric_minimum:\n                    row[name] = float('nan')",
        "if False:\n                    row[name] = float('nan')",
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'dedupe confidence ignored',
        AGGREGATE,
        "        frame['confidence'] = pd.to_numeric(frame['record_confidence'], errors='coerce')",
        "        frame['confidence'] = 0.0",
        tuple(AGGREGATE_TESTS),
    ),
    # validators.py — B2
    Mutant(
        'number_in_quote accepts any scale',
        VALIDATORS,
        "readings = (printed,) if match['percent'] else (printed, printed * scale)",
        'readings = (printed, printed * scale, printed * 1e3, printed * 1e6, printed * 1e9)',
        tuple(VALIDATOR_TESTS),
    ),
    # throttle.py — H-a
    Mutant(
        'per-minute limit ignored',
        THROTTLE,
        'if len(self._sent) >= self._per_minute',
        'if False',
        tuple(THROTTLE_TESTS),
    ),
    Mutant(
        'cooldown ignored',
        THROTTLE,
        'wait = max(wait_cooldown, wait_rate, 0.0)',
        'wait = max(wait_rate, 0.0)',
        tuple(THROTTLE_TESTS),
    ),
    # packing.py — B5
    Mutant(
        'phrase priority ignored',
        PACKING,
        'ordered = tuple(p for p in priority if p in pool) + tuple(p for p in pool if p not in priority)',
        'ordered = pool',
        tuple(PACKING_TESTS),
    ),
    # caller.py — H-b
    Mutant(
        'length truncation needs empty content',
        CALLER,
        "if empty or finish == 'length':",
        'if empty:',
        tuple(TRUNCATION_TESTS),
    ),
    # runner.py — H-c
    Mutant(
        'stale results consolidated anyway',
        RUNNER,
        "if str(payload.get('fingerprint') or '') != current:",
        'if False:',
        tuple(RUNNER_TESTS),
    ),
    # rebuild.py — B6
    Mutant(
        'populated target replaced without force',
        'src/nowcast/ingestion/rebuild.py',
        'if not force:',
        'if False:',
        tuple(REBUILD_TESTS),
    ),
    # aggregate.py — B3 / B4
    Mutant(
        'beat rate computed without consensus',
        AGGREGATE,
        "if name == 'beat_rate' and not has_consensus:",
        'if False:',
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'field flag drops the whole row',
        AGGREGATE,
        "counted = reported_docs[~reported_docs['blocked']]",
        "counted = reported_docs[~reported_docs['in_review']]",
        tuple(AGGREGATE_TESTS),
    ),
    # packing.py — B5
    Mutant(
        'windows allocated in document order',
        PACKING,
        'merged.sort(key=lambda item: (item[2], item[0]))',
        'merged.sort(key=lambda item: item[0])',
        tuple(PACKING_TESTS),
    ),
    # prompts.py
    Mutant(
        'prompt hash drops few-shots',
        PROMPTS,
        'if bundle.few_shots:',
        'if False:',
        tuple(PROMPT_TESTS),
    ),
    # aggregate.py
    Mutant(
        'company collapse removed',
        AGGREGATE,
        '            counted, _duplicate_rows = collapse_to_companies(\n                counted,\n                str(config.aggregation.dedupe_rule),\n                tuple(config.aggregation.model_priority or config.llm.models),\n            )',
        '            _duplicate_rows = 0',
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'share guard removed',
        AGGREGATE,
        'if n_expected and n_reported > n_expected:',
        'if False:',
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'review exclusion computed over the whole season',
        AGGREGATE,
        "excluded = int(reported_docs.loc[reported_docs['in_review'], 'cik'].nunique())",
        "excluded = int(season.loc[season['in_review'], 'cik'].nunique())",
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'beat tolerance comparison inverted',
        AGGREGATE,
        '[graded > tolerance, graded < -tolerance],',
        '[graded >= tolerance, graded <= -tolerance],',
        tuple(AGGREGATE_TESTS),
    ),
    Mutant(
        'counted rows not excluded from metrics',
        AGGREGATE,
        "counted = reported_docs[~reported_docs['blocked']]",
        'counted = reported_docs',
        tuple(AGGREGATE_TESTS),
    ),
)

MUTANTS += (
    Mutant(
        'K1 period ignored',
        VALIDATORS,
        "if year and str(year) in cell.split(']')[0]",
        'if True',
        ('tests/unit/test_plan_repairs.py',),
    ),
    Mutant(
        'K7 consolidation moves files',
        RUNNER,
        'current = _settings_digest(config, payload, model, prompt_digest)',
        'current = (supersede_result(config, path), _settings_digest(config, payload, model, prompt_digest))[1]',
        ('tests/unit/test_plan_repairs.py',),
    ),
    Mutant(
        'K3 summary blocks record',
        REVIEW,
        'return REASON_FIELDS.get(reason, frozenset())',
        "return REASON_FIELDS.get(reason, frozenset({'record'}))",
        ('tests/unit/test_plan_repairs.py',),
    ),
    Mutant(
        'K6 percentage becomes currency',
        VALIDATORS,
        "if percent is not None and bool(match['percent']) != percent:",
        'if False:',
        ('tests/unit/test_plan_repairs.py',),
    ),
    Mutant(
        'K6 sign discarded',
        VALIDATORS,
        'printed = -printed',
        'printed = printed',
        ('tests/unit/test_plan_repairs.py',),
    ),
    Mutant(
        'K8 project directory ignored',
        'src/nowcast/paths.py',
        'base = Path(config.config_dir) / config.paths.project_dir',
        'base = Path(config.config_dir)',
        ('tests/unit/test_plan_repairs.py',),
    ),
    Mutant(
        'K10 receipts ignored',
        'src/nowcast/ingestion/doc_index.py',
        'self.pending.append(json.loads(line))',
        'pass',
        ('tests/unit/test_plan_repairs.py',),
    ),
)

MUTANTS += (
    Mutant(
        'final: implicit CLI source',
        'src/nowcast/cli.py',
        'if not chosen and active.is_file() and not load_index(active).empty:',
        'if False:',
        ('tests/unit/test_final_safeguards.py',),
    ),
    Mutant(
        'final: replacement contents unchecked',
        'src/nowcast/ingestion/rebuild.py',
        'if report.backup_path is not None:',
        'if False:',
        ('tests/unit/test_final_safeguards.py',),
    ),
    Mutant(
        'final: table units leak',
        'src/nowcast/parsing/html.py',
        "rows = ['[table units: ' + (unit_match.group() if unit_match else '') + ']']",
        "rows = ['[table units: ' + unit_match.group() + ']'] if unit_match else []",
        ('tests/unit/test_final_safeguards.py',),
    ),
    Mutant(
        'final: source period ignored',
        'src/nowcast/extraction/validators.py',
        '    return (not years or year is None or str(year) in years) and (\n        not quarters or quarter is None or str(quarter) in quarters\n    )',
        '    return True',
        ('tests/unit/test_final_safeguards.py',),
    ),
    Mutant(
        'final: numeric labels compared as text',
        'src/nowcast/extraction/bakeoff.py',
        "            scores[name] = float(\n                joined.loc[usable, name + '_label']\n                .eq(joined.loc[usable, name + '_model'])\n                .fillna(False)\n                .mean()\n            )\n",
        "            scores[name] = float(\n                joined.loc[usable, name + '_label']\n                .astype(str).eq(joined.loc[usable, name + '_model'].astype(str))\n                .fillna(False)\n                .mean()\n            )\n",
        ('tests/unit/test_final_safeguards.py',),
    ),
    Mutant(
        'final: abandoned queued job ignored',
        'src/nowcast/jobs.py',
        "SELECT id,pid,identity FROM jobs WHERE status IN ('queued','running')",
        "SELECT id,pid,identity FROM jobs WHERE status='running'",
        ('tests/unit/test_final_safeguards.py',),
    ),
    Mutant(
        'final: human panel overwritten',
        'scripts/prepare_review.py',
        'if target.exists():',
        'if False:',
        ('tests/unit/test_final_safeguards.py',),
    ),
    Mutant(
        'final: colspan discarded',
        'src/nowcast/parsing/html.py',
        "colspan = _span(cell.get('colspan', 1), 1000)",
        'colspan = 1',
        ('tests/unit/test_final_safeguards.py',),
    ),
)


def _digest(path: Path) -> str:
    """Return the sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_tests(tests: tuple[str, ...]) -> bool:
    """Return True when the selected tests pass."""
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '--no-header', '-x', *tests],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _apply(path: Path, old: str, new: str) -> None:
    """Replace exactly one occurrence of `old`, refusing an ambiguous mutant."""
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise LookupError(f'mutant text occurs {count} times in {path}: {old[:60]!r}')
    path.write_text(text.replace(old, new), encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    """Run every mutant, restore the sources, and report the survivors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verbose', action='store_true', help='print each mutant as it runs')
    parser.add_argument('--match', default='', help='run mutants whose names contain this text')
    args = parser.parse_args(argv)
    selected = [mutant for mutant in MUTANTS if args.match in mutant.name]
    if not selected:
        parser.error('no matching mutants')
    if not _run_tests(tuple(sorted({test for mutant in selected for test in mutant.tests}))):
        print('BASELINE FAILED: mutants were not run')
        return 2

    survivors: list[str] = []
    broken: list[str] = []
    for index, mutant in enumerate(selected, start=1):
        path = ROOT / mutant.path
        original = path.read_bytes()
        before = _digest(path)
        try:
            _apply(path, mutant.old, mutant.new)
            killed = not _run_tests(mutant.tests)
        except LookupError as exc:
            broken.append(f'{mutant.name}: {exc}')
            killed = True
        finally:
            path.write_bytes(original)
            if _digest(path) != before:  # pragma: no cover - would mean days are over
                raise SystemExit(f'FAILED TO RESTORE {path}; restore it from git now')
        label = 'killed  ' if killed else 'SURVIVED'
        if args.verbose:
            print(f'[{index:2d}/{len(selected)}] {label} {mutant.name}')
        if not killed:
            survivors.append(mutant.name)
    for problem in broken:
        print(f'MALFORMED {problem}')
    print(
        f'{len(selected)} mutants, {len(selected) - len(survivors) - len(broken)} killed, {len(survivors)} survived, {len(broken)} malformed'
    )
    for name in survivors:
        print(f'  SURVIVED {name}')
    return 2 if broken else int(bool(survivors))


if __name__ == '__main__':
    raise SystemExit(main())
