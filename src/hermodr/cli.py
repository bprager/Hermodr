"""Command-line boundaries for the four Hermodr processes."""

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from threading import Event
import signal

from .build import BUILD
from .config import ConfigurationError, load_configuration
from .database import DatabaseError, connect, migrate, schema_version
from .metrics import reconstruct_critical_metrics
from .backup import BackupError, create_backup, verify_backup
from .audit import ANNOTATION_ACTIONS, AuditError, record_change
from .clock import SystemClock, unix_milliseconds
from .processor import heartbeat, serve as serve_processor
from .receiver import ReceiverApplication, ReceiverError, ReceiverService


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="hermodr")
    root.add_argument("--config", type=Path, required=True)
    commands = root.add_subparsers(dest="command", required=True)
    receiver = commands.add_parser("receiver")
    receiver.add_argument("--check", action="store_true")
    processor = commands.add_parser("processor")
    processor.add_argument("--check", action="store_true")
    processor.add_argument("--interval-seconds", type=float, default=30)
    admin = commands.add_parser("admin")
    admin.add_argument("action", choices=("build-info", "metrics", "audit-change", "backup-create", "backup-verify", "restore-test"))
    admin.add_argument("--archive", type=Path)
    admin.add_argument("--passphrase-file", type=Path)
    admin.add_argument("--audit-action", choices=sorted(ANNOTATION_ACTIONS))
    admin.add_argument("--target-id")
    admin.add_argument("--reason-code")
    admin.add_argument("--run-id")
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
            if args.command == "receiver":
                connection.execute("SELECT 1").fetchone()
                service = ReceiverService(configuration, sys.stderr)
                if args.check:
                    service.startup_check()
                    _safe_result(command=args.command, config_fingerprint=configuration.fingerprint, status="ready")
                else:
                    ReceiverApplication(service).serve()
            elif args.command == "processor":
                connection.execute("SELECT 1").fetchone()
                if args.check:
                    heartbeat(configuration)
                    _safe_result(command=args.command, config_fingerprint=configuration.fingerprint, status="ready")
                else:
                    if args.interval_seconds <= 0:
                        raise DatabaseError("processor_interval_invalid")
                    stopped = Event()
                    previous = {item: signal.signal(item, lambda _signum, _frame: stopped.set()) for item in (signal.SIGINT, signal.SIGTERM)}
                    try:
                        serve_processor(configuration, stopped, args.interval_seconds)
                    finally:
                        for item, handler in previous.items():
                            signal.signal(item, handler)
            elif args.command == "admin" and args.action == "build-info":
                _safe_result(**BUILD.labels())
            elif args.command == "admin" and args.action == "metrics":
                sys.stdout.write(reconstruct_critical_metrics(connection, unix_milliseconds(SystemClock().now())).render())
            elif args.command == "admin" and args.action == "audit-change":
                if None in (args.audit_action, args.target_id, args.reason_code, args.run_id):
                    raise AuditError("audit_arguments_missing")
                audit_id = record_change(
                    connection, configuration, args.audit_action, args.target_id,
                    args.reason_code, args.run_id,
                )
                _safe_result(action=args.audit_action, audit_id=audit_id, status="ok")
            elif args.command == "admin":
                if args.archive is None or args.passphrase_file is None:
                    raise BackupError("backup_arguments_missing")
                connection.close()
                connection = None
                if args.action == "backup-create":
                    report = create_backup(configuration, args.archive, args.passphrase_file)
                else:
                    report = verify_backup(
                        configuration, args.archive, args.passphrase_file,
                        restore_test=args.action == "restore-test",
                    )
                _safe_result(**report.values())
            else:
                _safe_result(schema_version=schema_version(connection), status="ok")
            return 0
        finally:
            if connection is not None:
                connection.close()
    except (AuditError, BackupError, ConfigurationError, DatabaseError, ReceiverError) as exc:
        _safe_result(error=str(exc), status="error")
        return 2
    except (OSError, sqlite3.Error):
        _safe_result(error="database_unavailable", status="error")
        return 2


def main() -> None:
    raise SystemExit(run())
