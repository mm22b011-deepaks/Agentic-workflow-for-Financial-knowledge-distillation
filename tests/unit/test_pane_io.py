"""Presentation contracts and the public projection share the same privacy boundary."""

import json

import pandas as pd

from nowcast.inspection import public_frame
from nowcast.workflow_registry import canvas_registry, extension_path


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
