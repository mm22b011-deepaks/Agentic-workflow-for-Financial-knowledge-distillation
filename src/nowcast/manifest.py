"""Run manifests: a JSON record of what produced an output, never including secrets."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nowcast.config import Config
from nowcast.errors import ConfigError

# The dependency set the manifest records versions for. A package that is not
# installed is recorded as absent rather than silently omitted, so a manifest
# can never overstate what was available.
TRACKED_PACKAGES = (
    'pandas',
    'pyarrow',
    'httpx',
    'beautifulsoup4',
    'lxml',
    'rapidfuzz',
    'tenacity',
    'jinja2',
    'pyyaml',
    'pydantic',
    'langchain-core',
    'scikit-learn',
    'statsmodels',
    'matplotlib',
    'duckdb',
    'diskcache',
    'nbformat',
    'python-dotenv',
)


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def git_sha(root: Path | str | None = None) -> str | None:
    """Return the current commit sha, or None when git is unavailable."""
    try:
        result = subprocess.run(
            ['git', '-C', str(root or Path.cwd()), 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def package_versions(packages: tuple[str, ...] = TRACKED_PACKAGES) -> dict[str, str | None]:
    """Return installed versions for the tracked packages, None when absent."""
    versions: dict[str, str | None] = {}
    for name in packages:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def config_hash(config: Config) -> str:
    """Return a deterministic hash of every config value.

    Only the config object is hashed, never the environment: an API key change
    must not alter what a run is recorded as having produced.
    """
    payload = dataclasses.asdict(config)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
    ).hexdigest()


def secret_names(config: Config) -> tuple[str, ...]:
    """Return the environment variable names whose values are secrets."""
    names = [config.llm.api_key_env, config.data.sec_user_agent_env]
    return tuple(name for name in dict.fromkeys(names) if name)


def _scrub(value: str, secrets: tuple[str, ...]) -> str:
    """Replace any secret value appearing in a string with a placeholder."""
    scrubbed = value
    for name in secrets:
        secret = os.environ.get(name)
        if secret and secret in scrubbed:
            scrubbed = scrubbed.replace(secret, f'<redacted:{name}>')
    return scrubbed


@dataclass
class Manifest:
    """The manifest body, in field order suitable for a human reading the JSON."""

    config_hash: str
    git_sha: str | None
    python_version: str
    package_versions: dict[str, str | None]
    seed: int
    started_at: str
    ended_at: str | None = None
    prompt_hashes: dict[str, str] = field(default_factory=dict)
    input_fingerprints: dict[str, str] = field(default_factory=dict)
    stage: str = ''
    notes: str = ''
    # How a run chose what it read: recorded so a capped or sampled run can be
    # reproduced, not only re-run.
    sample: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the manifest as an ordered, JSON-safe dict."""
        return {
            'config_hash': self.config_hash,
            'git_sha': self.git_sha,
            'python_version': self.python_version,
            'package_versions': dict(sorted(self.package_versions.items())),
            'seed': self.seed,
            'stage': self.stage,
            'started_at': self.started_at,
            'ended_at': self.ended_at,
            'prompt_hashes': dict(sorted(self.prompt_hashes.items())),
            'input_fingerprints': dict(sorted(self.input_fingerprints.items())),
            'notes': self.notes,
            'sample': self.sample,
        }

    def to_json(self, config: Config | None = None) -> str:
        """Serialise the manifest, scrubbing any secret value that slipped in."""
        secrets = secret_names(config) if config is not None else ()
        return _scrub(json.dumps(self.to_dict(), indent=2, sort_keys=False), secrets)

    def write(self, path: Path | str, config: Config | None = None) -> Path:
        """Write the manifest JSON to disk, creating parent folders."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(config) + '\n', encoding='utf-8')
        return target


def prompt_hashes(root: Path | str, name: str, version: str) -> dict[str, str]:
    """Return the sha256 of each prompt file for one prompt version."""
    from nowcast.llm.prompts import load_prompt

    bundle = load_prompt(name, version, root)
    hashes = {'bundle': bundle.prompt_hash}
    for label, text in (
        ('system', bundle.system_template),
        ('user', bundle.user_template),
    ):
        hashes[label] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return hashes


def file_fingerprint(path: Path | str) -> str:
    """Return the sha256 of a file's bytes, raising ConfigError when it is missing."""
    target = Path(path)
    if not target.is_file():
        raise ConfigError(f'cannot fingerprint a missing file: {target}')
    return hashlib.sha256(target.read_bytes()).hexdigest()


def start_manifest(config: Config, stage: str = '') -> Manifest:
    """Create a manifest stamped with the config, environment and start time."""
    return Manifest(
        config_hash=config_hash(config),
        git_sha=git_sha(),
        python_version=platform.python_version(),
        package_versions=package_versions(),
        seed=int(config.runtime.seed),
        started_at=utc_now(),
        stage=stage,
    )


def finish_manifest(manifest: Manifest) -> Manifest:
    """Stamp the manifest's end time and return it."""
    manifest.ended_at = utc_now()
    return manifest
