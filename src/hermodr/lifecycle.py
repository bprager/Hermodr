"""Subject-isolated retention and reviewed deletion workflows."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import sqlite3

from .audit import record_change
from .config import Configuration
from .identifiers import canonical_json, deterministic_id
from .processor import _outbox


DAY_MS = 86_400_000
SAFE_CODE = re.compile(r"^[a-z0-9_:-]{1,128}$")


class LifecycleError(RuntimeError):
    """A bounded lifecycle failure safe for operator output."""


def _stamp(now_ms: int) -> datetime:
    return datetime.fromtimestamp(now_ms / 1000, timezone.utc)


def approve_default_policy(
    connection: sqlite3.Connection,
    configuration: Configuration,
    subject_id: str,
    now_ms: int,
    run_id: str,
) -> None:
    if SAFE_CODE.fullmatch(run_id) is None:
        raise LifecycleError("lifecycle_fields_invalid")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO retention_policies VALUES (?, 90, 180, NULL, 30, ?, 'v1')
               ON CONFLICT(subject_id) DO UPDATE SET raw_days=90, normalized_days=180,
               derived_days=NULL, operational_log_days=30, approved_at_ms=excluded.approved_at_ms,
               policy_version=excluded.policy_version""",
            (subject_id, now_ms),
        )
        record_change(
            connection, configuration, "retention_policy", "policy_v1", "owner_approved",
            run_id, subject_id=subject_id, commit=False, now=_stamp(now_ms),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _held(connection: sqlite3.Connection, subject_id: str, captured_at_ms: int) -> bool:
    return connection.execute(
        """SELECT 1 FROM retention_holds WHERE subject_id=? AND released_at_ms IS NULL
           AND start_ms <= ? AND end_ms >= ? LIMIT 1""",
        (subject_id, captured_at_ms, captured_at_ms),
    ).fetchone() is not None


def apply_retention(
    connection: sqlite3.Connection,
    configuration: Configuration,
    subject_id: str,
    now_ms: int,
    run_id: str,
    batch_size: int = 100,
) -> dict[str, int]:
    if SAFE_CODE.fullmatch(run_id) is None or not 1 <= batch_size <= 1000:
        raise LifecycleError("retention_request_invalid")
    policy = connection.execute(
        "SELECT raw_days, normalized_days FROM retention_policies WHERE subject_id=?", (subject_id,),
    ).fetchone()
    if policy is None:
        raise LifecycleError("retention_policy_missing")
    raw_cutoff, normalized_cutoff = now_ms - policy[0] * DAY_MS, now_ms - policy[1] * DAY_MS
    result = {"raw_payloads": 0, "normalized_events": 0, "observations": 0}
    try:
        connection.execute("BEGIN IMMEDIATE")
        raw_rows = connection.execute(
            """SELECT ingest_id, COALESCE(captured_at_ms, received_at_ms) FROM raw_events r
               WHERE subject_id=? AND payload_expired_at_ms IS NULL
                 AND COALESCE(captured_at_ms, received_at_ms) < ?
                 AND NOT EXISTS (
                   SELECT 1 FROM retention_holds h WHERE h.subject_id=r.subject_id
                     AND h.released_at_ms IS NULL AND h.start_ms <= COALESCE(r.captured_at_ms,r.received_at_ms)
                     AND h.end_ms >= COALESCE(r.captured_at_ms,r.received_at_ms)
                 ) ORDER BY received_at_ms LIMIT ?""",
            (subject_id, raw_cutoff, batch_size),
        ).fetchall()
        for row in raw_rows:
            result["raw_payloads"] += connection.execute(
                "UPDATE raw_events SET payload=X'', payload_expired_at_ms=? WHERE subject_id=? AND ingest_id=?",
                (now_ms, subject_id, row[0]),
            ).rowcount

        observations = connection.execute(
            "SELECT observation_id, captured_at_ms FROM observations WHERE subject_id=? AND captured_at_ms < ? ORDER BY captured_at_ms LIMIT ?",
            (subject_id, normalized_cutoff, batch_size),
        ).fetchall()
        removable = []
        for row in observations:
            if _held(connection, subject_id, row[1]):
                continue
            unresolved = connection.execute(
                """SELECT 1 FROM record_evidence e WHERE e.subject_id=? AND e.observation_id=? AND (
                     (e.record_type='transition' AND EXISTS (SELECT 1 FROM transitions d WHERE d.subject_id=e.subject_id AND d.transition_id=e.record_id AND d.status='provisional')) OR
                     (e.record_type='visit' AND EXISTS (SELECT 1 FROM visits d WHERE d.subject_id=e.subject_id AND d.visit_id=e.record_id AND d.status='provisional')) OR
                     (e.record_type='trip' AND EXISTS (SELECT 1 FROM trips d WHERE d.subject_id=e.subject_id AND d.trip_id=e.record_id AND d.status='provisional')) OR
                     (e.record_type='coverage_gap' AND EXISTS (SELECT 1 FROM coverage_gaps d WHERE d.subject_id=e.subject_id AND d.gap_id=e.record_id AND d.status='provisional')))
                   LIMIT 1""",
                (subject_id, row[0]),
            ).fetchone()
            if unresolved is None:
                removable.append(row[0])
        for observation_id in removable:
            connection.execute(
                "DELETE FROM record_evidence WHERE subject_id=? AND observation_id=?",
                (subject_id, observation_id),
            )
            result["observations"] += connection.execute(
                "DELETE FROM observations WHERE subject_id=? AND observation_id=?",
                (subject_id, observation_id),
            ).rowcount
        result["normalized_events"] = connection.execute(
            """DELETE FROM normalized_events WHERE subject_id=? AND captured_at_ms < ?
               AND ingest_id NOT IN (SELECT ingest_id FROM observations WHERE subject_id=?)""",
            (subject_id, normalized_cutoff, subject_id),
        ).rowcount
        record_change(
            connection, configuration, "retention_apply", "retention_batch", "scheduled",
            run_id, subject_id=subject_id, commit=False, now=_stamp(now_ms),
        )
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise


def _selected_records(
    connection: sqlite3.Connection, subject_id: str, start_ms: int, end_ms: int,
) -> dict[str, list[str]]:
    specifications = {
        "raw_events": ("ingest_id", "COALESCE(captured_at_ms,received_at_ms)"),
        "normalized_events": ("normalized_event_id", "captured_at_ms"),
        "observations": ("observation_id", "captured_at_ms"),
        "places": ("place_id", "effective_from_ms"),
        "transitions": ("transition_id", "occurred_at_ms"),
        "visits": ("visit_id", "started_at_ms"),
        "trips": ("trip_id", "started_at_ms"),
        "coverage_gaps": ("gap_id", "started_at_ms"),
    }
    selected = {}
    for table, (identifier, timestamp) in specifications.items():
        selected[table] = [row[0] for row in connection.execute(
            f"SELECT {identifier} FROM {table} WHERE subject_id=? AND {timestamp} BETWEEN ? AND ? ORDER BY {identifier}",
            (subject_id, start_ms, end_ms),
        )]
    return selected


def _plan_counts(connection: sqlite3.Connection, subject_id: str, selected: dict[str, list[str]]) -> dict[str, int]:
    counts = {table: len(values) for table, values in selected.items()}
    raw = set(selected["raw_events"])
    counts["processing_jobs"] = sum(1 for row in connection.execute(
        "SELECT ingest_id FROM processing_jobs WHERE subject_id=?", (subject_id,),
    ) if row[0] in raw)
    counts["quarantine"] = sum(1 for row in connection.execute(
        "SELECT ingest_id FROM quarantine WHERE subject_id=?", (subject_id,),
    ) if row[0] in raw)
    record_ids = {item for table in ("transitions", "visits", "trips", "coverage_gaps") for item in selected[table]}
    observations = set(selected["observations"])
    counts["record_evidence"] = sum(1 for row in connection.execute(
        "SELECT record_id, observation_id FROM record_evidence WHERE subject_id=?", (subject_id,),
    ) if row[0] in record_ids or row[1] in observations)
    aggregates = record_ids | observations | set(selected["places"])
    counts["outbox_records"] = sum(1 for row in connection.execute(
        "SELECT aggregate_id FROM outbox_records WHERE subject_id=?", (subject_id,),
    ) if row[0] in aggregates)
    return counts


def plan_deletion(
    connection: sqlite3.Connection,
    configuration: Configuration,
    subject_id: str,
    start_ms: int,
    end_ms: int,
    now_ms: int,
    run_id: str,
) -> tuple[str, dict[str, int]]:
    if end_ms < start_ms or SAFE_CODE.fullmatch(run_id) is None:
        raise LifecycleError("deletion_request_invalid")
    if connection.execute("SELECT 1 FROM subjects WHERE subject_id=?", (subject_id,)).fetchone() is None:
        raise LifecycleError("subject_not_found")
    selected = _selected_records(connection, subject_id, start_ms, end_ms)
    counts = _plan_counts(connection, subject_id, selected)
    plan_id = deterministic_id("del", subject_id, str(start_ms), str(end_ms), str(now_ms))
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO deletion_plans VALUES (?, ?, ?, ?, ?, 'planned', ?, ?, NULL)",
            (plan_id, subject_id, start_ms, end_ms, canonical_json(counts).decode(), now_ms, now_ms + DAY_MS),
        )
        record_change(
            connection, configuration, "deletion_plan", plan_id, "owner_requested", run_id,
            subject_id=subject_id, commit=False, now=_stamp(now_ms),
        )
        connection.commit()
        return plan_id, counts
    except Exception:
        connection.rollback()
        raise


def apply_deletion(
    connection: sqlite3.Connection,
    configuration: Configuration,
    plan_id: str,
    now_ms: int,
    run_id: str,
) -> dict[str, int]:
    if SAFE_CODE.fullmatch(run_id) is None:
        raise LifecycleError("deletion_request_invalid")
    plan = connection.execute(
        "SELECT subject_id,start_ms,end_ms,expected_counts_json,status,expires_at_ms FROM deletion_plans WHERE plan_id=?",
        (plan_id,),
    ).fetchone()
    if plan is None or plan[4] != "planned":
        raise LifecycleError("deletion_plan_invalid")
    if plan[5] < now_ms:
        connection.execute("UPDATE deletion_plans SET status='expired' WHERE plan_id=?", (plan_id,))
        connection.commit()
        raise LifecycleError("deletion_plan_expired")
    subject_id = plan[0]
    selected = _selected_records(connection, subject_id, plan[1], plan[2])
    expected = json.loads(plan[3])
    if _plan_counts(connection, subject_id, selected) != expected:
        raise LifecycleError("deletion_plan_stale")
    record_types = {
        "observations": "observation", "places": "place", "transitions": "transition",
        "visits": "visit", "trips": "trip", "coverage_gaps": "coverage_gap",
    }
    tombstones = [(record_types[table], item) for table in record_types for item in selected[table]]
    try:
        connection.execute("BEGIN IMMEDIATE")
        aggregate_ids = {item for _kind, item in tombstones}
        sequences = [row[0] for row in connection.execute(
            "SELECT sequence, aggregate_id FROM outbox_records WHERE subject_id=?", (subject_id,),
        ) if row[1] in aggregate_ids]
        for sequence in sequences:
            connection.execute("DELETE FROM outbox_receipts WHERE sequence=?", (sequence,))
            connection.execute("DELETE FROM outbox_records WHERE sequence=?", (sequence,))
        raw_ids = set(selected["raw_events"])
        for table in ("quarantine", "processing_jobs"):
            for row in connection.execute(f"SELECT rowid, ingest_id FROM {table} WHERE subject_id=?", (subject_id,)).fetchall():
                if row[1] in raw_ids:
                    connection.execute(f"DELETE FROM {table} WHERE rowid=?", (row[0],))
        evidence_records = {item for table in ("transitions", "visits", "trips", "coverage_gaps") for item in selected[table]}
        observation_ids = set(selected["observations"])
        for row in connection.execute(
            "SELECT rowid, record_id, observation_id FROM record_evidence WHERE subject_id=?", (subject_id,),
        ).fetchall():
            if row[1] in evidence_records or row[2] in observation_ids:
                connection.execute("DELETE FROM record_evidence WHERE rowid=?", (row[0],))
        for table, identifier in (
            ("transitions", "transition_id"), ("visits", "visit_id"), ("trips", "trip_id"),
            ("coverage_gaps", "gap_id"), ("observations", "observation_id"),
            ("normalized_events", "normalized_event_id"), ("places", "place_id"),
        ):
            for item in selected[table]:
                connection.execute(f"DELETE FROM {table} WHERE subject_id=? AND {identifier}=?", (subject_id, item))
        for item in selected["raw_events"]:
            connection.execute("DELETE FROM raw_events WHERE subject_id=? AND ingest_id=?", (subject_id, item))
        for record_type, record_id in tombstones:
            event_id = deterministic_id("evt", "record.tombstoned", subject_id, record_type, record_id)
            _outbox(
                connection, subject_id=subject_id, event_id=event_id, aggregate_id=record_id,
                event_type="record.tombstoned", occurred_at_ms=now_ms, published_at_ms=now_ms,
                provenance=[], data={"record_type": record_type, "record_id": record_id},
            )
        connection.execute(
            "UPDATE deletion_plans SET status='applied', applied_at_ms=? WHERE plan_id=?",
            (now_ms, plan_id),
        )
        record_change(
            connection, configuration, "deletion_apply", plan_id, "owner_confirmed", run_id,
            subject_id=subject_id, commit=False, now=_stamp(now_ms),
        )
        connection.commit()
        return expected
    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise LifecycleError("deletion_dependency_active") from exc
    except Exception:
        connection.rollback()
        raise
