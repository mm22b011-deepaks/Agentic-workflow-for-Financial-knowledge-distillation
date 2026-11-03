"""Generate schemas, registry and offline fixtures from Python contracts."""

from __future__ import annotations

import json

from _bootstrap import ROOT

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
    lines = ['# Node inputs and outputs', '']
    for node in canvas_registry().nodes:
        lines.extend(
            [
                f'## {node.id}',
                '',
                f'Input: {node.io.takes.noun} ({node.io.takes.unit_label}). {node.io.takes.plain_line}.',
                f'Output: {node.io.gives.noun} ({node.io.gives.unit_label}). {node.io.gives.plain_line}.',
                '',
            ]
        )
        lines.extend(
            f'- {field.label}: {field.description}' + (f' ({field.unit})' if field.unit else '')
            for field in node.io.example_fields
        )
        lines.append('')
    (ROOT / 'web/public/io.md').write_text('\n'.join(lines))
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


if __name__ == '__main__':
    main()
