"""Generate schemas, help, registry fixtures and CLI reference from Python contracts."""

from __future__ import annotations

import json

from _bootstrap import ROOT
from typer.testing import CliRunner

from nowcast.app import app
from nowcast.contracts import (
    IndexSnapshot,
    Registry,
    RunEvent,
    RunRequest,
    RunStatus,
    ScheduleSnapshot,
)


def main() -> None:
    for model in (Registry, RunRequest, RunStatus, RunEvent, IndexSnapshot, ScheduleSnapshot):
        path = ROOT / 'schemas' / (model.__name__ + '.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + '\n')
    from nowcast import contracts
    from nowcast.workflow_registry import canvas_registry

    (ROOT / 'web/src/registry.json').write_text(canvas_registry().model_dump_json(indent=2) + '\n')
    for name in (
        'CanvasRegistry',
        'GraphDocument',
        'StageSnapshot',
        'PaneResponse',
        'MetricSnapshot',
        'EvidenceResponse',
        'LabelRequest',
        'LabelResponse',
        'KPIKnowledgeBase',
        'SessionResponse',
        'SettingsResponse',
    ):
        model = getattr(contracts, name)
        (ROOT / 'schemas' / (name + '.json')).write_text(
            json.dumps(model.model_json_schema(), indent=2) + '\n'
        )
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
    help_text = (ROOT / 'docs/help.md').read_text()
    (ROOT / 'web/src/help.md').write_text(help_text)
    runner = CliRunner()
    cli = (
        '# CLI reference\n\nGenerated from Typer.\n\n```text\n'
        + runner.invoke(app, ['--help'], color=False).stdout
        + '\n```\n'
    )
    from nowcast.cli_registry import catalogue

    for command in catalogue():
        cli += (
            '\n## '
            + (' '.join(command['command']) or 'nowcast')
            + '\n\n| Flag | Default | Meaning |\n|---|---|---|\n'
        )
        for control in command['controls']:
            cli += (
                '| '
                + ', '.join(control['flags'])
                + ' | '
                + str(control['default']).replace('|', '\\|')
                + ' | '
                + control['help'].replace('|', '\\|')
                + ' |\n'
            )
    (ROOT / 'docs/cli.md').write_text(cli)


if __name__ == '__main__':
    main()
