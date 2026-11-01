"""H-h: paths follow the config file, getters never mkdir, no module-level state."""

from __future__ import annotations

import os
from pathlib import Path

from nowcast.config import load_config
from nowcast.paths import Paths

REPO = Path(__file__).resolve().parent.parent.parent


def test_run_from_other_cwd(tmp_path: Path, monkeypatch: object) -> None:
    """A config loaded from elsewhere still resolves its prompts beside itself."""
    import shutil

    target = tmp_path / 'proj'
    shutil.copytree(REPO / 'prompts', target / 'prompts')
    config_path = target / 'configs' / 'config.yaml'
    config_path.parent.mkdir(parents=True)
    config_path.write_text((REPO / 'configs' / 'config.yaml').read_text(encoding='utf-8'))
    monkeypatch.delenv('DATA_DIR', raising=False)  # type: ignore[attr-defined]
    other = tmp_path / 'elsewhere'
    other.mkdir()
    monkeypatch.chdir(other)  # type: ignore[attr-defined]

    config = load_config(config_path)
    paths = Paths.from_config(config)
    assert paths.prompts == (target / 'prompts').resolve()
    assert paths.root == (target / 'data').resolve()


def test_getters_do_not_mkdir(tmp_path: Path, monkeypatch: object) -> None:
    """Asking for a path must not create a directory as a side effect."""
    data = tmp_path / 'data'
    monkeypatch.setenv('DATA_DIR', str(data))  # type: ignore[attr-defined]
    config = load_config(REPO / 'configs' / 'config.yaml')
    paths = Paths.from_config(config)
    paths.raw(config)
    paths.extractions(config)
    paths.manifests(config)
    assert not data.exists()
    assert os.path.isdir(REPO)  # the repo itself untouched


def test_no_module_level_mutable_state() -> None:
    """A module that accumulates state across runs makes two runs differ."""
    import inspect

    import nowcast.extraction.runner as runner

    module_values = {
        name: value
        for name, value in vars(runner).items()
        if not name.startswith('_')
        and not inspect.ismodule(value)
        and not inspect.isclass(value)
        and not callable(value)
    }
    mutable = {
        name: value for name, value in module_values.items() if isinstance(value, (list, dict, set))
    }
    assert mutable == {}, f'module-level mutable state: {sorted(mutable)}'
