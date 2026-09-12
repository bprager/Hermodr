"""Bounded, checkpointed access to the append-only integration outbox."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sqlite3

from .contracts import load_schema, validate


CONSUMER_ID = re.compile(r"^[a-z0-9_-]{1,64}$")
PROJECTABLE_TYPES = frozenset({
    "place.recorded", "transition.recorded", "visit.recorded", "trip.recorded",
    "coverage_gap.recorded", "record.superseded", "record.tombstoned",
})


class OutboxError(RuntimeError):
    """A fail-closed integration boundary error."""


@dataclass(frozen=True)
class OutboxItem:
    sequence: int
    event_id: str
    event_type: str
    payload: dict[str, object]


def register_consumer(connection: sqlite3.Connection, consumer_id: str, now_ms: int) -> None:
    if CONSUMER_ID.fullmatch(consumer_id) is None:
        raise OutboxError("consumer_id_invalid")
    connection.execute(
        "INSERT OR IGNORE INTO outbox_consumers VALUES (?, 0, ?)",
        (consumer_id, now_ms),
    )
    connection.commit()


def read_batch(connection: sqlite3.Connection, consumer_id: str, limit: int = 100) -> tuple[OutboxItem, ...]:
    if CONSUMER_ID.fullmatch(consumer_id) is None or not 1 <= limit <= 1000:
        raise OutboxError("outbox_request_invalid")
    consumer = connection.execute(
        "SELECT last_sequence FROM outbox_consumers WHERE consumer_id=?", (consumer_id,),
    ).fetchone()
    if consumer is None:
        raise OutboxError("consumer_not_registered")
    result = []
    for row in connection.execute(
        """SELECT sequence, event_id, event_type, schema_version, payload_json
           FROM outbox_records WHERE sequence > ? ORDER BY sequence LIMIT ?""",
        (consumer[0], limit),
    ):
        try:
            payload = json.loads(row[4])
        except (TypeError, json.JSONDecodeError) as exc:
            raise OutboxError("outbox_payload_invalid") from exc
        if row[3] != "1" or validate(load_schema("outbox-envelope"), payload):
            raise OutboxError("outbox_schema_rejected")
        result.append(OutboxItem(row[0], row[1], row[2], payload))
    return tuple(result)


def acknowledge(
    connection: sqlite3.Connection,
    consumer_id: str,
    item: OutboxItem,
    now_ms: int,
) -> bool:
    try:
        connection.execute("BEGIN IMMEDIATE")
        checkpoint = connection.execute(
            "SELECT last_sequence FROM outbox_consumers WHERE consumer_id=?", (consumer_id,),
        ).fetchone()
        if checkpoint is None:
            raise OutboxError("consumer_not_registered")
        stored = connection.execute(
            "SELECT event_id,event_type FROM outbox_records WHERE sequence=?", (item.sequence,),
        ).fetchone()
        if stored is None or tuple(stored) != (item.event_id, item.event_type):
            raise OutboxError("outbox_item_invalid")
        gap = connection.execute(
            "SELECT 1 FROM outbox_records WHERE sequence > ? AND sequence < ? LIMIT 1",
            (checkpoint[0], item.sequence),
        ).fetchone()
        if item.sequence > checkpoint[0] + 1 and gap is not None:
            raise OutboxError("outbox_checkpoint_gap")
        inserted = connection.execute(
            "INSERT OR IGNORE INTO outbox_receipts VALUES (?, ?, ?, ?)",
            (consumer_id, item.sequence, item.event_id, now_ms),
        ).rowcount == 1
        connection.execute(
            "UPDATE outbox_consumers SET last_sequence=MAX(last_sequence, ?), updated_at_ms=? WHERE consumer_id=?",
            (item.sequence, now_ms, consumer_id),
        )
        connection.commit()
        return inserted
    except Exception:
        connection.rollback()
        raise


class FakeImporter:
    """Conformance fixture; it deliberately has no graph client or credential."""

    def __init__(self):
        self.projection: dict[str, dict[str, object]] = {}

    def apply(self, item: OutboxItem) -> None:
        if item.event_type not in PROJECTABLE_TYPES:
            raise OutboxError("outbox_type_rejected")
        data = item.payload["data"]
        if item.event_type == "place.recorded" and data.get("approval_state") != "approved":
            raise OutboxError("outbox_entity_rejected")
        if item.event_type in {"record.superseded", "record.tombstoned"}:
            self.projection.pop(str(data["record_id"]), None)
        else:
            record_id = next(
                str(value) for key, value in data.items() if key.endswith("_id") and key != "subject_id"
            )
            self.projection[record_id] = dict(data)

    def consume(self, connection: sqlite3.Connection, consumer_id: str, now_ms: int) -> int:
        applied = 0
        for item in read_batch(connection, consumer_id):
            unseen = connection.execute(
                "SELECT 1 FROM outbox_receipts WHERE consumer_id=? AND event_id=?",
                (consumer_id, item.event_id),
            ).fetchone() is None
            projectable = item.event_type in PROJECTABLE_TYPES and not (
                item.event_type == "place.recorded"
                and item.payload["data"].get("approval_state") != "approved"
            )
            if unseen and projectable:
                self.apply(item)
            if acknowledge(connection, consumer_id, item, now_ms):
                applied += 1
        return applied
