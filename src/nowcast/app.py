"""Typer command interface; compatibility handlers retain established command behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    help='Tresata: index-level earnings proxies and workstation controls.', no_args_is_help=True
)
ConfigOption = Annotated[Path, typer.Option('--config', help='Configuration YAML')]
SetOption = Annotated[list[str] | None, typer.Option('--set', help='Dotted configuration override')]
DEFAULT = Path('configs/config.yaml')


def invoke(name: str, config: Path, settings: list[str], extra: list[str] | None = None) -> None:
    from nowcast.cli import main

    args = [name, '--config', str(config)]
    for value in settings:
        args.extend(['--set', value])
    raise typer.Exit(main(args + (extra or [])))


def register(name: str) -> None:
    def command(config: ConfigOption = DEFAULT, settings: SetOption = None) -> None:
        if settings is None:
            settings = []
        invoke(name, config, settings)

    app.command(name=name, help=f'Run the {name} pipeline stage.')(command)


for stage in ('build-constituents', 'estimate-scope', 'ingest', 'aggregate', 'run-all'):
    register(stage)


@app.command('validate-config')
def validate(
    config: ConfigOption = DEFAULT, settings: SetOption = None, strict: bool = False
) -> None:
    """Validate configuration; strict also checks environment credentials."""
    if settings is None:
        settings = []
    invoke('validate-config', config, settings, ['--strict'] if strict else [])


@app.command('extract')
def extract(
    config: ConfigOption = DEFAULT,
    settings: SetOption = None,
    limit: int = 0,
    sample: int = 0,
    seed: int | None = None,
) -> None:
    """Extract releases; limits and sampling are explicit verification controls."""
    if settings is None:
        settings = []
    extra = ['--limit', str(limit), '--sample', str(sample)]
    if seed is not None:
        extra += ['--seed', str(seed)]
    invoke('extract', config, settings, extra)


@app.command('rebuild-index')
def rebuild(
    config: ConfigOption = DEFAULT,
    settings: SetOption = None,
    source: Path | None = None,
    force: bool = False,
) -> None:
    """Rebuild a candidate into the configured target, preserving its backup."""
    if settings is None:
        settings = []
    extra = ['--source', str(source)] if source else []
    if force:
        extra.append('--force')
    invoke('rebuild-index', config, settings, extra)


@app.command('model-bakeoff')
def bakeoff(
    config: ConfigOption = DEFAULT,
    settings: SetOption = None,
    sample: int = 10,
    model: list[str] | None = None,
    labels: Path | None = None,
) -> None:
    """Run isolated, ledger-backed model comparison on the same sample."""
    if model is None:
        model = []
    if settings is None:
        settings = []
    extra = ['--sample', str(sample)]
    for name in model:
        extra += ['--model', name]
    if labels:
        extra += ['--labels', str(labels)]
    invoke('model-bakeoff', config, settings, extra)


@app.command('validate-index')
def validate_index(config: ConfigOption = DEFAULT, source: Path | None = None) -> None:
    """Check an index and raw hashes in place; never replace any artifacts."""
    from nowcast.config import load_config
    from nowcast.ingestion.doc_index import load_index
    from nowcast.ingestion.rebuild import index_path, validate_index_contents, validate_index_rows

    loaded = load_config(config)
    target = source or index_path(loaded)
    if not target.is_file():
        typer.echo('index file not found', err=True)
        raise typer.Exit(2)
    frame = load_index(target)
    problems = validate_index_rows(frame, loaded) + validate_index_contents(frame, loaded)
    typer.echo(f'{len(frame)} rows checked; {len(problems)} failures')
    raise typer.Exit(int(bool(problems)))


@app.command('supersede-stale')
def supersede(config: ConfigOption = DEFAULT) -> None:
    """Explicitly archive results with a verifiably stale settings fingerprint."""
    from nowcast.config import load_config
    from nowcast.extraction.runner import supersede_stale

    loaded = load_config(config)
    typer.echo(f'{len(supersede_stale(loaded, list(loaded.llm.models)))} results archived')


@app.command('demo')
def demo(config: ConfigOption = DEFAULT) -> None:
    """Run the deterministic 500-release offline verification."""
    from nowcast.config import load_config
    from nowcast.paths import Paths
    from nowcast.verification import synthetic_demo

    loaded = load_config(config)
    result = synthetic_demo(loaded, Paths.from_config(loaded).resolve('demo'))
    typer.echo(f'{result["documents"]} releases; pandas agreement: {result["pandas_agreement"]}')


@app.command('freeze-panel')
def panel(config: ConfigOption = DEFAULT) -> None:
    """Freeze the private seeded 150-company verification panel, offline."""
    from nowcast.config import load_config
    from nowcast.verification import freeze_panel

    typer.echo(str(freeze_panel(load_config(config))))


@app.command('serve')
def serve(config: ConfigOption = DEFAULT, port: int = 8767) -> None:
    """Serve the workstation website and API on all IPv4 interfaces."""
    import uvicorn

    from nowcast.api import create_app

    uvicorn.run(create_app(config), host='0.0.0.0', port=port, access_log=False)


if __name__ == '__main__':
    app()
