"""Tests for the runtime path layout."""

from __future__ import annotations

from pathlib import Path

from nowcast.config import Config, load_config
from nowcast.paths import (
    Paths,
    aggregates_dir,
    cache_dir,
    data_root,
    extractions_dir,
    manifests_dir,
    prompts_dir,
    raw_dir,
    reports_dir,
    resolve_data_path,
    sub_dir,
)

REPO = Path(__file__).resolve().parent.parent.parent


def _config(**overrides: object) -> Config:
    """Load the project config; DATA_DIR is whatever the test set in its environment."""
    return load_config(REPO / 'configs' / 'config.yaml', overrides=overrides or None)


def test_paths_all_inside_data_dir(monkeypatch, tmp_path: Path) -> None:
    """Every directory helper lands inside the configured data root."""
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'root'))
    config = _config()
    root = data_root(config)
    assert root == (tmp_path / 'root').resolve()
    for path in (
        raw_dir(config),
        cache_dir(config),
        extractions_dir(config),
        aggregates_dir(config),
        reports_dir(config),
        manifests_dir(config),
    ):
        # A getter returns a path; creating a directory is the writer's job (H-h).
        assert path == root / path.name or root in path.parents
        # cache_dir is nested (.cache/llm), so check containment rather than the parent.
        assert root in path.parents

    # The prompts folder is source, not output, so it lives outside the data root.
    assert prompts_dir(config).is_dir()
    assert prompts_dir(config).name == 'prompts'


def test_paths_ignore_relative_project_location(monkeypatch, tmp_path: Path) -> None:
    """Without DATA_DIR the root is project_dir/data_date, resolved absolutely."""
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    config = _config()
    assert Paths.from_config(config).root.is_absolute()
    assert sub_dir(config, 'custom') == (tmp_path / 'data' / 'custom').resolve()


def test_resolve_data_path_respects_absolute(monkeypatch, tmp_path: Path) -> None:
    """A relative input resolves under the data root; an absolute one is untouched."""
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
    config = _config()
    assert resolve_data_path(config, 'inputs/x.csv') == (tmp_path / 'data' / 'inputs' / 'x.csv')
    absolute = tmp_path / 'elsewhere' / 'x.csv'
    assert resolve_data_path(config, str(absolute)) == absolute
