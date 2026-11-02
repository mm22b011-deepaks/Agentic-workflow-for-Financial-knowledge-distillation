from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from typer.testing import CliRunner

from nowcast.app import app
from nowcast.extraction.validators import number_in_quote


@given(st.integers(min_value=1, max_value=1000000))
def test_sign_cannot_flip(value: int) -> None:
    assert number_in_quote(-value, f'Loss ({value:,})')
    assert not number_in_quote(value, f'Loss ({value:,})')


@given(
    st.integers(min_value=1, max_value=10000), st.sampled_from([('million', 1e6), ('billion', 1e9)])
)
def test_scale_is_local(value: int, scale: tuple[str, float]) -> None:
    word, factor = scale
    quote = f'Revenue ${value} {word}; EPS $2.50'
    assert number_in_quote(value * factor, quote)
    assert not number_in_quote(2.5 * factor, quote) or math.isclose(value, 2.5)


def test_typer_preserves_validate_config_behavior() -> None:
    result = CliRunner().invoke(app, ['validate-config', '--config', 'configs/config.yaml'])
    assert result.exit_code == 0, result.output
    assert 'config OK' in result.stdout


@pytest.mark.parametrize('extra,port', [([], 8767), (['--port', '18765'], 18765)])
def test_serve_binds_all_interfaces_on_an_unreserved_default(
    monkeypatch: pytest.MonkeyPatch, extra: list[str], port: int
) -> None:
    calls = {}
    monkeypatch.setattr('nowcast.api.create_app', lambda config: object())
    monkeypatch.setattr('uvicorn.run', lambda app, **kwargs: calls.update(kwargs))
    result = CliRunner().invoke(app, ['serve', *extra])
    assert result.exit_code == 0, result.output
    assert calls['host'] == '0.0.0.0'
    assert calls['port'] == port
