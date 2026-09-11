"""Command-line boundaries for the four Hermodr processes."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .build import BUILD
from .config import ConfigurationError, load_configuration
from .database import DatabaseError, connect, migrate, schema_version
from .metrics import reconstruct_critical_metrics


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="hermodr")
    root.add_argument("--config", type=Path, required=True)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("receiver", "processor"):
        command = commands.add_parser(name)
        command.add_argument("--check", action="store_true", required=True)
    admin = commands.add_parser("admin")
    admin.add_argument("action", choices=("build-info", "metrics"))
    migration = commands.add_parser("migrate")
    migration.add_argument("action", choices=("up", "status"))
    return root


def _safe_result(**values: object) -> None:
    print(json.dumps(values, sort_keys=True, separators=(",", ":")))


def run(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    try:
        configuration = load_configuration(args.config)
        connection = connect(configuration)
        try:
            if args.command == "migrate" and args.action == "up":
                applied = migrate(connection)
                _safe_result(applied=list(applied), schema_version=schema_version(connection), status="ok")
                return 0
            if schema_version(connection) != int(BUILD.schema_version):
                raise DatabaseError("schema_version_invalid")
            if args.command in {"receiver", "processor"}:
                connection.execute("SELECT 1").fetchone()
                _safe_result(command=args.command, config_fingerprint=configuration.fingerprint, status="ready")
            elif args.command == "admin" and args.action == "build-info":
                _safe_result(**BUILD.labels())
            elif args.command == "admin" and args.action == "metrics":
                sys.stdout.write(reconstruct_critical_metrics(connection, 0).render())
            else:
                _safe_result(schema_version=schema_version(connection), status="ok")
            return 0
        finally:
            connection.close()
    except (ConfigurationError, DatabaseError) as exc:
        _safe_result(error=str(exc), status="error")
        return 2
    except (OSError, sqlite3.Error):
        _safe_result(error="database_unavailable", status="error")
        return 2


def main() -> None:
    raise SystemExit(run())
