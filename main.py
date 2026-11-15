#!/usr/bin/env python3
"""
Waybill-Declaration Parsing application using Pydantic
Parsing practice for an ETL: customs declarations (GTD), their updates,
clearance statements, and waybills.

    python main.py [--env local] run                 # process input files (default command)
    python main.py --env local seed [--rows 50] ...  # generate mock input files / database records
    python main.py --env local reset                 # wipe the local sandbox
    python main.py [--env local] serve               # web dashboard (http://localhost:8000/ locally)

``--env`` selects the settings profile (same as the ``CORD_ENV`` variable), see
``application/configuration_handling.py``. Settings are read at import time, so
application modules are imported inside the commands, after ``--env`` is applied.
"""

import os
import shutil

import click

KIND_NAMES = ("declaration", "declarationupdates", "clearancestatement", "waybill")


def local_only(command: str) -> None:
    from application.configuration_handling import ENVIRONMENT

    if ENVIRONMENT == "production":
        raise click.UsageError(
            f"'{command}' only works with a local profile, e.g.: python main.py --env local {command}"
        )


@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--env", help="Settings profile, e.g. 'local' (default: $CORD_ENV or production)."
)
@click.pass_context
def cli(ctx: click.Context, env: str | None) -> None:
    """Waybill / declaration parsing ETL."""
    if env:
        os.environ["CORD_ENV"] = env
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
def run() -> None:
    """Validate input files, store them and export department reports."""
    from application.configuration_handling import ENVIRONMENT
    from application.pipeline import run as run_pipeline

    click.echo(f"[{ENVIRONMENT}]")
    click.echo(run_pipeline().summary())


@cli.command()
@click.option(
    "--rows",
    type=click.IntRange(min=1),
    default=50,
    show_default=True,
    help="Rows per document type.",
)
@click.option(
    "--kinds",
    multiple=True,
    metavar="KIND",
    help=f"Document type, repeatable or comma separated: {', '.join(KIND_NAMES)} (default: all).",
)
@click.option(
    "--invalid-ratio",
    type=click.FloatRange(0, 1),
    default=0.1,
    show_default=True,
    help="Share of deliberately invalid csv rows.",
)
@click.option(
    "--target",
    type=click.Choice(["csv", "db", "both"]),
    default="csv",
    show_default=True,
    help="csv: input files to be processed by 'run'; db: insert records directly.",
)
@click.option(
    "--seed", "random_seed", type=int, help="Random seed for reproducible data."
)
def seed(
    rows: int,
    kinds: tuple[str, ...],
    invalid_ratio: float,
    target: str,
    random_seed: int | None,
) -> None:
    """Generate schema based mock data (local profiles only)."""
    local_only("seed")
    from application.configuration_handling import resolve_path, settings
    from application.mock_data import MockDataGenerator, kinds_from_names
    from application.storage import build_repository

    names = [name for value in kinds for name in value.replace(",", " ").split()]
    try:
        selected = kinds_from_names(names or None)
    except ValueError as error:
        raise click.BadParameter(str(error), param_hint="--kinds") from error

    generator = MockDataGenerator(seed=random_seed)
    if target in ("csv", "both"):
        input_dir = resolve_path(settings.input_files_path)
        for kind in selected:
            path = generator.write_csv(
                input_dir,
                kind,
                rows,
                invalid_ratio,
                settings.get("csv_delimiters", "^")[0],
            )
            click.echo(f"{kind.key:<20} {rows} rows -> {path}")
    if target in ("db", "both"):
        repository = build_repository(settings)
        try:
            for kind in selected:
                count = generator.seed_repository(
                    repository, kind, rows, int(settings.get("days_to_fetch", 180))
                )
                click.echo(
                    f"{kind.key:<20} {count} records -> {settings.get('storage_backend')}"
                )
        finally:
            repository.close()


@cli.command()
def reset() -> None:
    """Delete the local sandbox (database, input, output, logs)."""
    local_only("reset")
    from application.configuration_handling import PROJECT_ROOT

    sandbox = PROJECT_ROOT / "sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    click.echo(f"removed {sandbox}")


@cli.command()
@click.option("--host", help="Listen address (default: web_host setting, 127.0.0.1).")
@click.option(
    "--port",
    type=click.IntRange(1, 65535),
    help="Port (default: web_port setting, 8000).",
)
def serve(host: str | None, port: int | None) -> None:
    """Web dashboard: runs, validation errors, department routing."""
    from application.configuration_handling import settings
    from web.server import serve as serve_web

    serve_web(settings, host=host, port=port)


if __name__ == "__main__":
    cli()
