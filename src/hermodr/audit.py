"""Append-only operational audit records used by dashboard annotations."""

from datetime import datetime, timezone
import hashlib
import re
import sqlite3

from .build import BUILD
from .clock import unix_milliseconds
from .config import Configuration
from .enums import AuditAction
from .identifiers import canonical_json, sortable_id


SAFE_CODE = re.compile(r"^[a-z0-9_:-]{1,128}$")
ANNOTATION_ACTIONS = frozenset({
    AuditAction.CONFIG_ACTIVATE.value,
    AuditAction.CREDENTIAL_CHANGE.value,
    "deployment",
    "deletion_apply",
    "deletion_plan",
    "device_change",
    "reprocess",
    "retention_apply",
    "retention_policy",
})


class AuditError(RuntimeError):
    """A bounded audit failure safe to expose to an operator."""


def record_change(
    connection: sqlite3.Connection,
    configuration: Configuration,
    action: str,
    target_id: str,
    reason: str,
    run_id: str,
    *,
    subject_id: str | None = None,
    commit: bool = True,
    now: datetime | None = None,
) -> str:
    if action not in ANNOTATION_ACTIONS or any(SAFE_CODE.fullmatch(value) is None for value in (target_id, reason, run_id)):
        raise AuditError("audit_fields_invalid")
    stamp = now or datetime.now(timezone.utc)
    occurred_at_ms = unix_milliseconds(stamp)
    audit_id = sortable_id("aud", stamp)
    row = connection.execute("SELECT entry_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
    previous_hash = None if row is None else str(row[0])
    entry = {
        "action": action,
        "actor": "operator",
        "audit_id": audit_id,
        "build_version": BUILD.version,
        "config_fingerprint": configuration.fingerprint,
        "occurred_at_ms": occurred_at_ms,
        "previous_hash": previous_hash,
        "reason": reason,
        "result": "success",
        "run_id": run_id,
        "target_id": target_id,
        "target_type": action,
    }
    if subject_id is not None:
        entry["subject_id"] = subject_id
    entry_hash = hashlib.sha256(canonical_json(entry)).hexdigest()
    connection.execute(
        """INSERT INTO audit_events(
            audit_id, subject_id, actor, action, target_type, target_id, reason,
            run_id, result, occurred_at_ms, config_fingerprint, build_version,
            previous_hash, entry_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            audit_id, subject_id, entry["actor"], action, action, target_id, reason, run_id,
            entry["result"], occurred_at_ms, entry["config_fingerprint"],
            entry["build_version"], previous_hash, entry_hash,
        ),
    )
    if commit:
        connection.commit()
    return audit_id


def verify_chain(connection: sqlite3.Connection) -> int:
    previous_hash = None
    count = 0
    for row in connection.execute("SELECT * FROM audit_events ORDER BY sequence"):
        entry = {
            "action": row["action"], "actor": row["actor"], "audit_id": row["audit_id"],
            "build_version": row["build_version"], "config_fingerprint": row["config_fingerprint"],
            "occurred_at_ms": row["occurred_at_ms"], "previous_hash": row["previous_hash"],
            "reason": row["reason"], "result": row["result"], "run_id": row["run_id"],
            "target_id": row["target_id"],
            "target_type": row["target_type"],
        }
        if row["subject_id"] is not None:
            entry["subject_id"] = row["subject_id"]
        if row["previous_hash"] != previous_hash or hashlib.sha256(canonical_json(entry)).hexdigest() != row["entry_hash"]:
            raise AuditError("audit_chain_invalid")
        previous_hash = row["entry_hash"]
        count += 1
    return count
