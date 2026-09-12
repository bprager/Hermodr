"""Audited credential controls used during real-device commissioning."""

from pathlib import Path
import sqlite3

from .audit import SAFE_CODE, record_change
from .config import Configuration
from .receiver import ReceiverError, load_protected_secret
from .repository import Repository


class CommissioningError(RuntimeError):
    """A bounded commissioning failure safe to expose to an operator."""


def _fields(*values: str) -> None:
    if any(SAFE_CODE.fullmatch(value) is None for value in values):
        raise CommissioningError("credential_fields_invalid")


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
