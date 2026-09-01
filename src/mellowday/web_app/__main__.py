"""Command-line entry point for a self-hosted Mellowday installation."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .runtime import (
    BackupError,
    RuntimeConfiguration,
    RuntimeConfigurationError,
    backup_installation,
    create_production_app,
    migrate_installation,
)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments.append("serve")
    parser = _argument_parser()
    parsed = parser.parse_args(arguments)
    try:
        configuration = RuntimeConfiguration.from_environment()
        if parsed.command == "serve":
            uvicorn.run(
                create_production_app(configuration),
                host=configuration.host,
                port=configuration.port,
            )
        elif parsed.command == "migrate":
            path = migrate_installation(configuration)
            print(f"Migrations complete: {path}")
        elif parsed.command == "backup":
            path = backup_installation(configuration, Path(parsed.destination))
            print(f"Backup complete: {path}")
        else:  # pragma: no cover - argparse constrains this branch
            parser.error("unknown command")
    except (RuntimeConfigurationError, BackupError) as error:
        parser.error(str(error))


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mellowday")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("serve", help="start the production Web App")
    subcommands.add_parser("migrate", help="apply local database migrations")
    backup = subcommands.add_parser(
        "backup", help="create a consistent local-data backup"
    )
    backup.add_argument("destination", help="new directory to create")
    return parser


if __name__ == "__main__":
    main()
