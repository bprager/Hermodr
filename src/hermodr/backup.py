"""Encrypted SQLite backup, verification, and isolated restore workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
from typing import Callable

from .build import BUILD
from .clock import unix_milliseconds
from .config import Configuration
from .database import connect, schema_version
from .identifiers import canonical_json
from .audit import AuditError, verify_chain


class BackupError(RuntimeError):
    """A bounded backup failure safe to expose to operators."""


Runner = Callable[..., subprocess.CompletedProcess[bytes]]
TABLES = (
    "subjects", "devices", "credentials", "raw_events", "processing_jobs",
    "observations", "places", "transitions", "visits", "trips",
    "coverage_gaps", "record_evidence", "recompute_windows", "outbox_records",
    "quarantine", "audit_events", "service_heartbeats", "retention_holds",
    "normalized_events", "retention_policies", "deletion_plans",
    "outbox_consumers", "outbox_receipts",
)


@dataclass(frozen=True)
class BackupReport:
    archive: str
    database_sha256: str
    schema_version: int
    status: str
    tables: dict[str, int]
    identifier_hashes: dict[str, str]

    def values(self) -> dict[str, object]:
        return {
            "archive": self.archive,
            "database_sha256": self.database_sha256,
            "schema_version": self.schema_version,
            "status": self.status,
            "tables": self.tables,
            "identifier_hashes": self.identifier_hashes,
        }


def _protected_file(path: Path, minimum_bytes: int = 16) -> None:
    try:
        details = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise BackupError("passphrase_unreadable") from exc
    if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) & 0o077 or details.st_size < minimum_bytes:
        raise BackupError("passphrase_permissions_invalid")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inventory(connection: sqlite3.Connection) -> dict[str, int]:
    return {name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]) for name in TABLES}


def _identifier_hashes(connection: sqlite3.Connection) -> dict[str, str]:
    fingerprints = {}
    for name in TABLES:
        keys = [row[1] for row in connection.execute(f"PRAGMA table_info({name})") if row[5]]
        rows = connection.execute(
            f"SELECT {','.join(keys)} FROM {name} ORDER BY {','.join(keys)}"
        ) if keys else ()
        fingerprints[name] = hashlib.sha256(canonical_json([list(row) for row in rows])).hexdigest()
    return fingerprints


def _state(configuration: Configuration, stage: str, success: bool, now_ms: int) -> None:
    connection = connect(configuration)
    try:
        connection.execute(
            "INSERT INTO operational_state VALUES (?, ?, ?) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value, updated_at_ms=excluded.updated_at_ms",
            (f"backup_{stage}_status", int(success), now_ms),
        )
        if success:
            connection.execute(
                "INSERT INTO operational_state VALUES (?, ?, ?) ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value, updated_at_ms=excluded.updated_at_ms",
                (f"backup_{stage}_last_success_ms", now_ms, now_ms),
            )
        connection.commit()
    finally:
        connection.close()


def _gpg(arguments: list[str], runner: Runner) -> None:
    try:
        runner(arguments, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackupError("encryption_operation_failed") from exc


def create_backup(
    configuration: Configuration,
    output: Path,
    passphrase_file: Path,
    *,
    now: datetime | None = None,
    runner: Runner | None = None,
) -> BackupReport:
    execute = subprocess.run if runner is None else runner
    _protected_file(passphrase_file)
    if output.exists() or output.is_symlink():
        raise BackupError("backup_output_exists")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = now or datetime.now(timezone.utc)
    now_ms = unix_milliseconds(stamp)
    try:
        with tempfile.TemporaryDirectory(prefix="hermodr-backup-") as temporary:
            root = Path(temporary)
            snapshot = root / "database.sqlite"
            source = connect(configuration)
            try:
                target = sqlite3.connect(snapshot)
                try:
                    source.backup(target)
                finally:
                    target.close()
            finally:
                source.close()
            restored = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
            restored.row_factory = sqlite3.Row
            try:
                if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError("backup_integrity_failed")
                verify_chain(restored)
                tables = _inventory(restored)
                identifiers = _identifier_hashes(restored)
                version = schema_version(restored)
            finally:
                restored.close()
            digest = _sha256(snapshot)
            manifest = {
                "build": BUILD.labels(),
                "created_at": stamp.astimezone(timezone.utc).isoformat(),
                "database_sha256": digest,
                "format": 1,
                "identifier_hashes": identifiers,
                "schema_version": version,
                "tables": tables,
            }
            (root / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
            package = root / "backup.tar"
            with tarfile.open(package, "w") as archive:
                archive.add(snapshot, arcname="database.sqlite")
                archive.add(root / "manifest.json", arcname="manifest.json")
            _gpg([
                "gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
                "--passphrase-file", os.fspath(passphrase_file), "--symmetric",
                "--cipher-algo", "AES256", "--output", os.fspath(output), os.fspath(package),
            ], execute)
        output.chmod(0o600)
        _state(configuration, "create", True, now_ms)
        return BackupReport(os.fspath(output), digest, version, "ok", tables, identifiers)
    except Exception as exc:
        _state(configuration, "create", False, now_ms)
        if isinstance(exc, BackupError):
            raise
        raise BackupError("backup_create_failed") from exc


def _unpack(encrypted: Path, passphrase_file: Path, root: Path, runner: Runner) -> tuple[Path, dict[str, object]]:
    _protected_file(passphrase_file)
    package = root / "backup.tar"
    _gpg([
        "gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
        "--passphrase-file", os.fspath(passphrase_file), "--decrypt",
        "--output", os.fspath(package), os.fspath(encrypted),
    ], runner)
    with tarfile.open(package, "r") as archive:
        members = archive.getmembers()
        if {item.name for item in members} != {"database.sqlite", "manifest.json"} or any(
            not item.isfile() or item.name.startswith(("/", "../")) for item in members
        ):
            raise BackupError("backup_archive_invalid")
        archive.extractall(root, filter="data")
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackupError("backup_manifest_invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != 1:
        raise BackupError("backup_manifest_invalid")
    return root / "database.sqlite", manifest


def verify_backup(
    configuration: Configuration,
    encrypted: Path,
    passphrase_file: Path,
    *,
    restore_test: bool = False,
    runner: Runner | None = None,
) -> BackupReport:
    execute = subprocess.run if runner is None else runner
    stage = "restore_test" if restore_test else "verify"
    now_ms = unix_milliseconds(datetime.now(timezone.utc))
    try:
        with tempfile.TemporaryDirectory(prefix="hermodr-restore-") as temporary:
            snapshot, manifest = _unpack(encrypted, passphrase_file, Path(temporary), execute)
            digest = _sha256(snapshot)
            if digest != manifest.get("database_sha256"):
                raise BackupError("backup_digest_mismatch")
            restored = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
            restored.row_factory = sqlite3.Row
            try:
                if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise BackupError("backup_integrity_failed")
                verify_chain(restored)
                tables = _inventory(restored)
                identifiers = _identifier_hashes(restored)
                version = schema_version(restored)
            finally:
                restored.close()
            if (
                tables != manifest.get("tables")
                or identifiers != manifest.get("identifier_hashes")
                or version != manifest.get("schema_version")
            ):
                raise BackupError("backup_reconciliation_failed")
            report = BackupReport(os.fspath(encrypted), digest, version, "ok", tables, identifiers)
        _state(configuration, stage, True, now_ms)
        return report
    except Exception as exc:
        _state(configuration, stage, False, now_ms)
        if isinstance(exc, BackupError):
            raise
        if isinstance(exc, AuditError):
            raise BackupError("backup_audit_chain_invalid") from exc
        raise BackupError("backup_verification_failed") from exc
