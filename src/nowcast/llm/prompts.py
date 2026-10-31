"""Prompt template loading and rendering."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

from nowcast.errors import ConfigError

SYSTEM_TEMPLATE = 'system.md.j2'
USER_TEMPLATE = 'user.md.j2'
FEW_SHOT_FILE = 'few_shot.yaml'


@dataclass(frozen=True)
class PromptBundle:
    """A loaded prompt version: system text, user template and few-shot pairs."""

    name: str
    version: str
    system_template: str
    user_template: str
    few_shots: tuple[dict[str, Any], ...]
    text: str

    @property
    def prompt_hash(self) -> str:
        """Return the sha256 hash of everything sent to the model as prompt text."""
        return hashlib.sha256(_prompt_material(self)).hexdigest()


def _prompt_material(bundle: PromptBundle) -> bytes:
    """Return the template text and the few-shot pairs, which reach the model together.

    The pairs are messages in their own right, so editing an example changes what the
    model is asked exactly as editing a template does. Leaving them out of the hash
    would resume records extracted under a different prompt.
    """
    material = bundle.text
    if bundle.few_shots:
        material += '\x00' + json.dumps(bundle.few_shots, sort_keys=True, default=str)
    return material.encode('utf-8')


def _read(path: Path) -> str:
    """Read a UTF-8 text file, raising ConfigError when absent."""
    if not path.is_file():
        raise ConfigError(f'prompt file not found: {path}')
    return path.read_text(encoding='utf-8')


def load_prompt(name: str, version: str, root: Path | str) -> PromptBundle:
    """Load a prompt version from <root>/<name>/<version>/."""
    base = Path(root) / name / version
    if not base.is_dir():
        raise ConfigError(f'prompt directory not found: {base}')
    system_template = _read(base / SYSTEM_TEMPLATE)
    user_template = _read(base / USER_TEMPLATE)
    few_shot_path = base / FEW_SHOT_FILE
    few_shots: tuple[dict[str, Any], ...] = ()
    if few_shot_path.is_file():
        loaded = yaml.safe_load(few_shot_path.read_text(encoding='utf-8')) or []
        if not isinstance(loaded, list):
            raise ConfigError(f'{few_shot_path} must contain a list of {{input, output}} pairs')
        for item in loaded:
            if not isinstance(item, dict) or 'input' not in item or 'output' not in item:
                raise ConfigError(f'{few_shot_path} entries must have input and output keys')
        few_shots = tuple(dict(item) for item in loaded)
    text = system_template + '\n' + user_template
    return PromptBundle(
        name=name,
        version=version,
        system_template=system_template,
        user_template=user_template,
        few_shots=few_shots,
        text=text,
    )


def render_template(template_text: str, variables: dict[str, Any]) -> str:
    """Render a Jinja2 template string with StrictUndefined so missing variables raise."""
    env = Environment(undefined=StrictUndefined, autoescape=False)
    try:
        return env.from_string(template_text).render(**variables)
    except Exception as exc:  # jinja2 raises UndefinedError for missing names
        raise ConfigError(f'prompt render failed: {exc}') from exc


def render_prompt(bundle: PromptBundle, variables: dict[str, Any]) -> str:
    """Render the user template with StrictUndefined so missing variables raise."""
    try:
        return render_template(bundle.user_template, variables)
    except ConfigError as exc:
        raise ConfigError(
            f'prompt render failed for {bundle.name}/{bundle.version}: {exc}'
        ) from exc


def prompt_hash(bundle: PromptBundle, variables: dict[str, Any] | None = None) -> str:
    """Return the sha256 hash of the prompt text, few-shots and rendered variables."""
    digest = hashlib.sha256()
    digest.update(_prompt_material(bundle))
    if variables:
        digest.update(b'\x00')
        digest.update(repr(sorted(variables.items())).encode('utf-8'))
    return digest.hexdigest()
