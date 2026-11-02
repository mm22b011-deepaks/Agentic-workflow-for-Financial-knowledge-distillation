"""Typer discovers commands from the canonical argparse CLI instead of duplicating flags."""

from __future__ import annotations

import argparse
from collections.abc import Callable

import typer

from nowcast.cli import build_parser, main

app = typer.Typer(
    help='Tresata: index-level earnings proxies and workstation controls.', no_args_is_help=True
)


def register(application: typer.Typer, parser: argparse.ArgumentParser, prefix: list[str]) -> None:
    groups = [
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ]
    if not groups:
        return
    descriptions = {action.dest: action.help for action in groups[0]._choices_actions}
    for name, child in groups[0].choices.items():
        path = [*prefix, name]
        if any(isinstance(action, argparse._SubParsersAction) for action in child._actions):
            group = typer.Typer(no_args_is_help=True)
            register(group, child, path)
            application.add_typer(group, name=name, help=descriptions.get(name, ''))
        else:
            # Keep the closure's path out of Typer's parameter schema.
            def make_callback(command: list[str]) -> Callable[[typer.Context], None]:
                def invoke(context: typer.Context) -> None:
                    raise typer.Exit(main([*command, *context.args]))

                return invoke

            application.command(
                name=name,
                help=descriptions.get(name, ''),
                context_settings={
                    'allow_extra_args': True,
                    'ignore_unknown_options': True,
                    'help_option_names': [],
                },
            )(make_callback(path))


register(app, build_parser(), [])

if __name__ == '__main__':
    app()
