#!/usr/bin/env python3
"""
Waybill-Declaration Parsing application using Pydantic
Suitable for use w/ FastAPI/Django

    python main.py [--env local] run                 # process input files (default command)
    python main.py --env local seed [--rows 50] ...  # generate mock input files / database records
    python main.py --env local reset                 # wipe the local sandbox
    python main.py [--env local] serve               # web dashboard (http://localhost:8000/ locally)

``--env`` selects the settings profile (same as the ``CORD_ENV`` variable), see
``application/configuration_handling.py``.
"""

import argparse
import os
import shutil
import sys


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Waybill / declaration parsing ETL")
    parser.add_argument("--env", help="settings profile, e.g. 'local' (default: $CORD_ENV or production)")
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("run", help="validate input files, store them and export department reports")

    seed = commands.add_parser("seed", help="generate schema based mock data (local profiles only)")
    seed.add_argument("--rows", type=int, default=50, help="rows per document type (default: 50)")
    seed.add_argument("--kinds", nargs="+", help="document types: declaration declarationupdates clearancestatement waybill")
    seed.add_argument("--invalid-ratio", type=float, default=0.1, help="share of deliberately invalid csv rows (default: 0.1)")
    seed.add_argument("--target", choices=["csv", "db", "both"], default="csv",
                      help="csv: input files to be processed by 'run'; db: insert records directly (default: csv)")
    seed.add_argument("--seed", type=int, help="random seed for reproducible data")

    commands.add_parser("reset", help="delete the local sandbox (database, input, output, logs)")

    serve = commands.add_parser("serve", help="web dashboard: runs, validation errors, department routing")
    serve.add_argument("--host", help="listen address (default: web_host setting, 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port (default: web_port setting, 8000)")
    args = parser.parse_args(argv)
    args.command = args.command or "run"
    return args


def seed(args) -> None:
    from application.configuration_handling import resolve_path, settings
    from application.mock_data import MockDataGenerator, kinds_from_names
    from application.storage import build_repository

    generator = MockDataGenerator(seed=args.seed)
    kinds = kinds_from_names(args.kinds)
    if args.target in ("csv", "both"):
        input_dir = resolve_path(settings.input_files_path)
        for kind in kinds:
            path = generator.write_csv(input_dir, kind, args.rows, args.invalid_ratio, settings.get("csv_delimiters", "^")[0])
            print(f"{kind.key:<20} {args.rows} rows -> {path}")
    if args.target in ("db", "both"):
        repository = build_repository(settings)
        try:
            for kind in kinds:
                count = generator.seed_repository(repository, kind, args.rows, int(settings.get("days_to_fetch", 180)))
                print(f"{kind.key:<20} {count} records -> {settings.get('storage_backend')}")
        finally:
            repository.close()


def reset() -> None:
    from application.configuration_handling import PROJECT_ROOT

    sandbox = PROJECT_ROOT / "sandbox"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    print(f"removed {sandbox}")


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.env:
        os.environ["CORD_ENV"] = args.env

    from application.configuration_handling import ENVIRONMENT

    if args.command in ("seed", "reset") and ENVIRONMENT == "production":
        print(f"'{args.command}' only works with a local profile, e.g.: python main.py --env local {args.command}")
        return 2
    if args.command == "seed":
        seed(args)
    elif args.command == "reset":
        reset()
    elif args.command == "serve":
        from application.configuration_handling import settings
        from web.server import serve

        serve(settings, host=args.host, port=args.port)
    else:
        from application.pipeline import run

        print(f"[{ENVIRONMENT}]")
        print(run().summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
