"""Presentation contracts and the public projection share the same privacy boundary."""

import json

import pandas as pd
import pytest

from nowcast.inspection import public_frame
from nowcast.workflow_registry import canvas_registry, extension_path


def test_demo_steps_describe_the_same_data_as_production_steps():
    nodes = {node.id: node for node in canvas_registry().nodes}
    for node, unit, source in [
        ('demo-ingest', 'file', None),
        ('demo-parse', 'text', 'demo-ingest'),
        ('demo-extract', 'record', 'demo-parse'),
        ('demo-validate', 'record', 'demo-extract'),
        ('demo-aggregate', 'index row', 'demo-validate'),
    ]:
        assert nodes[node].io.gives.unit_label == unit
        if source:
            assert nodes[node].io.source == source
            assert nodes[node].io.takes == nodes[source].io.gives
    assert nodes['model-bakeoff'].io.gives.unit_label == 'check'
    assert nodes['rebuild-index'].io.gives.plain_line == 'Files listed in the document index'

    from dataclasses import replace
    from pathlib import Path

    from nowcast.config import ScopeConfig, load_config
    from nowcast.scope import scope_summary

    row = json.loads(Path('web/src/io-demo.json').read_text())['estimate-scope']['rows'][0]
    defaults = load_config('configs/config.yaml', local=False)
    summary = scope_summary(replace(defaults, scope=ScopeConfig(companies=125, seasons=4)))
    for key in ('companies', 'releases', 'base_requests', 'expected_requests', 'model_days'):
        assert row[key] == summary[key], key


@pytest.mark.parametrize('agreement', [True, False])
def test_offline_demo_reports_a_reference_check_with_safe_details(config, agreement):
    from pathlib import Path

    from nowcast.inspection import frame_for
    from nowcast.jobs import store_for
    from nowcast.paths import Paths

    path = Paths.from_config(config).resolve('demo/verification.json')
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {'pandas_agreement': agreement, 'documents': 500, 'companies': 125, 'seasons': 4}
        )
    )
    frame = public_frame(frame_for(config, Path('configs/config.yaml'), store_for(config), 'demo'))
    assert len(frame) == 1
    assert frame.iloc[0].status == ('ok' if agreement else 'failed')
    assert frame.iloc[0].checks == 1
    assert frame.iloc[0].releases == 500
    assert len(frame.columns) >= 3


def test_demo_aggregates_count_one_row_per_kpi(config):
    from pathlib import Path

    from nowcast.inspection import frame_for, stages
    from nowcast.jobs import store_for
    from nowcast.paths import Paths

    path = Paths.from_config(config).resolve('demo/index.json')
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                'snapshots': [
                    {'season_year': 2025, 'season_quarter': 1, 'n_expected': 125, 'n_reported': 125}
                ]
            }
        )
    )
    store = store_for(config)
    frame = frame_for(config, Path('configs/config.yaml'), store, 'demo-aggregate')
    state = next(
        n
        for n in stages(config, Path('configs/config.yaml'), store).nodes
        if n.id == 'demo-aggregate'
    )
    assert len(frame) == state.out_count == 4
    assert frame.metric.nunique() == 4


def test_settings_count_one_file_instead_of_individual_settings(config):
    from pathlib import Path

    from nowcast.inspection import pane
    from nowcast.jobs import store_for

    store = store_for(config)
    for node in ('validate-config', 'run-all', 'doctor'):
        result = pane(config, Path('configs/config.yaml'), store, node, 'input')
        assert result.total == 1
        assert len(result.rows[0]) >= 3


def test_export_and_report_examples_show_files_without_report_text(config):
    from pathlib import Path

    from nowcast.inspection import frame_for
    from nowcast.jobs import store_for
    from nowcast.paths import Paths

    paths = Paths.from_config(config)
    for name, body in [
        ('exports/index.json', '{"snapshots":[]}'),
        ('exports/kpis.json', '{"records":[]}'),
        (config.reporting.report_path, 'PRIVATE COMPANY AND QUOTE'),
    ]:
        path = paths.resolve(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    store = store_for(config)
    for node, count in [('export', 2), ('report', 1)]:
        frame = public_frame(frame_for(config, Path('configs/config.yaml'), store, node))
        assert len(frame) == count
        assert len(frame.columns) >= 3
        assert frame.size_bytes.gt(0).all()
        assert 'PRIVATE' not in frame.to_json()
        assert 'QUOTE' not in frame.to_json()


def test_frozen_selection_keeps_counts_without_membership_identifiers(config):
    from pathlib import Path

    from nowcast.inspection import frame_for
    from nowcast.jobs import store_for
    from nowcast.paths import Paths

    path = Paths.from_config(config).resolve('manifests/panel.json')
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                'companies': ['PRIVATE-COMPANY'],
                'seasons': ['2025Q1'],
                'pairs': [{'cik': 'PRIVATE-COMPANY', 'season': '2025Q1'}],
            }
        )
    )
    frame = public_frame(
        frame_for(config, Path('configs/config.yaml'), store_for(config), 'freeze-panel')
    )
    assert frame.iloc[0].companies == frame.iloc[0].seasons == frame.iloc[0].company_quarters == 1
    assert len(frame.columns) >= 3
    assert 'PRIVATE' not in frame.to_json()


def test_review_input_counts_flags_instead_of_checked_records(config):
    from pathlib import Path

    from nowcast.inspection import pane
    from nowcast.jobs import store_for
    from nowcast.paths import Paths

    path = Paths.from_config(config).resolve(config.extraction.review_queue_path)
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        [{'document_id': 'PRIVATE', 'field': 'reported_eps', 'reason': 'eps_missing'}] * 3
    ).to_parquet(path)
    result = pane(config, Path('configs/config.yaml'), store_for(config), 'review', 'input')
    assert result.total == 3
    assert len(result.rows[0]) >= 3
    assert 'PRIVATE' not in json.dumps(result.rows)


def test_every_node_has_generated_io():
    fields = json.loads((extension_path().parent / 'io-fields.schema.json').read_text())[
        'properties'
    ]
    units = {
        'member',
        'company-quarter',
        'release',
        'file',
        'text',
        'record',
        'check',
        'flag',
        'index row',
        'KPI',
    }
    for node in canvas_registry().nodes:
        for io in (node.io.takes, node.io.gives):
            assert io.unit_label in units
            assert len(io.plain_line.split()) <= 8
        assert node.io.summaries
        for field in node.io.example_fields:
            assert field.label == fields[field.key]['title']
            assert '_' not in field.label


def test_public_projection_keeps_attributes_without_identifiers_or_quotes():
    frame = pd.DataFrame(
        [
            {
                'cik': '0000123456',
                'document_id': 'SECRET-DOC',
                'ticker': 'PRIVATE',
                'company': 'Private Corp',
                'sector': 'Secret sector',
                'raw_path': '/private/name.htm',
                'effective_from': '2019-03-01',
                'effective_to': None,
                'report_date': '2025-04-24',
                'chars': 3800,
                'size_bytes': 38000,
                'record': json.dumps(
                    {
                        'reported_eps': {
                            'value': 1.2,
                            'confidence': 0.9,
                            'evidence_quote': 'SECRET QUOTE',
                        }
                    }
                ),
            }
        ]
    )
    public = public_frame(frame)
    encoded = public.to_json()
    for secret in [
        '0000123456',
        'SECRET-DOC',
        'PRIVATE',
        'Private Corp',
        'Secret sector',
        '/private',
        'SECRET QUOTE',
    ]:
        assert secret not in encoded
    row = public.iloc[0]
    assert row.effective_from == '2019-03-01'
    assert row.season == '2025Q2'
    assert row.reported_eps == 1.2
    assert row.eps_confidence == 0.9
    assert row.chars == 3800
    assert len(row.member_token) == 64
    assert public_frame(frame).member_token.iloc[0] == row.member_token
    assert len(public.columns) >= 3


def test_projection_rejects_identifier_strings_in_attribute_columns():
    public = public_frame(
        pd.DataFrame(
            [
                {
                    'chars': 'SECRET',
                    'report_date': 'PRIVATE',
                    'outcome': 'SECRET',
                    'items': 'CIK123',
                    'season': 'SECRET',
                    'record': '{}',
                }
            ]
        )
    )
    assert 'SECRET' not in public.to_json()
    assert 'PRIVATE' not in public.to_json()
    assert 'CIK123' not in public.to_json()


def test_public_projection_keeps_flat_values_and_valid_management_tones():
    flat = public_frame(
        pd.DataFrame(
            [
                {
                    'reported_eps': 1.2,
                    'revenue': 38000000,
                    'tone': 'confident',
                    'guidance_presence': 'provided',
                }
            ]
        )
    )
    assert flat.iloc[0].reported_eps == 1.2
    assert flat.iloc[0].revenue == 38000000
    assert flat.iloc[0].tone == 'confident'
    assert flat.iloc[0].guidance_presence == 'provided'
    nested = public_frame(pd.DataFrame([{'record': json.dumps({'tone': {'value': 'cautious'}})}]))
    assert nested.iloc[0].tone == 'cautious'
    hidden = public_frame(
        pd.DataFrame(
            [
                {
                    'reported_eps': 'SECRET',
                    'revenue': 'PRIVATE',
                    'tone': 'Private company',
                    'guidance_presence': 'CIK123',
                }
            ]
        )
    )
    assert not any(
        value in hidden.to_json() for value in ('SECRET', 'PRIVATE', 'Private company', 'CIK123')
    )


def test_filing_dates_and_currency_remain_readable_without_identifiers():
    frame = public_frame(
        pd.DataFrame(
            [
                {
                    'cik': '0000123456',
                    'accession': 'PRIVATE-ACCESSION',
                    'filing_date': '2025-04-24',
                    'items': '2.02',
                    'currency': 'USD',
                }
            ]
        )
    )
    assert frame.iloc[0].report_date == '2025-04-24'
    assert frame.iloc[0].season == '2025Q2'
    assert frame.iloc[0].currency == 'USD'
    assert len(frame.iloc[0].release_token) == 64
    assert 'PRIVATE' not in frame.to_json()
    for currency in ('PRIVATE', 'SECRET', 'ABC'):
        hidden = public_frame(pd.DataFrame([{'currency': currency}]))
        assert currency not in hidden.to_json()


def test_index_presentation_is_one_kpi_per_quarter(config):
    from nowcast.inspection import index_rows

    frame = pd.DataFrame(
        [
            {
                'season_year': 2025,
                'season_quarter': 1,
                'n_expected': 40,
                'n_obs_growth': 31,
                'eps_growth_agg': 0.042,
                'metric_status_eps_growth_agg': 'ok',
                'suppressed': False,
            }
        ]
    )
    rows = index_rows(config, frame)
    assert len(rows) == 4
    eps = rows.loc[rows.metric.eq('EPS growth proxy')].iloc[0]
    assert eps.season == '2025Q1'
    assert eps.metric_value == 0.042
    assert eps.coverage == 31 / 40
    assert eps.threshold == config.aggregation.min_observations / 40
    assert eps['pass']


def test_plan_uses_nested_scope_instead_of_outer_report(config, tmp_path, monkeypatch):
    from nowcast.inspection import frame_for, stages
    from nowcast.jobs import store_for

    path = tmp_path / 'estimate-scope.json'
    path.write_text(
        json.dumps(
            {
                'companies': 1,
                'quarters': 4,
                'documents': 4,
                'scope_plan': {
                    'companies': 40,
                    'seasons': ['2025Q1', '2025Q2', '2025Q3', '2025Q4'],
                    'releases': 160,
                    'base_requests': 160,
                    'model_days': 4,
                },
            }
        )
    )
    monkeypatch.setattr(
        'nowcast.inspection.source_files',
        lambda config, config_path, node: [path] if node == 'estimate-scope' else [],
    )
    monkeypatch.setattr('nowcast.extraction.runner.load_documents', lambda *args: [])
    monkeypatch.setattr('nowcast.scope.select_documents', lambda *args: [])
    store = store_for(config)
    plan = frame_for(config, path, store, 'estimate-scope')
    assert plan.iloc[0].companies == 40
    assert plan.iloc[0].seasons == 4
    assert public_frame(plan).iloc[0].releases == 160
    state = next(n for n in stages(config, path, store).nodes if n.id == 'estimate-scope')
    assert state.out_count == 160
