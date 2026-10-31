"""Content-addressed cache for LLM completions."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nowcast.config import CacheConfig

LOGGER = logging.getLogger(__name__)


def cache_key(prompt_text: str, model: str, params: dict[str, Any] | None = None) -> str:
    """Return the sha256 cache key for a prompt, model id and sampling parameters."""
    digest = hashlib.sha256()
    digest.update(prompt_text.encode('utf-8'))
    digest.update(b'\x00')
    digest.update(model.encode('utf-8'))
    if params:
        digest.update(b'\x00')
        digest.update(json.dumps(params, sort_keys=True).encode('utf-8'))
    return digest.hexdigest()


class ResponseCache:
    """Filesystem cache storing one JSON record per prompt/model pair."""

    def __init__(self, config: CacheConfig, root: Path | str) -> None:
        """Point the cache at a directory and copy the enabled flag."""
        self._enabled = bool(config.enabled)
        self._root = Path(root)
        self._ttl = timedelta(days=int(config.ttl_days))

    @property
    def enabled(self) -> bool:
        """Return whether cache reads and writes are active."""
        return self._enabled

    def _path_for(self, key: str) -> Path:
        """Return the sharded cache file path for a key."""
        return self._root / key[:2] / f'{key}.json'

    def _expired(self, payload: dict[str, Any], path: Path) -> bool:
        """Return True when the cached record is older than the configured TTL."""
        if self._ttl.total_seconds() <= 0:
            return False
        stamp = payload.get('created_at')
        try:
            created = datetime.fromisoformat(str(stamp))
        except (TypeError, ValueError):
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - created > self._ttl

    def get(self, key: str) -> str | None:
        """Return the cached response text, or None on a miss or when disabled."""
        if not self._enabled:
            return None
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning('cache entry unreadable path=%s', path)
            return None
        if self._expired(payload, path):
            LOGGER.info('cache entry expired key=%s', key)
            return None
        text = payload.get('text')
        return str(text) if text is not None else None

    def set(self, key: str, text: str, model: str) -> None:
        """Store a response text under the cache key."""
        if not self._enabled:
            return
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'model': model,
            'text': text,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
