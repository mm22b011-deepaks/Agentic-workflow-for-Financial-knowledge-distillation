from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from nowcast.config import Config
from nowcast.errors import DataError

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


def members(count=60):
    return pd.DataFrame(
        [
            {
                'ticker': f'T{i}',
                'cik': f'{i + 1:010d}',
                'effective_from': pd.Timestamp('2024-01-01'),
                'effective_to': pd.NaT,
            }
            for i in range(count)
        ]
    )


def test_default_scope_is_fixed_and_uses_completed_seasons(config: Config):
    from nowcast.scope import freeze_scope, scope_summary

    panel = freeze_scope(config, members(), now=NOW)
    assert len(panel['companies']) == 40
    assert panel['seasons'] == ['2025Q4', '2026Q1', '2026Q2', '2026Q3']
    assert len(panel['pairs']) == 160
    assert len({row['cik'] for row in panel['pairs']}) == 40
    assert panel == freeze_scope(config, members(), now=NOW)
    summary = scope_summary(config, now=NOW)
    assert summary['releases'] == 160
    assert summary['base_requests'] == 160
    assert summary['daily_capacity'] == 40
    assert summary['model_days'] == 5
    assert summary['expected_requests'] == 205


@pytest.mark.parametrize('profile,size', [('small', 20), ('standard', 40), ('large', 100)])
def test_presets(profile, size, config):
    from nowcast.scope import scope_summary

    settings = dataclasses.replace(config, scope=dataclasses.replace(config.scope, profile=profile))
    assert scope_summary(settings, now=NOW)['releases'] == size * 4


def test_scope_refuses_silent_panel_redraw(config):
    from nowcast.scope import freeze_scope

    first = freeze_scope(config, members(), now=NOW)
    changed = dataclasses.replace(config, scope=dataclasses.replace(config.scope, seed=99))
    with pytest.raises(DataError, match='frozen'):
        freeze_scope(changed, members(), now=NOW)
    assert freeze_scope(config, members(), now=NOW) == first
    with pytest.raises(DataError, match='frozen'):
        freeze_scope(config, members(61), now=NOW)


def test_scope_warning_is_numeric_and_panel_membership_is_point_in_time(config, caplog):
    from nowcast.scope import freeze_scope

    settings = dataclasses.replace(
        config, scope=dataclasses.replace(config.scope, profile='custom', companies=3, seasons=4)
    )
    frame = members(4)
    frame.loc[3, 'effective_from'] = pd.Timestamp('2026-05-01')
    panel = freeze_scope(settings, frame, now=NOW)
    assert '0000000004' not in panel['companies']
    assert '3 < 10' in caplog.text
    assert len(panel['pairs']) == 12
