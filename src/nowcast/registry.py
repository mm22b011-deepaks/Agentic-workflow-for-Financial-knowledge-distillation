"""Load the configured business and workflow registry without process-global state."""

from __future__ import annotations

from pathlib import Path

import yaml

from nowcast.config import Config
from nowcast.contracts import Registry


def load_registry(config: Config) -> Registry:
    path = Path(config.config_dir) / config.paths.project_dir / config.paths.registry_file
    registry = Registry.model_validate(yaml.safe_load(path.read_text()))
    for node in registry.nodes:
        for binding in node.parameters:
            section, name = binding.config_path.split('.')
            value = getattr(getattr(config, section), name)
            binding.value = list(value) if isinstance(value, tuple) else value
    return registry
