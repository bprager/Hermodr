"""Privacy-safe preflight and audited controls for device commissioning."""

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3

from .audit import SAFE_CODE, AuditError, record_change, verify_chain
from .config import Configuration
from .receiver import ReceiverError, load_protected_secret
from .repository import Repository


class CommissioningError(RuntimeError):
    """A bounded commissioning failure safe to expose to an operator."""


SOURCE_TID = re.compile(r"^[A-Za-z0-9]{2}$", re.ASCII)


@dataclass(frozen=True)
class CommissioningPreflight:
    """Aggregate readiness evidence which contains no authority identifiers."""

    active_subjects: int
    active_devices: int
    configured_device_identities: int
    approved_retention_policies: int
    usable_credentials: int
    protected_credentials: int
    blocking_jobs: int
    blocking_recompute_windows: int
    pending_quarantine: int
    audit_entries: int
    database_integrity: bool
    audit_integrity: bool
    backup_create: bool
    backup_verify: bool
    backup_restore_test: bool
    issues: tuple[str, ...]
    ready: bool


def commissioning_preflight(connection: sqlite3.Connection, now_ms: int) -> CommissioningPreflight:
    """Assess repository-controlled M8 gates without exposing sensitive values."""
    if now_ms < 0:
        raise CommissioningError("commissioning_time_invalid")
    database_integrity = connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    try:
        audit_entries = verify_chain(connection)
        audit_integrity = True
    except AuditError:
        audit_entries = 0
        audit_integrity = False
    active_subjects = connection.execute(
        "SELECT COUNT(*) FROM subjects WHERE status='active'"
    ).fetchone()[0]
    active_devices, configured_device_identities = connection.execute(
        """SELECT COUNT(*), COUNT(d.source_tid)
           FROM devices d JOIN subjects s USING(subject_id)
           WHERE d.status='active' AND s.status='active'"""
    ).fetchone()
    approved_retention_policies = connection.execute(
        """SELECT COUNT(*) FROM retention_policies p JOIN subjects s USING(subject_id)
           WHERE s.status='active'"""
    ).fetchone()[0]
    credentials = Repository(connection).usable_credentials(now_ms)
    protected_credentials = 0
    for credential, _source_tid in credentials:
        try:
            load_protected_secret(Path(credential.secret_ref), minimum_bytes=24)
        except ReceiverError:
            continue
        protected_credentials += 1
    blocking_jobs = connection.execute(
        "SELECT COUNT(*) FROM processing_jobs WHERE state IN ('pending','processing','quarantined','failed')"
    ).fetchone()[0]
    blocking_recompute_windows = connection.execute(
        "SELECT COUNT(*) FROM recompute_windows WHERE state IN ('pending','processing','failed')"
    ).fetchone()[0]
    pending_quarantine = connection.execute(
        "SELECT COUNT(*) FROM quarantine WHERE review_state='pending'"
    ).fetchone()[0]
    backup = {}
    for stage in ("create", "verify", "restore_test"):
        row = connection.execute(
            "SELECT state_value FROM operational_state WHERE state_key=?",
            (f"backup_{stage}_status",),
        ).fetchone()
        backup[stage] = row is not None and row[0] == 1
    checks = (
        (active_subjects == 1, "active_subject_count"),
        (active_devices >= 1, "active_device_missing"),
        (configured_device_identities == active_devices, "device_identity_missing"),
        (approved_retention_policies == active_subjects, "retention_policy_missing"),
        (len(credentials) >= 1, "usable_credential_missing"),
        (protected_credentials == len(credentials), "protected_credential_invalid"),
        (blocking_jobs == 0, "processing_work_blocking"),
        (blocking_recompute_windows == 0, "recompute_work_blocking"),
        (pending_quarantine == 0, "quarantine_review_pending"),
        (database_integrity, "database_integrity_invalid"),
        (audit_integrity, "audit_integrity_invalid"),
        (backup["create"], "backup_create_missing"),
        (backup["verify"], "backup_verify_missing"),
        (backup["restore_test"], "backup_restore_test_missing"),
    )
    issues = tuple(code for passed, code in checks if not passed)
    return CommissioningPreflight(
        active_subjects=active_subjects,
        active_devices=active_devices,
        configured_device_identities=configured_device_identities,
        approved_retention_policies=approved_retention_policies,
        usable_credentials=len(credentials),
        protected_credentials=protected_credentials,
        blocking_jobs=blocking_jobs,
        blocking_recompute_windows=blocking_recompute_windows,
        pending_quarantine=pending_quarantine,
        audit_entries=audit_entries,
        database_integrity=database_integrity,
        audit_integrity=audit_integrity,
        backup_create=backup["create"],
        backup_verify=backup["verify"],
        backup_restore_test=backup["restore_test"],
        issues=issues,
        ready=not issues,
    )


def _fields(*values: str) -> None:
    if any(SAFE_CODE.fullmatch(value) is None for value in values):
        raise CommissioningError("credential_fields_invalid")


def _device_fields(*values: str) -> None:
    if any(not isinstance(value, str) or SAFE_CODE.fullmatch(value) is None for value in values):
        raise CommissioningError("device_fields_invalid")


def enroll_device(
    connection: sqlite3.Connection,
    configuration: Configuration,
    *,
    subject_id: str,
    device_id: str,
    source_tid: str,
    enrolled_at_ms: int,
    reason_code: str,
    run_id: str,
) -> str:
    _device_fields(subject_id, device_id, reason_code, run_id)
    if not isinstance(source_tid, str) or SOURCE_TID.fullmatch(source_tid) is None:
        raise CommissioningError("device_source_tid_invalid")
    if isinstance(enrolled_at_ms, bool) or not isinstance(enrolled_at_ms, int) or enrolled_at_ms < 0:
        raise CommissioningError("device_time_invalid")
    try:
        connection.execute("BEGIN IMMEDIATE")
        subject = connection.execute(
            "SELECT status FROM subjects WHERE subject_id=?", (subject_id,),
        ).fetchone()
        if subject is None:
            raise CommissioningError("device_subject_not_found")
        if subject[0] != "active":
            raise CommissioningError("device_subject_inactive")
        connection.execute(
            """INSERT INTO devices(subject_id,device_id,status,enrolled_at_ms,source_tid)
               VALUES (?,?,'active',?,?)""",
            (subject_id, device_id, enrolled_at_ms, source_tid),
        )
        audit_id = record_change(
            connection, configuration, "device_change", device_id, reason_code, run_id,
            subject_id=subject_id, commit=False,
        )
        connection.commit()
        return audit_id
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise CommissioningError("device_conflict") from exc
    except Exception:
        connection.rollback()
        raise


def disable_device(
    connection: sqlite3.Connection,
    configuration: Configuration,
    *,
    subject_id: str,
    device_id: str,
    disabled_at_ms: int,
    reason_code: str,
    run_id: str,
) -> tuple[str | None, bool]:
    _device_fields(subject_id, device_id, reason_code, run_id)
    if isinstance(disabled_at_ms, bool) or not isinstance(disabled_at_ms, int) or disabled_at_ms < 0:
        raise CommissioningError("device_time_invalid")
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """SELECT d.status,d.enrolled_at_ms,s.status FROM devices d
               JOIN subjects s ON s.subject_id=d.subject_id
               WHERE d.subject_id=? AND d.device_id=?""",
            (subject_id, device_id),
        ).fetchone()
        if row is None:
            raise CommissioningError("device_not_found")
        if row[0] == "disabled":
            connection.rollback()
            return None, False
        if row[0] != "active":
            raise CommissioningError("device_not_active")
        if row[2] != "active":
            raise CommissioningError("device_subject_inactive")
        if disabled_at_ms < row[1]:
            raise CommissioningError("device_time_invalid")
        usable = connection.execute(
            """SELECT 1 FROM credentials c
               JOIN subjects s ON s.subject_id=c.subject_id
               WHERE c.subject_id=? AND c.device_id=? AND s.status='active'
                 AND c.valid_from_ms <= ?
                 AND (c.valid_until_ms IS NULL OR c.valid_until_ms > ?)
               LIMIT 1""",
            (subject_id, device_id, disabled_at_ms, disabled_at_ms),
        ).fetchone()
        if usable is not None:
            raise CommissioningError("device_credential_usable")
        connection.execute(
            """UPDATE devices SET status='disabled', revoked_at_ms=?
               WHERE subject_id=? AND device_id=?""",
            (disabled_at_ms, subject_id, device_id),
        )
        audit_id = record_change(
            connection, configuration, "device_change", device_id, reason_code, run_id,
            subject_id=subject_id, commit=False,
        )
        connection.commit()
        return audit_id, True
    except Exception:
        connection.rollback()
        raise


def stage_credential(
    connection: sqlite3.Connection,
    configuration: Configuration,
    *,
    subject_id: str,
    device_id: str,
    key_id: str,
    secret_ref: Path,
    valid_from_ms: int,
    valid_until_ms: int | None,
    reason_code: str,
    run_id: str,
) -> str:
    _fields(subject_id, device_id, key_id, reason_code, run_id)
    if not secret_ref.is_absolute():
        raise CommissioningError("credential_secret_ref_invalid")
    if valid_from_ms < 0 or valid_until_ms is not None and valid_until_ms <= valid_from_ms:
        raise CommissioningError("credential_validity_invalid")
    try:
        load_protected_secret(secret_ref, minimum_bytes=24)
    except ReceiverError as exc:
        raise CommissioningError(str(exc)) from exc
    try:
        connection.execute("BEGIN IMMEDIATE")
        device = connection.execute(
            """SELECT d.status, s.status FROM devices d JOIN subjects s ON s.subject_id=d.subject_id
               WHERE d.subject_id=? AND d.device_id=?""",
            (subject_id, device_id),
        ).fetchone()
        if device is None:
            raise CommissioningError("credential_device_not_found")
        if device[0] != "active" or device[1] != "active":
            raise CommissioningError("credential_authority_inactive")
        connection.execute(
            """INSERT INTO credentials(subject_id,device_id,key_id,secret_ref,valid_from_ms,valid_until_ms)
               VALUES (?,?,?,?,?,?)""",
            (subject_id, device_id, key_id, str(secret_ref), valid_from_ms, valid_until_ms),
        )
        audit_id = record_change(
            connection, configuration, "credential_change", key_id, reason_code, run_id,
            subject_id=subject_id, commit=False,
        )
        connection.commit()
        return audit_id
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise CommissioningError("credential_conflict") from exc
    except Exception:
        connection.rollback()
        raise


def revoke_credential(
    connection: sqlite3.Connection,
    configuration: Configuration,
    *,
    key_id: str,
    revoked_at_ms: int,
    reason_code: str,
    run_id: str,
) -> tuple[str | None, bool]:
    _fields(key_id, reason_code, run_id)
    if revoked_at_ms < 0:
        raise CommissioningError("credential_validity_invalid")
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT subject_id,valid_from_ms,valid_until_ms FROM credentials WHERE key_id=?", (key_id,),
        ).fetchone()
        if row is None:
            raise CommissioningError("credential_not_found")
        subject_id, valid_from_ms, valid_until_ms = row
        if valid_until_ms is not None and valid_until_ms <= revoked_at_ms:
            connection.rollback()
            return None, False
        if revoked_at_ms <= valid_from_ms:
            raise CommissioningError("credential_validity_invalid")
        replacement = False
        for credential, _source_tid in Repository(connection).usable_credentials(revoked_at_ms):
            if credential.key_id == key_id:
                continue
            try:
                load_protected_secret(Path(credential.secret_ref), minimum_bytes=24)
            except ReceiverError:
                continue
            if credential.subject_id == subject_id:
                replacement = True
                break
        if not replacement:
            raise CommissioningError("credential_replacement_required")
        connection.execute(
            "UPDATE credentials SET valid_until_ms=? WHERE key_id=?", (revoked_at_ms, key_id),
        )
        audit_id = record_change(
            connection, configuration, "credential_change", key_id, reason_code, run_id,
            subject_id=subject_id, commit=False,
        )
        connection.commit()
        return audit_id, True
    except Exception:
        connection.rollback()
        raise
