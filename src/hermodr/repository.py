"""Narrow, explicitly subject-scoped repository operations."""

from dataclasses import dataclass
import sqlite3
from typing import Callable


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
    source_tid: str | None = None


@dataclass(frozen=True)
class Credential:
    subject_id: str
    device_id: str
    key_id: str
    secret_ref: str


@dataclass(frozen=True)
class PersistedIngest:
    ingest_id: str
    result: str


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

    def add_device(self, subject_id: str, device_id: str, enrolled_at_ms: int, source_tid: str | None = None) -> Device:
        self._connection.execute(
            "INSERT INTO devices(subject_id, device_id, status, enrolled_at_ms, source_tid) VALUES (?, ?, 'active', ?, ?)",
            (subject_id, device_id, enrolled_at_ms, source_tid),
        )
        self._connection.commit()
        return Device(subject_id, device_id, "active", source_tid)

    def get_device(self, subject_id: str, device_id: str) -> Device:
        row = self._connection.execute(
            "SELECT subject_id, device_id, status, source_tid FROM devices WHERE subject_id = ? AND device_id = ?",
            (subject_id, device_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("device_not_found")
        return Device(*row)

    def add_credential(
        self,
        subject_id: str,
        device_id: str,
        key_id: str,
        secret_ref: str,
        valid_from_ms: int,
        valid_until_ms: int | None = None,
    ) -> Credential:
        self._connection.execute(
            """INSERT INTO credentials(
                subject_id, device_id, key_id, secret_ref, valid_from_ms, valid_until_ms
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (subject_id, device_id, key_id, secret_ref, valid_from_ms, valid_until_ms),
        )
        self._connection.commit()
        return Credential(subject_id, device_id, key_id, secret_ref)

    def credential(self, key_id: str, now_ms: int) -> tuple[Credential, str | None] | None:
        row = self._connection.execute(
            """SELECT c.subject_id, c.device_id, c.key_id, c.secret_ref, d.source_tid
               FROM credentials c
               JOIN devices d ON d.subject_id = c.subject_id AND d.device_id = c.device_id
               JOIN subjects s ON s.subject_id = c.subject_id
               WHERE c.key_id = ? AND c.valid_from_ms <= ?
                 AND (c.valid_until_ms IS NULL OR c.valid_until_ms > ?)
                 AND d.status = 'active' AND s.status = 'active'""",
            (key_id, now_ms, now_ms),
        ).fetchone()
        if row is None:
            return None
        return Credential(row[0], row[1], row[2], row[3]), row[4]

    def usable_credentials(self, now_ms: int) -> tuple[tuple[Credential, str | None], ...]:
        rows = self._connection.execute(
            """SELECT c.subject_id, c.device_id, c.key_id, c.secret_ref, d.source_tid
               FROM credentials c
               JOIN devices d ON d.subject_id = c.subject_id AND d.device_id = c.device_id
               JOIN subjects s ON s.subject_id = c.subject_id
               WHERE c.valid_from_ms <= ? AND (c.valid_until_ms IS NULL OR c.valid_until_ms > ?)
                 AND d.status = 'active' AND s.status = 'active' ORDER BY c.key_id""",
            (now_ms, now_ms),
        )
        return tuple((Credential(row[0], row[1], row[2], row[3]), row[4]) for row in rows)

    def persist_ingest(
        self,
        *,
        subject_id: str,
        device_id: str,
        ingest_id: str,
        idempotency_key: str,
        source_digest: str,
        payload: bytes,
        received_at_ms: int,
        captured_at_ms: int,
        source_type: str,
        disposition: str,
        request_id: str,
        key_id: str,
        content_type: str,
        content_length: int,
        user_agent_family: str,
        receiver_build: str,
        quarantine_reason: str | None = None,
        before_commit: Callable[[], None] | None = None,
    ) -> PersistedIngest:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            duplicate = self._connection.execute(
                "SELECT ingest_id FROM raw_events WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if duplicate is not None:
                self._connection.commit()
                return PersistedIngest(duplicate[0], "duplicate")
            self._connection.execute(
                """INSERT INTO raw_events(
                    subject_id, device_id, ingest_id, idempotency_key, source_digest, payload,
                    received_at_ms, captured_at_ms, source_type, disposition, synthetic,
                    request_id, key_id, content_type, content_length, user_agent_family, receiver_build
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                (
                    subject_id, device_id, ingest_id, idempotency_key, source_digest, payload,
                    received_at_ms, captured_at_ms, source_type, disposition, request_id, key_id, content_type,
                    content_length, user_agent_family, receiver_build,
                ),
            )
            if disposition == "accepted":
                self._connection.execute(
                    """INSERT INTO processing_jobs(
                        subject_id, job_id, ingest_id, state, attempts, next_attempt_ms,
                        created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)""",
                    (subject_id, f"job_{ingest_id[4:]}", ingest_id, received_at_ms, received_at_ms, received_at_ms),
                )
            else:
                self._connection.execute(
                    """INSERT INTO quarantine(
                        subject_id, quarantine_id, ingest_id, reason_code, details_code,
                        review_state, created_at_ms
                    ) VALUES (?, ?, ?, ?, 'future_timestamp', 'pending', ?)""",
                    (subject_id, f"qua_{ingest_id[4:]}", ingest_id, quarantine_reason, received_at_ms),
                )
            if before_commit is not None:
                before_commit()
            self._connection.commit()
            return PersistedIngest(ingest_id, disposition)
        except Exception:
            self._connection.rollback()
            raise

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
