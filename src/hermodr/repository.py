"""Narrow, explicitly subject-scoped repository operations."""

from dataclasses import dataclass
import sqlite3


class NotFoundError(LookupError):
    """An object is absent from the caller's subject scope."""


@dataclass(frozen=True)
class Subject:
    subject_id: str
    status: str
    policy_ref: str


@dataclass(frozen=True)
class Device:
    subject_id: str
    device_id: str
    status: str


class Repository:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def add_subject(self, subject_id: str, policy_ref: str, enrolled_at_ms: int) -> Subject:
        self._connection.execute(
            "INSERT INTO subjects(subject_id, status, policy_ref, enrolled_at_ms) VALUES (?, 'active', ?, ?)",
            (subject_id, policy_ref, enrolled_at_ms),
        )
        self._connection.commit()
        return Subject(subject_id, "active", policy_ref)

    def get_subject(self, subject_id: str) -> Subject:
        row = self._connection.execute(
            "SELECT subject_id, status, policy_ref FROM subjects WHERE subject_id = ?", (subject_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("subject_not_found")
        return Subject(*row)

    def add_device(self, subject_id: str, device_id: str, enrolled_at_ms: int) -> Device:
        self._connection.execute(
            "INSERT INTO devices(subject_id, device_id, status, enrolled_at_ms) VALUES (?, ?, 'active', ?)",
            (subject_id, device_id, enrolled_at_ms),
        )
        self._connection.commit()
        return Device(subject_id, device_id, "active")

    def get_device(self, subject_id: str, device_id: str) -> Device:
        row = self._connection.execute(
            "SELECT subject_id, device_id, status FROM devices WHERE subject_id = ? AND device_id = ?",
            (subject_id, device_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("device_not_found")
        return Device(*row)

    def add_raw_event(
        self,
        *,
        subject_id: str,
        device_id: str,
        ingest_id: str,
        idempotency_key: str,
        source_digest: str,
        payload: bytes,
        received_at_ms: int,
        captured_at_ms: int | None,
        source_type: str,
    ) -> None:
        self._connection.execute(
            """INSERT INTO raw_events(
                subject_id, device_id, ingest_id, idempotency_key, source_digest,
                payload, received_at_ms, captured_at_ms, source_type, disposition, synthetic
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'accepted', 0)""",
            (subject_id, device_id, ingest_id, idempotency_key, source_digest, payload, received_at_ms, captured_at_ms, source_type),
        )
        self._connection.commit()

    def raw_event_ids(self, subject_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            "SELECT ingest_id FROM raw_events WHERE subject_id = ? ORDER BY received_at_ms, ingest_id", (subject_id,)
        )
        return tuple(row[0] for row in rows)
