"""Shared test fixtures and a canned-reply FakeCaller."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nowcast.config import Config, load_config
from nowcast.llm.caller import LLMResult

REPO_ROOT = Path(__file__).resolve().parent.parent


class FakeCaller:
    """Deterministic caller returning canned text and recording every call."""

    def __init__(
        self, replies: list[str] | str | None = None, fail_on_call: int | None = None
    ) -> None:
        """Store the canned replies and the optional failing call index."""
        if replies is None:
            replies = ['{}']
        self.replies: list[str] = [replies] if isinstance(replies, str) else list(replies)
        self.fail_on_call = fail_on_call
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> LLMResult:
        """Return the next canned reply, or raise when the call index matches."""
        index = len(self.calls)
        self.calls.append({'model': model, 'messages': messages})
        if self.fail_on_call is not None and index == self.fail_on_call:
            raise RuntimeError(f'fake failure on call {index}')
        text = self.replies[index % len(self.replies)] if self.replies else ''
        return LLMResult(text=text, model=model)

    @property
    def call_count(self) -> int:
        """Return how many completions were requested."""
        return len(self.calls)


@pytest.fixture(scope='session')
def repo_root() -> Path:
    """Return the repository root directory."""
    return REPO_ROOT


@pytest.fixture(scope='session')
def base_config(repo_root: Path) -> Config:
    """Return the project config with output paths redirected into a temp root."""
    return load_config(repo_root / 'configs' / 'config.yaml')


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_config: Config) -> Iterator[Path]:
    """Point DATA_DIR at a temp directory so tests never touch real outputs."""
    data = tmp_path / 'data'
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(base_config.runtime.data_dir_env, str(data))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('SEC_USER_AGENT', 'nowcast-tests tests@example.com')
    yield data


@pytest.fixture
def config(workdir: Path, base_config: Config) -> Config:
    """Return the project config bound to the temp data directory."""
    return base_config
