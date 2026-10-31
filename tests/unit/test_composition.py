"""N1: the live path must be composed with retry and cache, through the real entry point."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nowcast.config import Config, extractions_dir, resolve_data_path
from nowcast.errors import RateLimited
from nowcast.extraction import runner
from nowcast.extraction.runner import Document, run_extraction
from nowcast.llm.caller import LLMResult

REPLY = json.dumps(
    {
        'schema_version': 'v1',
        'document_id': 'x',
        'fiscal_year': 2026,
        'fiscal_quarter': 1,
        'reported_eps': {
            'value': 0.55,
            'evidence_quote': 'earnings per share were $0.55',
            'confidence': 0.9,
        },
    }
)
SOURCE = 'GAAP earnings per share were $0.55.'


def _documents(tmp_path: Path, count: int = 1) -> list[Document]:
    """Create document stubs whose raw files hold the source text."""
    documents: list[Document] = []
    for index in range(count):
        path = tmp_path / f'doc{index}.txt'
        path.write_text(SOURCE, encoding='utf-8')
        documents.append(
            Document(
                document_id=f'doc{index}',
                cik='0000000001',
                report_date='2026-01-15',
                document_type='EX-99.1',
                raw_path=path,
                sha256=f'hash{index}',
            )
        )
    return documents


def _run(config: Config, documents: list[Document], factory):
    """Drive run_extraction through its real signature."""
    return asyncio.run(
        run_extraction(
            config,
            documents,
            caller_factory=factory,
            models=[config.llm.models[0]],
            queue_path=resolve_data_path(config, config.extraction.review_queue_path),
        )
    )


class RateLimitedOnce:
    """Raise a 429 with a provider delay once, then answer."""

    def __init__(self, text: str = REPLY) -> None:
        """Store the reply returned after the first rate-limited attempt."""
        self.text = text
        self.calls = 0

    def complete(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> LLMResult:
        """Fail the first call with a rate limit, then succeed."""
        self.calls += 1
        if self.calls == 1:
            raise RateLimited('busy', retry_after_seconds=7.0)
        return LLMResult(text=self.text, model=model)


class CountingCaller:
    """Answer every call, counting how many reached the provider."""

    def __init__(self, text: str = REPLY) -> None:
        """Store the reply returned for every call."""
        self.text = text
        self.calls = 0

    def complete(
        self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
    ) -> LLMResult:
        """Return the canned reply and count the call."""
        self.calls += 1
        return LLMResult(text=self.text, model=model)


def test_runner_retries_429_with_retry_after(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 429 raised inside the batch is retried after the provider-stated delay.

    Exercised through run_extraction, not through the wrapper directly: the defect was
    that the wrapper was never wired in, so only the real entry point proves the fix.
    """
    sleeps: list[float] = []

    inner = RateLimitedOnce()
    documents = _documents(tmp_path)
    # RetryingCaller sleeps through its own injected `sleep`, which the runner builds
    # from config, so patch the default at the composition module.
    import nowcast.llm.composition as composition

    monkeypatch.setattr(composition.time, 'sleep', lambda seconds: sleeps.append(float(seconds)))
    outcomes = _run(config, documents, lambda _model: inner)

    assert [outcome.status for outcome in outcomes] == ['ok']
    assert inner.calls == 2
    assert sleeps == [7.0], 'the provider-stated delay must be honoured'


def test_cache_hit_avoids_second_call(config: Config, tmp_path: Path) -> None:
    """A repeated identical prompt is served from the cache, not the network."""
    inner = CountingCaller()
    documents = _documents(tmp_path)
    _run(config, documents, lambda _model: inner)
    assert inner.calls == 1
    # Remove the stored result so resume cannot answer before the caller is reached;
    # the second answer can then only come from the response cache.
    for path in (extractions_dir(config) / runner.model_slug(config.llm.models[0])).glob('*.json'):
        path.unlink()
    outcomes = _run(config, documents, lambda _model: inner)
    assert inner.calls == 1, 'the second run must be served from the cache'
    assert [outcome.status for outcome in outcomes] == ['ok']


def test_empty_reply_never_cached(config: Config, tmp_path: Path) -> None:
    """An empty completion must not be stored, or it would be replayed forever."""
    from nowcast.llm.composition import make_caller

    class EmptyCaller:
        def __init__(self) -> None:
            self.calls = 0

        def complete(
            self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
        ) -> LLMResult:
            """Return an empty completion every time."""
            self.calls += 1
            return LLMResult(text='', model=model)

    inner = EmptyCaller()
    caller = make_caller(config, inner=inner)
    for _ in range(2):
        caller.complete('fake/model:free', [{'role': 'user', 'content': 'hi'}])
    assert inner.calls == 2, 'an empty reply must not short-circuit the second call'
    assert list((tmp_path / 'cache').rglob('*.json')) == []


def test_unparseable_reply_never_cached(config: Config, tmp_path: Path) -> None:
    """Text that is not a JSON object is not cached, so a repair turn can retry it."""
    from nowcast.llm.composition import make_caller

    class GarbageCaller:
        def __init__(self) -> None:
            self.calls = 0

        def complete(
            self, model: str, messages: list[dict[str, str]], max_tokens: int | None = None
        ) -> LLMResult:
            """Return prose that no parser can read."""
            self.calls += 1
            return LLMResult(text='I cannot answer that.', model=model)

    inner = GarbageCaller()
    caller = make_caller(config, inner=inner)
    for _ in range(2):
        caller.complete('fake/model:free', [{'role': 'user', 'content': 'hi'}])
    assert inner.calls == 2
    assert list((tmp_path / 'cache').rglob('*.json')) == []


def test_cli_extract_uses_retrying_caller(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI must hand the runner a caller composed with retry and cache.

    Asserted on the real `_cmd_extract` path: the defect was that the CLI built a bare
    `LLMCaller`, so a test of the wrapper alone could never have caught it.
    """
    import pandas as pd

    from nowcast import cli
    from nowcast.config import data_root
    from nowcast.llm.composition import RetryingCaller

    seen: list[object] = []

    async def fake_run(_config, _documents, caller_factory, _models=None, **_kwargs):
        """Record the composed caller the CLI supplied, as an awaitable."""
        seen.append(caller_factory('fake/model:free'))
        return []

    root = data_root(config)
    root.mkdir(parents=True, exist_ok=True)
    source = tmp_path / 'exhibit.htm'
    source.write_text('<html><body>GAAP earnings per share were $0.55.</body></html>', 'utf-8')
    pd.DataFrame(
        [
            {
                'document_id': 'doc-1',
                'cik': '0000000001',
                'report_date': '2026-01-15',
                'document_type': 'EX-99.1',
                'source': 'edgar',
                'raw_path': str(source),
                'sha256': 'abc',
                'chars': 60,
                'downloaded_at': '2026-01-15T00:00:00+00:00',
                'items': '2.02',
            }
        ]
    ).to_parquet(root / config.data.document_index, index=False)

    monkeypatch.setattr(cli, '_load', lambda _args: config)
    monkeypatch.setattr(cli, 'start_manifest', lambda *_a, **_k: _NullManifest())
    monkeypatch.setattr('nowcast.extraction.runner.run_extraction', fake_run)
    args = cli.build_parser().parse_args(['extract'])
    assert cli._cmd_extract(args) == 0
    assert seen, 'the CLI never handed a caller to the runner'
    assert isinstance(seen[0], RetryingCaller)


class _NullManifest:
    """Minimal manifest stand-in for the CLI shim."""

    def __init__(self) -> None:
        """Create the mutable fields the CLI stamps before writing."""
        self.prompt_hashes: dict[str, str] = {}
        self.input_fingerprints: dict[str, str] = {}

    def write(self, _path: Path, _config: object) -> Path:
        """Pretend to write a manifest."""
        return Path('/dev/null')


def _config_path(config: Config) -> Path:
    """Return the repo config path the CLI parses."""
    return Path(__file__).resolve().parent.parent.parent / 'configs' / 'config.yaml'
