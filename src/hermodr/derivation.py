"""Deterministic, uncertainty-preserving event-time derivation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import sqlite3

from .config import Configuration
from .identifiers import canonical_json, deterministic_id, source_digest
from .processor import _distance_m, _outbox, _utc


ALGORITHM = "event-time-deriver-v1"
PLACE_ALGORITHM = "place-registry-v1"


class DerivationError(RuntimeError):
    """A bounded derivation or reprocessing error."""


@dataclass(frozen=True)
class DerivationSummary:
    transitions: int
    visits: int
    trips: int
    gaps: int


@dataclass(frozen=True)
class Evidence:
    observation_id: str
    captured_at_ms: int
    latitude: float
    longitude: float
    accuracy_m: float
    source_digest: str
    place_id: str | None


def register_place(
    connection: sqlite3.Connection,
    configuration: Configuration,
    *,
    subject_id: str,
    latitude: float,
    longitude: float,
    radius_m: float,
    sensitivity: str,
    approval_state: str,
    effective_from_ms: int,
    now_ms: int,
    label: str | None = None,
    commit: bool = True,
) -> str:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and radius_m > 0):
        raise DerivationError("place_geometry_invalid")
    if sensitivity not in {"restricted", "private"} or approval_state not in {"proposed", "approved", "rejected"}:
        raise DerivationError("place_policy_invalid")
    if label is not None and (not label or len(label) > 128):
        raise DerivationError("place_label_invalid")
    place_id = deterministic_id(
        "plc", subject_id, f"{latitude:.7f}", f"{longitude:.7f}", f"{radius_m:.3f}", label or "",
    )
    material = {
        "latitude": latitude, "longitude": longitude, "radius_m": radius_m,
        "sensitivity": sensitivity, "approval_state": approval_state,
        "effective_from_ms": effective_from_ms, "label": label,
    }
    version = int(connection.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM places WHERE subject_id=? AND place_id=?",
        (subject_id, place_id),
    ).fetchone()[0])
    digest = source_digest(material)
    connection.execute(
        """INSERT INTO places(
               subject_id, place_id, version, latitude, longitude, radius_m, sensitivity,
               approval_state, effective_from_ms, effective_until_ms, label, processed_at_ms,
               source_digest, algorithm_version, algorithm_config_version
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
        (subject_id, place_id, version, latitude, longitude, radius_m, sensitivity,
         approval_state, effective_from_ms, label, now_ms, digest,
         PLACE_ALGORITHM, configuration.fingerprint),
    )
    data = {
        "place_id": place_id, "schema_version": "1", "subject_id": subject_id,
        "version": version, "latitude": latitude, "longitude": longitude,
        "radius_m": radius_m, "sensitivity": sensitivity, "approval_state": approval_state,
        "effective_from": _utc(effective_from_ms), "effective_until": None,
        "processed_at": _utc(now_ms), "source_digest": digest,
        "algorithm": PLACE_ALGORITHM, "algorithm_config_version": configuration.fingerprint,
        "privacy_class": "restricted",
    }
    _outbox(
        connection, subject_id=subject_id,
        event_id=deterministic_id("evt", "place.recorded", place_id, str(version)),
        aggregate_id=place_id, event_type="place.recorded", occurred_at_ms=effective_from_ms,
        published_at_ms=now_ms, provenance=[], data=data,
    )
    if commit:
        connection.commit()
    return place_id


def schedule_recompute(
    connection: sqlite3.Connection,
    configuration: Configuration,
    subject_id: str,
    start_ms: int,
    end_ms: int,
    cause: str,
    now_ms: int,
) -> str:
    if cause not in {"new_data", "late_data", "operator", "algorithm_change"} or end_ms < start_ms:
        raise DerivationError("recompute_request_invalid")
    key = hashlib.sha256(canonical_json([subject_id, ALGORITHM, configuration.fingerprint])).hexdigest()
    existing = connection.execute(
        "SELECT window_id, start_ms, end_ms FROM recompute_windows WHERE subject_id=? AND coalescing_key=?",
        (subject_id, key),
    ).fetchone()
    if existing is None:
        window_id = deterministic_id("win", subject_id, key)
        connection.execute(
            """INSERT INTO recompute_windows(
                   subject_id, window_id, start_ms, end_ms, cause, algorithm_version,
                   state, coalescing_key, created_at_ms, updated_at_ms
               ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (subject_id, window_id, start_ms, end_ms, cause, ALGORITHM, key, now_ms, now_ms),
        )
    else:
        window_id = existing[0]
        connection.execute(
            """UPDATE recompute_windows SET start_ms=?, end_ms=?, cause=?, state='pending',
                      updated_at_ms=? WHERE subject_id=? AND window_id=?""",
            (min(start_ms, existing[1]), max(end_ms, existing[2]), cause, now_ms, subject_id, window_id),
        )
    return window_id


def _place_for(connection: sqlite3.Connection, subject_id: str, item: sqlite3.Row) -> str | None:
    matches: list[tuple[float, str]] = []
    accuracy = float(item[4] or 0)
    for place in connection.execute(
        """SELECT p.place_id, p.latitude, p.longitude, p.radius_m FROM places AS p
           WHERE p.subject_id=? AND p.approval_state='approved' AND p.effective_from_ms <= ?
             AND (effective_until_ms IS NULL OR effective_until_ms > ?)
             AND p.version = (
                 SELECT MAX(v.version) FROM places AS v
                 WHERE v.subject_id=p.subject_id AND v.place_id=p.place_id
                   AND v.effective_from_ms <= ?
                   AND (v.effective_until_ms IS NULL OR v.effective_until_ms > ?)
             )
           ORDER BY p.place_id""",
        (subject_id, item[1], item[1], item[1], item[1]),
    ):
        distance = _distance_m(item[2], item[3], place[1], place[2])
        if distance <= place[3] + accuracy:
            matches.append((distance / place[3], place[0]))
    matches.sort()
    if len(matches) > 1 and math.isclose(matches[0][0], matches[1][0], rel_tol=0.05, abs_tol=0.05):
        return None
    return None if not matches else matches[0][1]


def _evidence(connection: sqlite3.Connection, subject_id: str) -> list[Evidence]:
    values = []
    rows = connection.execute(
        """SELECT observation_id, captured_at_ms, latitude, longitude,
                  COALESCE(horizontal_accuracy_m, 0), source_digest
           FROM observations WHERE subject_id=?
           ORDER BY captured_at_ms, observation_id""",
        (subject_id,),
    ).fetchall()
    for row in rows:
        values.append(Evidence(row[0], row[1], row[2], row[3], row[4], row[5], _place_for(connection, subject_id, row)))
    return values


def _supersede_missing(
    connection: sqlite3.Connection,
    table: str,
    identifier: str,
    subject_id: str,
    active_ids: set[str],
    now_ms: int,
) -> None:
    rows = connection.execute(
        f"SELECT {identifier} FROM {table} WHERE subject_id=? AND status != 'superseded' AND algorithm_version=?",
        (subject_id, ALGORITHM),
    ).fetchall()
    for row in rows:
        if row[0] not in active_ids:
            connection.execute(
                f"UPDATE {table} SET status='superseded', superseded_by=NULL WHERE subject_id=? AND {identifier}=?",
                (subject_id, row[0]),
            )
            record_type = table.removesuffix("s")
            _outbox(
                connection, subject_id=subject_id,
                event_id=deterministic_id("evt", "record.superseded", record_type, row[0]),
                aggregate_id=row[0], event_type="record.superseded", occurred_at_ms=now_ms,
                published_at_ms=now_ms, provenance=[],
                data={"record_type": record_type, "record_id": row[0], "superseded_by": None},
            )


def _record_evidence(
    connection: sqlite3.Connection,
    subject_id: str,
    record_type: str,
    record_id: str,
    evidence: list[Evidence],
) -> None:
    for item in evidence:
        connection.execute(
            "INSERT OR IGNORE INTO record_evidence VALUES (?, ?, ?, ?)",
            (subject_id, record_type, record_id, item.observation_id),
        )


def _emit_derived(
    connection: sqlite3.Connection,
    subject_id: str,
    record_id: str,
    event_type: str,
    occurred_at_ms: int,
    now_ms: int,
    evidence: list[Evidence],
    data: dict[str, object],
) -> None:
    _outbox(
        connection, subject_id=subject_id,
        event_id=deterministic_id("evt", event_type, record_id), aggregate_id=record_id,
        event_type=event_type, occurred_at_ms=occurred_at_ms, published_at_ms=now_ms,
        provenance=[item.observation_id for item in evidence], data=data,
    )


def derive_subject(
    connection: sqlite3.Connection,
    configuration: Configuration,
    subject_id: str,
    now_ms: int,
) -> DerivationSummary:
    evidence = _evidence(connection, subject_id)
    transition_ids: set[str] = set()
    visit_ids: set[str] = set()
    trip_ids: set[str] = set()
    gap_ids: set[str] = set()
    config_version = configuration.fingerprint

    for previous, current in zip(evidence, evidence[1:]):
        if current.captured_at_ms - previous.captured_at_ms > configuration.coverage_gap_ms:
            gap_evidence = [previous, current]
            gap_id = deterministic_id("gap", subject_id, previous.observation_id, current.observation_id, ALGORITHM, config_version)
            gap_ids.add(gap_id)
            digests = [item.source_digest for item in gap_evidence]
            connection.execute(
                """INSERT OR IGNORE INTO coverage_gaps(
                       subject_id, gap_id, started_at_ms, ended_at_ms, reason, status,
                       superseded_by, processed_at_ms, source_digests_json,
                       algorithm_version, algorithm_config_version
                   ) VALUES (?, ?, ?, ?, 'silence', 'confirmed', NULL, ?, ?, ?, ?)""",
                (subject_id, gap_id, previous.captured_at_ms, current.captured_at_ms,
                 now_ms, canonical_json(digests).decode(), ALGORITHM, config_version),
            )
            _record_evidence(connection, subject_id, "coverage_gap", gap_id, gap_evidence)
            data = {
                "gap_id": gap_id, "schema_version": "1", "subject_id": subject_id,
                "started_at": _utc(previous.captured_at_ms), "ended_at": _utc(current.captured_at_ms),
                "processed_at": _utc(now_ms), "reason": "silence",
                "evidence_ids": [item.observation_id for item in gap_evidence],
                "source_digests": digests, "algorithm": ALGORITHM,
                "algorithm_config_version": config_version, "status": "confirmed",
                "superseded_by": None, "privacy_class": "restricted",
            }
            _emit_derived(connection, subject_id, gap_id, "coverage_gap.recorded",
                          current.captured_at_ms, now_ms, gap_evidence, data)

    runs: list[list[Evidence]] = []
    current_run: list[Evidence] = []
    for item in evidence:
        if item.place_id is None:
            if current_run:
                runs.append(current_run)
                current_run = []
            continue
        if current_run and current_run[-1].place_id == item.place_id:
            current_run.append(item)
        else:
            if current_run:
                runs.append(current_run)
            current_run = [item]
    if current_run:
        runs.append(current_run)
    for index, run in enumerate(runs):
        duration = run[-1].captured_at_ms - run[0].captured_at_ms
        complete = index < len(runs) - 1
        status = "confirmed" if complete and duration >= configuration.visit_dwell_ms else "provisional"
        ended = run[-1].captured_at_ms if complete else None
        visit_id = deterministic_id("vst", subject_id, run[0].observation_id, run[-1].observation_id,
                                    run[0].place_id or "", ALGORITHM, config_version)
        visit_ids.add(visit_id)
        digests = [item.source_digest for item in run]
        connection.execute(
            """INSERT OR IGNORE INTO visits(
                   subject_id, visit_id, place_id, started_at_ms, ended_at_ms, confidence,
                   status, superseded_by, processed_at_ms, source_digests_json,
                   algorithm_version, algorithm_config_version
               ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)""",
            (subject_id, visit_id, run[0].place_id, run[0].captured_at_ms, ended,
             1.0 if status == "confirmed" else 0.5, status, now_ms,
             canonical_json(digests).decode(), ALGORITHM, config_version),
        )
        _record_evidence(connection, subject_id, "visit", visit_id, run)
        data = {
            "visit_id": visit_id, "schema_version": "1", "subject_id": subject_id,
            "place_id": run[0].place_id, "started_at": _utc(run[0].captured_at_ms),
            "ended_at": None if ended is None else _utc(ended), "processed_at": _utc(now_ms),
            "confidence": 1.0 if status == "confirmed" else 0.5,
            "evidence_ids": [item.observation_id for item in run], "source_digests": digests,
            "algorithm": ALGORITHM, "algorithm_config_version": config_version,
            "status": status, "superseded_by": None, "privacy_class": "restricted",
        }
        _emit_derived(connection, subject_id, visit_id, "visit.recorded",
                      run[0].captured_at_ms, now_ms, run, data)

    for previous, current in zip(runs, runs[1:]):
        if previous[-1].place_id == current[0].place_id:
            continue
        for transition_type, item, place_id in (
            ("departure", previous[-1], previous[-1].place_id),
            ("arrival", current[0], current[0].place_id),
        ):
            transition_id = deterministic_id("trn", subject_id, transition_type, item.observation_id,
                                             place_id or "", ALGORITHM, config_version)
            transition_ids.add(transition_id)
            connection.execute(
                """INSERT OR IGNORE INTO transitions(
                       subject_id, transition_id, transition_type, occurred_at_ms, confidence,
                       status, superseded_by, place_id, processed_at_ms, source_digest,
                       algorithm_version, algorithm_config_version
                   ) VALUES (?, ?, ?, ?, 1.0, 'confirmed', NULL, ?, ?, ?, ?, ?)""",
                (subject_id, transition_id, transition_type, item.captured_at_ms, place_id,
                 now_ms, item.source_digest, ALGORITHM, config_version),
            )
            _record_evidence(connection, subject_id, "transition", transition_id, [item])
            data = {
                "transition_id": transition_id, "schema_version": "1", "subject_id": subject_id,
                "transition_type": transition_type, "occurred_at": _utc(item.captured_at_ms),
                "processed_at": _utc(now_ms), "confidence": 1.0,
                "evidence_ids": [item.observation_id], "source_digest": item.source_digest,
                "algorithm": ALGORITHM, "algorithm_config_version": config_version,
                "status": "confirmed", "superseded_by": None, "privacy_class": "restricted",
            }
            _emit_derived(connection, subject_id, transition_id, "transition.recorded",
                          item.captured_at_ms, now_ms, [item], data)
            connection.execute(
                """UPDATE transitions SET status='superseded', superseded_by=?
                   WHERE subject_id=? AND algorithm_version='owntracks-transition-v1'
                     AND transition_type=? AND status='provisional'
                     AND ABS(occurred_at_ms - ?) <= 300000""",
                (transition_id, subject_id, transition_type, item.captured_at_ms),
            )
        trip_evidence = [item for item in evidence
                         if previous[-1].captured_at_ms <= item.captured_at_ms <= current[0].captured_at_ms]
        trip_id = deterministic_id("trip", subject_id, previous[-1].observation_id,
                                   current[0].observation_id, ALGORITHM, config_version)
        trip_ids.add(trip_id)
        digests = [item.source_digest for item in trip_evidence]
        connection.execute(
            """INSERT OR IGNORE INTO trips(
                   subject_id, trip_id, started_at_ms, ended_at_ms, confidence, status,
                   superseded_by, processed_at_ms, source_digests_json,
                   algorithm_version, algorithm_config_version
               ) VALUES (?, ?, ?, ?, 1.0, 'confirmed', NULL, ?, ?, ?, ?)""",
            (subject_id, trip_id, previous[-1].captured_at_ms, current[0].captured_at_ms,
             now_ms, canonical_json(digests).decode(), ALGORITHM, config_version),
        )
        _record_evidence(connection, subject_id, "trip", trip_id, trip_evidence)
        data = {
            "trip_id": trip_id, "schema_version": "1", "subject_id": subject_id,
            "started_at": _utc(previous[-1].captured_at_ms), "ended_at": _utc(current[0].captured_at_ms),
            "processed_at": _utc(now_ms), "confidence": 1.0,
            "evidence_ids": [item.observation_id for item in trip_evidence],
            "source_digests": digests, "algorithm": ALGORITHM,
            "algorithm_config_version": config_version, "status": "confirmed",
            "superseded_by": None, "privacy_class": "restricted",
        }
        _emit_derived(connection, subject_id, trip_id, "trip.recorded",
                      current[0].captured_at_ms, now_ms, trip_evidence, data)

    for table, identifier, active in (
        ("transitions", "transition_id", transition_ids), ("visits", "visit_id", visit_ids),
        ("trips", "trip_id", trip_ids), ("coverage_gaps", "gap_id", gap_ids),
    ):
        _supersede_missing(connection, table, identifier, subject_id, active, now_ms)
    return DerivationSummary(len(transition_ids), len(visit_ids), len(trip_ids), len(gap_ids))


def reprocess_subject(
    connection: sqlite3.Connection,
    configuration: Configuration,
    subject_id: str,
    now_ms: int,
) -> DerivationSummary:
    if connection.execute("SELECT 1 FROM subjects WHERE subject_id=?", (subject_id,)).fetchone() is None:
        raise DerivationError("subject_not_found")
    try:
        connection.execute("BEGIN IMMEDIATE")
        summary = derive_subject(connection, configuration, subject_id, now_ms)
        connection.execute(
            "UPDATE recompute_windows SET state='processed', updated_at_ms=? WHERE subject_id=? AND state IN ('pending','processing')",
            (now_ms, subject_id),
        )
        connection.commit()
        return summary
    except Exception:
        connection.rollback()
        raise


def preview_subject(
    connection: sqlite3.Connection,
    configuration: Configuration,
    subject_id: str,
    now_ms: int,
) -> DerivationSummary:
    connection.execute("SAVEPOINT derivation_preview")
    try:
        summary = derive_subject(connection, configuration, subject_id, now_ms)
        connection.execute("ROLLBACK TO derivation_preview")
        connection.execute("RELEASE derivation_preview")
        return summary
    except Exception:
        connection.execute("ROLLBACK TO derivation_preview")
        connection.execute("RELEASE derivation_preview")
        raise
