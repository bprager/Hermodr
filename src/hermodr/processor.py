"""Transactional, subject-partitioned durable processing worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import sqlite3
from threading import Event
from typing import Callable

from .clock import unix_milliseconds
from .config import Configuration
from .database import connect
from .identifiers import canonical_json, deterministic_id


ALGORITHM = "owntracks-normalizer-v1"
SCHEMA_VERSION = "1"


class ProcessingError(RuntimeError):
    """A bounded processor failure safe for operator output."""


class PermanentProcessingError(ProcessingError):
    """Evidence cannot be normalized by this algorithm version."""


@dataclass(frozen=True)
class ClaimedJob:
    subject_id: str
    job_id: str
    ingest_id: str
    attempts: int
    lease_owner: str


@dataclass(frozen=True)
class ProcessResult:
    job_id: str
    state: str
    normalized_event_id: str | None = None
    observation_id: str | None = None


def heartbeat(configuration: Configuration, now_ms: int | None = None) -> None:
    stamp = now_ms if now_ms is not None else unix_milliseconds(datetime.now(timezone.utc))
    connection = connect(configuration)
    try:
        connection.execute(
            "INSERT INTO service_heartbeats VALUES ('processor', ?, 'healthy') "
            "ON CONFLICT(service) DO UPDATE SET last_success_ms=excluded.last_success_ms, "
            "status=excluded.status",
            (stamp,),
        )
        connection.commit()
    finally:
        connection.close()


def reclaim_expired(connection: sqlite3.Connection, now_ms: int) -> int:
    cursor = connection.execute(
        """UPDATE processing_jobs
           SET state = 'pending', lease_owner = NULL, lease_expires_ms = NULL,
               next_attempt_ms = ?, updated_at_ms = ?, error_code = 'lease_expired'
           WHERE state = 'processing' AND lease_expires_ms <= ?""",
        (now_ms, now_ms, now_ms),
    )
    return cursor.rowcount


def claim_next(
    connection: sqlite3.Connection,
    owner: str,
    now_ms: int,
    lease_ms: int,
) -> ClaimedJob | None:
    if not owner or len(owner) > 128:
        raise ProcessingError("lease_owner_invalid")
    try:
        connection.execute("BEGIN IMMEDIATE")
        reclaim_expired(connection, now_ms)
        row = connection.execute(
            """SELECT j.subject_id, j.job_id, j.ingest_id, j.attempts
               FROM processing_jobs j
               JOIN raw_events r
                 ON r.subject_id = j.subject_id AND r.ingest_id = j.ingest_id
               WHERE j.state = 'pending' AND j.next_attempt_ms <= ?
               ORDER BY j.subject_id, COALESCE(r.captured_at_ms, r.received_at_ms),
                        r.received_at_ms, j.job_id
               LIMIT 1""",
            (now_ms,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        changed = connection.execute(
            """UPDATE processing_jobs
               SET state = 'processing', attempts = attempts + 1, lease_owner = ?,
                   lease_expires_ms = ?, updated_at_ms = ?, error_code = NULL
               WHERE subject_id = ? AND job_id = ? AND state = 'pending'""",
            (owner, now_ms + lease_ms, now_ms, row[0], row[1]),
        ).rowcount
        if changed != 1:
            connection.rollback()
            return None
        connection.commit()
        return ClaimedJob(row[0], row[1], row[2], row[3] + 1, owner)
    except sqlite3.Error:
        connection.rollback()
        raise


def _utc(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _number(payload: dict[str, object], name: str) -> float | None:
    value = payload.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PermanentProcessingError("source_contract_invalid")
    return float(value)


def _distance_m(first_lat: float, first_lon: float, second_lat: float, second_lon: float) -> float:
    radius = 6_371_008.8
    lat1, lat2 = math.radians(first_lat), math.radians(second_lat)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second_lon - first_lon)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def _quality_flags(
    connection: sqlite3.Connection,
    subject_id: str,
    captured_at_ms: int,
    received_at_ms: int,
    latitude: float,
    longitude: float,
    accuracy: float | None,
    configuration: Configuration,
) -> tuple[str, ...]:
    flags: set[str] = set()
    if accuracy is None:
        flags.add("missing_accuracy")
    elif accuracy > configuration.poor_accuracy_m:
        flags.add("poor_accuracy")
    if received_at_ms - captured_at_ms > configuration.late_after_ms:
        flags.add("late")
    newest = connection.execute(
        "SELECT MAX(captured_at_ms) FROM observations WHERE subject_id = ?", (subject_id,)
    ).fetchone()[0]
    if newest is not None and newest > captured_at_ms:
        flags.add("out_of_order")
    previous = connection.execute(
        """SELECT latitude, longitude, captured_at_ms FROM observations
           WHERE subject_id = ? AND captured_at_ms < ?
           ORDER BY captured_at_ms DESC, observation_id DESC LIMIT 1""",
        (subject_id, captured_at_ms),
    ).fetchone()
    if previous is not None:
        elapsed = (captured_at_ms - previous[2]) / 1000
        speed = _distance_m(previous[0], previous[1], latitude, longitude) / elapsed if elapsed > 0 else 0
        if speed > configuration.implausible_speed_mps:
            flags.add("implausible_speed")
    return tuple(sorted(flags))


def _outbox(
    connection: sqlite3.Connection,
    *,
    subject_id: str,
    event_id: str,
    aggregate_id: str,
    event_type: str,
    occurred_at_ms: int,
    published_at_ms: int,
    provenance: list[str],
    data: dict[str, object],
) -> None:
    sequence = int(connection.execute(
        """SELECT MAX(value) + 1 FROM (
               SELECT COALESCE(MAX(sequence), 0) AS value FROM outbox_records
               UNION ALL SELECT COALESCE(MAX(last_sequence), 0) FROM outbox_consumers
               UNION ALL SELECT COALESCE((SELECT seq FROM sqlite_sequence WHERE name='outbox_records'), 0)
           )"""
    ).fetchone()[0])
    envelope = {
        "event_id": event_id, "sequence": sequence, "event_type": event_type,
        "schema_version": SCHEMA_VERSION, "occurred_at": _utc(occurred_at_ms),
        "published_at": _utc(published_at_ms), "subject_id": subject_id,
        "privacy_class": "restricted", "provenance": provenance, "data": data,
    }
    connection.execute(
        """INSERT OR IGNORE INTO outbox_records(
               sequence, subject_id, event_id, aggregate_id, aggregate_version,
               schema_version, event_type, privacy_class, payload_json, created_at_ms
           ) VALUES (?, ?, ?, ?, 1, ?, ?, 'restricted', ?, ?)""",
        (sequence, subject_id, event_id, aggregate_id, SCHEMA_VERSION, event_type,
         canonical_json(envelope).decode(), published_at_ms),
    )


def normalize_claimed(
    connection: sqlite3.Connection,
    configuration: Configuration,
    job: ClaimedJob,
    now_ms: int,
    before_commit: Callable[[], None] | None = None,
) -> ProcessResult:
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT state, lease_owner FROM processing_jobs WHERE subject_id = ? AND job_id = ?",
            (job.subject_id, job.job_id),
        ).fetchone()
        if current is None or current[0] != "processing" or current[1] != job.lease_owner:
            raise ProcessingError("lease_lost")
        row = connection.execute(
            """SELECT device_id, payload, received_at_ms, captured_at_ms, source_type,
                      source_digest, disposition
               FROM raw_events WHERE subject_id = ? AND ingest_id = ?""",
            (job.subject_id, job.ingest_id),
        ).fetchone()
        if row is None or row[6] != "accepted":
            raise PermanentProcessingError("source_unavailable")
        try:
            payload = json.loads(bytes(row[1]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise PermanentProcessingError("source_contract_invalid") from exc
        if not isinstance(payload, dict) or payload.get("_type") != row[4]:
            raise PermanentProcessingError("source_contract_invalid")
        if row[3] is None and row[4] != "status":
            raise PermanentProcessingError("source_contract_invalid")
        captured_at_ms = int(row[3]) if row[3] is not None else int(row[2])
        normalized_id = deterministic_id("nrm", job.subject_id, job.ingest_id, ALGORITHM)
        normalized = {
            "normalized_event_id": normalized_id, "schema_version": SCHEMA_VERSION,
            "subject_id": job.subject_id, "device_id": row[0], "source_type": row[4],
            "captured_at": _utc(captured_at_ms), "received_at": _utc(row[2]),
            "processed_at": _utc(now_ms), "ingest_id": job.ingest_id,
            "source_digest": row[5], "algorithm": ALGORITHM,
            "algorithm_config_version": configuration.fingerprint, "privacy_class": "restricted",
        }
        if row[3] is None:
            normalized["captured_at_source"] = "receipt_fallback"
        connection.execute(
            "INSERT OR IGNORE INTO normalized_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job.subject_id, normalized_id, job.ingest_id, row[0], row[4], captured_at_ms,
             row[2], now_ms, SCHEMA_VERSION, ALGORITHM, configuration.fingerprint,
             row[5], canonical_json(normalized).decode()),
        )
        observation_id: str | None = None
        if row[4] in {"location", "transition", "waypoint"}:
            latitude = _number(payload, "lat")
            longitude = _number(payload, "lon")
            if latitude is None or longitude is None or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise PermanentProcessingError("source_contract_invalid")
            accuracy = _number(payload, "acc")
            if accuracy is not None and accuracy < 0:
                raise PermanentProcessingError("source_contract_invalid")
            flags = _quality_flags(connection, job.subject_id, captured_at_ms, row[2], latitude,
                                   longitude, accuracy, configuration)
            if row[4] == "transition":
                flags = tuple(sorted(set(flags) | {"source_transition_unconfirmed"}))
            observation_id = deterministic_id("obs", job.subject_id, job.ingest_id, ALGORITHM)
            observation = {
                "observation_id": observation_id, "schema_version": SCHEMA_VERSION,
                "subject_id": job.subject_id, "device_id": row[0], "source": "owntracks",
                "source_type": row[4], "captured_at": _utc(captured_at_ms),
                "received_at": _utc(row[2]), "processed_at": _utc(now_ms),
                "latitude": latitude, "longitude": longitude,
                "horizontal_accuracy_m": accuracy, "quality_flags": list(flags),
                "ingest_id": job.ingest_id, "source_digest": row[5], "algorithm": ALGORITHM,
                "algorithm_config_version": configuration.fingerprint, "privacy_class": "restricted",
            }
            connection.execute(
                """INSERT OR IGNORE INTO observations(
                       subject_id, observation_id, device_id, ingest_id, schema_version,
                       algorithm_version, captured_at_ms, received_at_ms, latitude, longitude,
                       horizontal_accuracy_m, quality_flags_json, source_digest, processed_at_ms,
                       source_type, altitude_m, velocity_mps, heading_deg, battery_percent,
                       trigger, connectivity, algorithm_config_version
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job.subject_id, observation_id, row[0], job.ingest_id, SCHEMA_VERSION,
                 ALGORITHM, captured_at_ms, row[2], latitude, longitude, accuracy,
                 canonical_json(list(flags)).decode(), row[5], now_ms, row[4],
                 _number(payload, "alt"), _number(payload, "vel"), _number(payload, "cog"),
                 _number(payload, "batt"), payload.get("t") if isinstance(payload.get("t"), str) else None,
                 payload.get("conn") if isinstance(payload.get("conn"), str) else None,
                 configuration.fingerprint),
            )
            event_id = deterministic_id("evt", "observation.recorded", observation_id)
            _outbox(connection, subject_id=job.subject_id, event_id=event_id,
                    aggregate_id=observation_id, event_type="observation.recorded",
                    occurred_at_ms=captured_at_ms, published_at_ms=now_ms,
                    provenance=[job.ingest_id], data=observation)
            if row[4] == "transition" and payload.get("event") in {"enter", "leave"}:
                transition_type = "arrival" if payload["event"] == "enter" else "departure"
                transition_id = deterministic_id(
                    "trn", job.subject_id, "source", transition_type, observation_id,
                )
                connection.execute(
                    """INSERT OR IGNORE INTO transitions(
                           subject_id,transition_id,transition_type,occurred_at_ms,confidence,status,
                           superseded_by,place_id,processed_at_ms,source_digest,algorithm_version,
                           algorithm_config_version)
                       VALUES (?, ?, ?, ?, 0.5, 'provisional', NULL, NULL, ?, ?,
                               'owntracks-transition-v1', ?)""",
                    (job.subject_id, transition_id, transition_type, captured_at_ms, now_ms,
                     row[5], configuration.fingerprint),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO record_evidence VALUES (?, 'transition', ?, ?)",
                    (job.subject_id, transition_id, observation_id),
                )
                transition = {
                    "transition_id": transition_id, "schema_version": "1",
                    "subject_id": job.subject_id, "transition_type": transition_type,
                    "occurred_at": _utc(captured_at_ms), "processed_at": _utc(now_ms),
                    "confidence": 0.5, "evidence_ids": [observation_id],
                    "source_digest": row[5], "algorithm": "owntracks-transition-v1",
                    "algorithm_config_version": configuration.fingerprint,
                    "status": "provisional", "superseded_by": None,
                    "privacy_class": "restricted",
                }
                _outbox(
                    connection, subject_id=job.subject_id,
                    event_id=deterministic_id("evt", "transition.recorded", transition_id),
                    aggregate_id=transition_id, event_type="transition.recorded",
                    occurred_at_ms=captured_at_ms, published_at_ms=now_ms,
                    provenance=[observation_id], data=transition,
                )
            if row[4] == "waypoint":
                radius = _number(payload, "rad")
                if radius is not None and radius > 0:
                    from .derivation import register_place
                    register_place(
                        connection, configuration, subject_id=job.subject_id,
                        latitude=latitude, longitude=longitude, radius_m=radius,
                        sensitivity="restricted", approval_state="proposed",
                        effective_from_ms=captured_at_ms, now_ms=now_ms,
                        label=payload.get("desc") if isinstance(payload.get("desc"), str) else None,
                        commit=False,
                    )
            from .derivation import schedule_recompute
            schedule_recompute(
                connection, configuration, job.subject_id,
                max(0, captured_at_ms - max(configuration.visit_dwell_ms, configuration.coverage_gap_ms)),
                captured_at_ms + max(configuration.visit_dwell_ms, configuration.coverage_gap_ms),
                "late_data" if "late" in flags or "out_of_order" in flags else "new_data", now_ms,
            )
        changed = connection.execute(
            """UPDATE processing_jobs
               SET state = 'processed', lease_owner = NULL, lease_expires_ms = NULL,
                   updated_at_ms = ?, error_code = NULL
               WHERE subject_id = ? AND job_id = ? AND state = 'processing' AND lease_owner = ?""",
            (now_ms, job.subject_id, job.job_id, job.lease_owner),
        ).rowcount
        if changed != 1:
            raise ProcessingError("lease_lost")
        if before_commit is not None:
            before_commit()
        connection.commit()
        return ProcessResult(job.job_id, "processed", normalized_id, observation_id)
    except Exception:
        connection.rollback()
        raise


def _retry_delay(configuration: Configuration, job: ClaimedJob) -> int:
    exponential = min(configuration.processor_max_backoff_ms,
                      configuration.processor_base_backoff_ms * 2 ** max(0, job.attempts - 1))
    digest = hashlib.sha256(f"{job.job_id}:{job.attempts}".encode()).digest()
    jitter = int.from_bytes(digest[:2], "big") % max(1, exponential // 4 + 1)
    return min(configuration.processor_max_backoff_ms, exponential + jitter)


def fail_claimed(
    connection: sqlite3.Connection,
    configuration: Configuration,
    job: ClaimedJob,
    now_ms: int,
    error_code: str,
    *,
    permanent: bool = False,
) -> str:
    terminal = permanent or job.attempts >= configuration.processor_max_attempts
    state = "failed" if terminal else "pending"
    next_attempt = now_ms if terminal else now_ms + _retry_delay(configuration, job)
    changed = connection.execute(
        """UPDATE processing_jobs SET state = ?, next_attempt_ms = ?, lease_owner = NULL,
                  lease_expires_ms = NULL, error_code = ?, updated_at_ms = ?
           WHERE subject_id = ? AND job_id = ? AND state = 'processing' AND lease_owner = ?""",
        (state, next_attempt, error_code, now_ms, job.subject_id, job.job_id, job.lease_owner),
    ).rowcount
    connection.commit()
    if changed != 1:
        raise ProcessingError("lease_lost")
    return state


def process_one(
    configuration: Configuration,
    owner: str,
    now_ms: int | None = None,
    before_commit: Callable[[], None] | None = None,
) -> ProcessResult | None:
    stamp = now_ms if now_ms is not None else unix_milliseconds(datetime.now(timezone.utc))
    connection = connect(configuration)
    try:
        job = claim_next(connection, owner, stamp, configuration.processor_lease_ms)
        if job is None:
            return None
        try:
            result = normalize_claimed(connection, configuration, job, stamp, before_commit)
        except PermanentProcessingError as exc:
            state = fail_claimed(connection, configuration, job, stamp, str(exc), permanent=True)
            return ProcessResult(job.job_id, state)
        except sqlite3.Error:
            state = fail_claimed(connection, configuration, job, stamp, "database_error")
            return ProcessResult(job.job_id, state)
        if result.observation_id is not None:
            from .derivation import DerivationError, reprocess_subject
            try:
                reprocess_subject(connection, configuration, job.subject_id, stamp)
            except (DerivationError, sqlite3.Error):
                # The normalized job is already durable; its pending window is the retry contract.
                pass
        return result
    finally:
        connection.close()


def process_recompute(configuration: Configuration, now_ms: int | None = None) -> bool:
    stamp = now_ms if now_ms is not None else unix_milliseconds(datetime.now(timezone.utc))
    connection = connect(configuration)
    try:
        row = connection.execute(
            "SELECT subject_id FROM recompute_windows WHERE state='pending' ORDER BY start_ms, subject_id LIMIT 1"
        ).fetchone()
        if row is None:
            return False
        from .derivation import reprocess_subject
        reprocess_subject(connection, configuration, row[0], stamp)
        return True
    finally:
        connection.close()


def serve(configuration: Configuration, stop: Event, interval_seconds: float = 1) -> None:
    owner = "processor-main"
    while not stop.is_set():
        heartbeat(configuration)
        result = process_one(configuration, owner)
        recomputed = process_recompute(configuration)
        if result is None and not recomputed:
            stop.wait(interval_seconds)
