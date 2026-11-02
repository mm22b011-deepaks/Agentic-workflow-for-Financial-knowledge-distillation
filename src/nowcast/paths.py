"""Directory layout: every runtime path is a subfolder of the configured data root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing-only import, avoids a config <-> paths cycle
    from nowcast.config import Config


@dataclass(frozen=True)
class Paths:
    """Resolved runtime directories, all derived from one data root.

    The root comes from the environment variable named in the config so that a
    Colab secret or a shell export wins over the YAML; nothing here is absolute
    in the source tree.
    """

    root: Path
    prompts: Path

    @classmethod
    def from_config(cls, config: Config) -> Paths:
        """Build the path set for a loaded config, honouring the data-dir env var."""
        override = os.environ.get(config.runtime.data_dir_env)
        base = Path(config.config_dir) / config.paths.project_dir
        root = Path(override) if override else base / config.paths.data_dir
        prompts = base / config.paths.prompts_dir
        return cls(root=root.resolve(), prompts=prompts.resolve())

    def sub(self, name: str) -> Path:
        """Return a subfolder of the data root. Creating it is the writer's job."""
        return self.root / name

    def raw(self, config: Config) -> Path:
        """Return the raw document directory."""
        return self.sub(config.paths.raw_dir)

    def cache(self, config: Config) -> Path:
        """Return the LLM response cache directory."""
        return self.sub(config.paths.cache_dir)

    def extractions(self, config: Config) -> Path:
        """Return the extraction output directory."""
        return self.sub(config.paths.extractions_dir)

    def aggregates(self, config: Config) -> Path:
        """Return the aggregate output directory."""
        return self.sub(config.paths.aggregates_dir)

    def reports(self, config: Config) -> Path:
        """Return the report output directory."""
        return self.sub(config.paths.reports_dir)

    def manifests(self, config: Config) -> Path:
        """Return the run-manifest directory."""
        return self.sub(config.paths.manifests_dir)

    def resolve(self, relative: str) -> Path:
        """Resolve a configured input path against the data root."""
        candidate = Path(relative)
        if candidate.is_absolute():
            return candidate
        return self.root / candidate


def data_root(config: Config) -> Path:
    """Return the absolute data directory, honouring the configured env var."""
    return Paths.from_config(config).root


def prompts_dir(config: Config) -> Path:
    """Return the prompts directory."""
    return Paths.from_config(config).prompts


def sub_dir(config: Config, name: str) -> Path:
    """Return an absolute subdirectory of the data root and create it."""
    return Paths.from_config(config).sub(name)


def raw_dir(config: Config) -> Path:
    """Return the raw document directory."""
    return Paths.from_config(config).raw(config)


def cache_dir(config: Config) -> Path:
    """Return the LLM response cache directory."""
    return Paths.from_config(config).cache(config)


def extractions_dir(config: Config) -> Path:
    """Return the extraction output directory."""
    return Paths.from_config(config).extractions(config)


def aggregates_dir(config: Config) -> Path:
    """Return the aggregate output directory."""
    return Paths.from_config(config).aggregates(config)


def reports_dir(config: Config) -> Path:
    """Return the report output directory."""
    return Paths.from_config(config).reports(config)


def manifests_dir(config: Config) -> Path:
    """Return the run-manifest directory."""
    return Paths.from_config(config).manifests(config)


def resolve_data_path(config: Config, relative: str) -> Path:
    """Resolve a configured input path against the data root."""
    return Paths.from_config(config).resolve(relative)
