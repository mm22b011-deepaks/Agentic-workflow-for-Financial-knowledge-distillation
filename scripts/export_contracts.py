"""Generate schemas, help, registry fixtures and CLI reference from Python contracts."""

from __future__ import annotations

import json

from _bootstrap import ROOT
from typer.testing import CliRunner

from nowcast.app import app
from nowcast.config import load_config
from nowcast.contracts import (
    IndexSnapshot,
    Registry,
    RunEvent,
    RunRequest,
    RunStatus,
    ScheduleSnapshot,
)
from nowcast.registry import load_registry


def main() -> None:
    config = load_config(ROOT / 'configs/config.yaml')
    registry = load_registry(config)
    for model in (Registry, RunRequest, RunStatus, RunEvent, IndexSnapshot, ScheduleSnapshot):
        path = ROOT / 'schemas' / (model.__name__ + '.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + '\n')
    (ROOT / 'web/src/registry.json').write_text(registry.model_dump_json(indent=2) + '\n')
    fixture = IndexSnapshot(
        source='synthetic',
        snapshots=[
            {
                'season_year': 2025,
                'season_quarter': 1,
                'n_reported': 125,
                'n_expected': 125,
                'suppressed': False,
            }
        ],
    )
    (ROOT / 'web/src/index-fixture.json').write_text(fixture.model_dump_json(indent=2) + '\n')
    help_text = (
        '# Pipeline help\n\nAll metrics are index-level proxies. Replay never starts a job.\n\n'
    )
    for node in registry.nodes:
        help_text += f'## {node.label}\n\n{node.help}\n\nCapability: {node.capability}.\n\n'
    for kpi in registry.kpis:
        help_text += f'## {kpi.label}\n\n{kpi.definition}\n\n'
    (ROOT / 'docs/help.md').write_text(help_text)
    (ROOT / 'web/src/help.md').write_text(help_text)
    runner = CliRunner()
    cli = (
        '# CLI reference\n\nGenerated from Typer.\n\n```text\n'
        + runner.invoke(app, ['--help'], color=False).stdout
        + '\n```\n'
    )
    (ROOT / 'docs/cli.md').write_text(cli)


if __name__ == '__main__':
    main()
