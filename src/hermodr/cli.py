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
from .audit import ANNOTATION_ACTIONS, AuditError, record_change, verify_chain
from .clock import SystemClock, unix_milliseconds
from .commissioning import (
    CommissioningError, commissioning_preflight, disable_device, enroll_device,
    revoke_credential, stage_credential,
)
from .processor import heartbeat, serve as serve_processor
from .receiver import ReceiverApplication, ReceiverError, ReceiverService
from .derivation import DerivationError, preview_subject, reprocess_subject
from .lifecycle import (
    LifecycleError, apply_deletion, apply_retention, approve_default_policy, plan_deletion,
)


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
    admin.add_argument("action", choices=(
        "build-info", "metrics", "audit-change", "audit-verify", "backup-create",
        "backup-verify", "restore-test", "reprocess-preview", "reprocess-apply",
        "retention-approve", "retention-apply", "deletion-plan", "deletion-apply",
        "commissioning-preflight", "credential-stage", "credential-revoke",
        "device-enroll", "device-disable",
    ))
    admin.add_argument("--archive", type=Path)
    admin.add_argument("--passphrase-file", type=Path)
    admin.add_argument("--audit-action", choices=sorted(ANNOTATION_ACTIONS))
    admin.add_argument("--target-id")
    admin.add_argument("--reason-code")
    admin.add_argument("--run-id")
    admin.add_argument("--subject-id")
    admin.add_argument("--start-ms", type=int)
    admin.add_argument("--end-ms", type=int)
    admin.add_argument("--plan-id")
    admin.add_argument("--device-id")
    admin.add_argument("--source-tid")
    admin.add_argument("--key-id")
    admin.add_argument("--secret-ref", type=Path)
    admin.add_argument("--valid-from-ms", type=int)
    admin.add_argument("--valid-until-ms", type=int)
    admin.add_argument("--now-ms", type=int)
    admin.add_argument("--batch-size", type=int, default=100)
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
            elif args.command == "admin" and args.action == "commissioning-preflight":
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                report = commissioning_preflight(connection, now_ms)
                _safe_result(**report.__dict__, status="ready" if report.ready else "action_required")
            elif args.command == "admin" and args.action == "audit-verify":
                _safe_result(entries=verify_chain(connection), status="ok")
            elif args.command == "admin" and args.action == "audit-change":
                if None in (args.audit_action, args.target_id, args.reason_code, args.run_id):
                    raise AuditError("audit_arguments_missing")
                audit_id = record_change(
                    connection, configuration, args.audit_action, args.target_id,
                    args.reason_code, args.run_id,
                )
                _safe_result(action=args.audit_action, audit_id=audit_id, status="ok")
            elif args.command == "admin" and args.action in {"reprocess-preview", "reprocess-apply"}:
                if None in (args.subject_id, args.reason_code, args.run_id):
                    raise DerivationError("reprocess_arguments_missing")
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                if args.action == "reprocess-preview":
                    report = preview_subject(connection, configuration, args.subject_id, now_ms)
                else:
                    report = reprocess_subject(connection, configuration, args.subject_id, now_ms)
                record_change(
                    connection, configuration, "reprocess", args.subject_id,
                    args.reason_code, args.run_id, subject_id=args.subject_id,
                )
                _safe_result(**report.__dict__, mode=args.action.rsplit("-", 1)[1], status="ok")
            elif args.command == "admin" and args.action == "retention-approve":
                if None in (args.subject_id, args.run_id):
                    raise LifecycleError("retention_arguments_missing")
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                approve_default_policy(connection, configuration, args.subject_id, now_ms, args.run_id)
                _safe_result(policy_version="v1", status="ok")
            elif args.command == "admin" and args.action == "retention-apply":
                if None in (args.subject_id, args.run_id):
                    raise LifecycleError("retention_arguments_missing")
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                report = apply_retention(
                    connection, configuration, args.subject_id, now_ms, args.run_id, args.batch_size,
                )
                _safe_result(**report, status="ok")
            elif args.command == "admin" and args.action == "deletion-plan":
                if None in (args.subject_id, args.start_ms, args.end_ms, args.run_id):
                    raise LifecycleError("deletion_arguments_missing")
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                plan_id, counts = plan_deletion(
                    connection, configuration, args.subject_id, args.start_ms, args.end_ms,
                    now_ms, args.run_id,
                )
                _safe_result(counts=counts, plan_id=plan_id, status="planned")
            elif args.command == "admin" and args.action == "deletion-apply":
                if None in (args.plan_id, args.run_id):
                    raise LifecycleError("deletion_arguments_missing")
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                report = apply_deletion(connection, configuration, args.plan_id, now_ms, args.run_id)
                _safe_result(counts=report, plan_id=args.plan_id, status="applied")
            elif args.command == "admin" and args.action == "credential-stage":
                if None in (
                    args.subject_id, args.device_id, args.key_id, args.secret_ref,
                    args.reason_code, args.run_id,
                ):
                    raise CommissioningError("credential_arguments_missing")
                valid_from_ms = args.valid_from_ms
                if valid_from_ms is None:
                    valid_from_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                audit_id = stage_credential(
                    connection, configuration, subject_id=args.subject_id, device_id=args.device_id,
                    key_id=args.key_id, secret_ref=args.secret_ref, valid_from_ms=valid_from_ms,
                    valid_until_ms=args.valid_until_ms, reason_code=args.reason_code, run_id=args.run_id,
                )
                _safe_result(audit_id=audit_id, status="staged")
            elif args.command == "admin" and args.action == "device-enroll":
                if None in (
                    args.subject_id, args.device_id, args.source_tid,
                    args.reason_code, args.run_id,
                ):
                    raise CommissioningError("device_arguments_missing")
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                audit_id = enroll_device(
                    connection, configuration, subject_id=args.subject_id,
                    device_id=args.device_id, source_tid=args.source_tid,
                    enrolled_at_ms=now_ms, reason_code=args.reason_code, run_id=args.run_id,
                )
                _safe_result(audit_id=audit_id, status="enrolled")
            elif args.command == "admin" and args.action == "device-disable":
                if None in (args.subject_id, args.device_id, args.reason_code, args.run_id):
                    raise CommissioningError("device_arguments_missing")
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                audit_id, changed = disable_device(
                    connection, configuration, subject_id=args.subject_id,
                    device_id=args.device_id, disabled_at_ms=now_ms,
                    reason_code=args.reason_code, run_id=args.run_id,
                )
                _safe_result(
                    audit_id=audit_id, changed=changed,
                    status="disabled" if changed else "already_disabled",
                )
            elif args.command == "admin" and args.action == "credential-revoke":
                if None in (args.key_id, args.reason_code, args.run_id):
                    raise CommissioningError("credential_arguments_missing")
                now_ms = args.now_ms if args.now_ms is not None else unix_milliseconds(SystemClock().now())
                audit_id, changed = revoke_credential(
                    connection, configuration, key_id=args.key_id, revoked_at_ms=now_ms,
                    reason_code=args.reason_code, run_id=args.run_id,
                )
                _safe_result(audit_id=audit_id, changed=changed, status="revoked" if changed else "already_revoked")
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
    except (
        AuditError, BackupError, CommissioningError, ConfigurationError, DatabaseError, DerivationError,
        LifecycleError, ReceiverError,
    ) as exc:
        _safe_result(error=str(exc), status="error")
        return 2
    except (OSError, sqlite3.Error):
        _safe_result(error="database_unavailable", status="error")
        return 2


def main() -> None:
    raise SystemExit(run())
