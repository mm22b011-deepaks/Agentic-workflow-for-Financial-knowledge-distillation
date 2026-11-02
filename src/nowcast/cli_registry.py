"""CLI metadata and validated argv come from the same argparse definitions."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def catalogue() -> list[dict[str, Any]]:
    from nowcast.cli import build_parser

    result = []

    def visit(parser: argparse.ArgumentParser, prefix: list[str]) -> None:
        groups = [
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        ]
        if groups:
            for name, child in groups[0].choices.items():
                visit(child, [*prefix, name])
            return
        controls = []
        for action in parser._actions:
            if not action.option_strings:
                continue
            kind = (
                'help'
                if isinstance(action, argparse._HelpAction)
                else 'boolean'
                if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction))
                else 'integer'
                if action.type is int
                else 'number'
                if action.type is float
                else 'string'
            )
            default = action.default
            if isinstance(default, Path):
                default = str(default)
            controls.append(
                {
                    'name': action.dest,
                    'flags': action.option_strings,
                    'kind': kind,
                    'default': default,
                    'choices': list(action.choices) if action.choices is not None else None,
                    'multiple': isinstance(action, argparse._AppendAction),
                    'help': action.help or '',
                }
            )
        result.append(
            {
                'id': '-'.join(prefix),
                'command': prefix,
                'controls': controls,
                'help': parser.description or ' '.join(prefix),
            }
        )

    visit(build_parser(), [])
    return result


def command_argv(command_id: str, parameters: dict[str, Any], config_path: Path) -> list[str]:
    definition = next((item for item in catalogue() if item['id'] == command_id), None)
    if definition is None:
        raise ValueError('unknown CLI command')
    controls = {item['name']: item for item in definition['controls']}
    if set(parameters) - set(controls):
        raise ValueError('unknown CLI parameter')
    result = [*definition['command'], '--config', str(config_path)]
    for name, value in parameters.items():
        item = controls[name]
        if name == 'config':
            if Path(str(value)).resolve() != config_path.resolve():
                raise ValueError('configuration is server-owned')
            continue
        if item['kind'] == 'help':
            continue
        flag = next((flag for flag in item['flags'] if flag.startswith('--')), item['flags'][0])
        if item['kind'] == 'boolean':
            if not isinstance(value, bool):
                raise ValueError('boolean parameter required')
            if value:
                result.append(flag)
        elif item['multiple']:
            if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
                raise ValueError('list parameter required')
            for part in value:
                if name == 'set':
                    setting = part.partition('=')[0]
                    if (
                        setting.startswith('paths.')
                        or setting.endswith('_env')
                        or '_url' in setting
                        or setting
                        in {
                            'data.constituents_csv',
                            'data.document_index',
                            'data.local_manifest_csv',
                            'data.labels_csv',
                            'data.weights_csv',
                            'budget.ledger_path',
                            'extraction.review_queue_path',
                            'reporting.report_path',
                        }
                    ):
                        raise ValueError('filesystem and credential settings are server-owned')
                result.extend([flag, part])
        else:
            if item['kind'] == 'integer' and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise ValueError('integer parameter required')
            if isinstance(value, (dict, list)):
                raise ValueError('scalar parameter required')
            if item['choices'] is not None and value not in item['choices']:
                raise ValueError('unknown parameter choice')
            if name in {'source', 'labels'}:
                from nowcast.config import load_config
                from nowcast.paths import Paths

                root = Paths.from_config(load_config(config_path)).root
                path = Path(str(value))
                path = path.resolve() if path.is_absolute() else (root / path).resolve()
                if not path.is_relative_to(root) or path.suffix != (
                    '.csv' if name == 'labels' else '.parquet'
                ):
                    raise ValueError('artifact path is outside its permitted data root')
                value = str(path)
            result.extend([flag, str(value)])
    return result
