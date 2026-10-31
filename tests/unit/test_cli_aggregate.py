"""Step 11: the aggregate stage runs through the real CLI and writes index-level output."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nowcast.cli import main

REPO = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = REPO / 'configs' / 'config.yaml'


def _write_inputs(data: Path, companies: int = 12) -> None:
    """Write a constituents file, a consolidated extraction parquet and no review queue."""
    rows = [
        {
            'ticker': f'T{index:03d}',
            'cik': f'{index + 1:010d}',
            'effective_from': '2024-01-01',
            'effective_to': '',
        }
        for index in range(companies)
    ]
    (data / 'universe').mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(data / 'universe' / 'constituents.csv', index=False)
    extractions = []
    for index in range(companies):
        extractions.append(
            {
                'document_id': f'doc-{index}',
                'cik': f'{index + 1:010d}',
                'report_date': '2025-04-20',
                'model': 'fake/model:free',
                'record_confidence': 0.9,
                'reported_eps': 1.1,
                'consensus_eps': 1.0,
                'prior_year_eps': 1.0,
                'revenue': 1.0,
                'eps_basis': 'gaap',
                'guidance_direction': 'raised',
                'guidance_metric': 'revenue',
                'tone': 'confident',
            }
        )
    target = data / 'extractions' / 'extractions.parquet'
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(extractions).to_parquet(target, index=False)


def _run(data: Path, *extra: str) -> int:
    """Run the CLI against the temp data root."""
    return main(
        ['aggregate', '--config', str(CONFIG_PATH), *extra],
    )


def test_cli_aggregate_writes_index_level_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Twelve companies in one season produce an unsuppressed index row on disk."""
    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setenv('DATA_DIR', str(data))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('SEC_USER_AGENT', 'nowcast-tests tests@example.com')
    _write_inputs(data)

    code = _run(data)
    assert code == 0, capsys.readouterr().err
    written = pd.read_parquet(data / 'aggregates' / 'index_aggregates.parquet')
    assert len(written) == 1
    assert bool(written.loc[0, 'suppressed']) is False
    assert written.loc[0, 'n_reported'] == 12
    assert (data / 'aggregates' / 'index_aggregates.csv').is_file()
    # No identifier column reached the output.
    forbidden = {'ticker', 'cik', 'document_id', 'company_name'}
    assert not forbidden.intersection(column.lower() for column in written.columns)


def test_cli_aggregate_refuses_identifier_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The privacy guardrail is a real check, and it fires."""
    from nowcast.aggregation.aggregate import assert_index_level_only
    from nowcast.errors import DataError

    frame = pd.DataFrame({'as_of_date': ['2025-04-20'], 'cik': ['0000000001']})
    with pytest.raises(DataError, match='index-level'):
        assert_index_level_only(frame)


def test_run_all_stops_at_first_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failing stage ends the run instead of continuing into later stages."""
    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setenv('DATA_DIR', str(data))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('SEC_USER_AGENT', 'nowcast-tests tests@example.com')
    # No constituents file: build-constituents would try the network, so point ingest at
    # a missing file instead and check the run stops there with a non-zero code.
    code = main(
        [
            'run-all',
            '--config',
            str(CONFIG_PATH),
            '--set',
            'data.constituents_csv=missing.csv',
        ]
    )
    assert code != 0
    assert not (data / 'extractions' / 'extractions.parquet').exists()
