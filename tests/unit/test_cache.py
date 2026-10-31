"""Unit tests for the LLM response cache."""

from __future__ import annotations

import json
from pathlib import Path

from nowcast.config import CacheConfig
from nowcast.llm.cache import ResponseCache, cache_key


def _cache(tmp_path: Path, enabled: bool = True, ttl_days: int = 30) -> ResponseCache:
    """Build a cache rooted at a temp directory."""
    return ResponseCache(CacheConfig(enabled=enabled, ttl_days=ttl_days), tmp_path)


def test_cache_roundtrip(tmp_path: Path) -> None:
    """A stored response is returned unchanged for the same key."""
    cache = _cache(tmp_path)
    key = cache_key('render this', 'model-a:free')
    assert cache.get(key) is None
    cache.set(key, 'canned response', 'model-a:free')
    assert cache.get(key) == 'canned response'


def test_cache_key_changes_with_prompt_hash(tmp_path: Path) -> None:
    """Different prompt text or model id yields a different cache key."""
    first = cache_key('prompt one', 'model-a:free')
    second = cache_key('prompt two', 'model-a:free')
    third = cache_key('prompt one', 'model-b:free')
    assert first != second
    assert first != third
    cache = _cache(tmp_path)
    cache.set(first, 'value', 'model-a:free')
    assert cache.get(second) is None


def test_cache_disabled(tmp_path: Path) -> None:
    """A disabled cache neither writes nor reads entries."""
    cache = _cache(tmp_path, enabled=False)
    key = cache_key('anything', 'model-a:free')
    cache.set(key, 'ignored', 'model-a:free')
    assert cache.get(key) is None
    assert not list(tmp_path.rglob('*.json'))


def test_cache_ignores_corrupt_entry(tmp_path: Path) -> None:
    """A corrupt cache file is treated as a miss instead of raising."""
    cache = _cache(tmp_path)
    key = cache_key('x', 'model-a:free')
    path = tmp_path / key[:2] / f'{key}.json'
    path.parent.mkdir(parents=True)
    path.write_text('{not json', encoding='utf-8')
    assert cache.get(key) is None


def test_cache_records_model_metadata(tmp_path: Path) -> None:
    """The stored payload carries the model id used to produce the text."""
    cache = _cache(tmp_path)
    key = cache_key('y', 'model-a:free')
    cache.set(key, 'text', 'model-a:free')
    payload = json.loads((tmp_path / key[:2] / f'{key}.json').read_text(encoding='utf-8'))
    assert payload['model'] == 'model-a:free'
    assert payload['text'] == 'text'
