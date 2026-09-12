from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from hermodr.config import Configuration
from hermodr.contracts import load_schema, validate
from hermodr.database import connect, migrate
from hermodr.identifiers import canonical_json, source_digest
from hermodr.processor import (
    ProcessingError,
    claim_next,
    fail_claimed,
    process_one,
    reclaim_expired,
)
from hermodr.repository import Repository


NOW_MS = int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


class ProcessingTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.configuration = Configuration(
            "test", self.root / "events.sqlite", "127.0.0.1", "INFO", 1000,
            processor_lease_ms=1_000, processor_max_attempts=3,
            processor_base_backoff_ms=100, processor_max_backoff_ms=1_000,
            poor_accuracy_m=50, implausible_speed_mps=80, late_after_ms=10_000,
        )
        connection = connect(self.configuration)
        migrate(connection)
        repository = Repository(connection)
        for suffix in ("00000000", "11111111"):
            repository.add_subject(f"sub_{suffix}", f"policy_{suffix}", 1)
            repository.add_device(f"sub_{suffix}", f"dev_{suffix}", 1, suffix[:2])
        connection.close()

    def tearDown(self):
        self.temporary.cleanup()

    def queue(
        self,
        suffix: str,
        payload: dict[str, object],
        *,
        subject: str = "sub_00000000",
        received_at_ms: int = NOW_MS,
    ) -> str:
        ingest_id = f"ing_{suffix:0>20}"
        device_id = "dev_11111111" if subject.endswith("11111111") else "dev_00000000"
        encoded = canonical_json(payload)
        connection = connect(self.configuration)
        try:
            Repository(connection).add_raw_event(
                subject_id=subject, device_id=device_id, ingest_id=ingest_id,
                idempotency_key=f"{suffix:0>64}", source_digest=source_digest(payload),
                payload=encoded, received_at_ms=received_at_ms,
                captured_at_ms=int(payload["tst"]) * 1000,
                source_type=str(payload["_type"]),
            )
            job_id = f"job_{suffix:0>20}"
            connection.execute(
                """INSERT INTO processing_jobs(
                       subject_id, job_id, ingest_id, state, attempts, next_attempt_ms,
                       created_at_ms, updated_at_ms
                   ) VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)""",
                (subject, job_id, ingest_id, received_at_ms, received_at_ms, received_at_ms),
            )
            connection.commit()
            return job_id
        finally:
            connection.close()


class ClaimTests(ProcessingTestCase):
    def test_claim_is_atomic_ordered_and_owner_bounded(self):
        self.queue("2", {"_type": "status", "tst": 20}, subject="sub_11111111", received_at_ms=20_000)
        first_job = self.queue("1", {"_type": "status", "tst": 30}, received_at_ms=30_000)
        connection = connect(self.configuration)
        second = connect(self.configuration)
        try:
            first = claim_next(connection, "worker-a", NOW_MS, 1_000)
            other = claim_next(second, "worker-b", NOW_MS, 1_000)
            self.assertEqual((first.job_id, first.attempts, first.lease_owner), (first_job, 1, "worker-a"))
            self.assertEqual(other.subject_id, "sub_11111111")
            self.assertIsNone(claim_next(connection, "worker", NOW_MS, 1_000))
            for owner in ("", "x" * 129):
                with self.assertRaisesRegex(ProcessingError, "lease_owner_invalid"):
                    claim_next(connection, owner, NOW_MS, 1_000)
        finally:
            second.close()
            connection.close()

    def test_expired_lease_reclaims_after_boot(self):
        job_id = self.queue("3", {"_type": "status", "tst": 1}, received_at_ms=1_000)
        connection = connect(self.configuration)
        try:
            claimed = claim_next(connection, "old-worker", 1_000, 1_000)
            self.assertEqual(claimed.job_id, job_id)
            connection.execute("BEGIN IMMEDIATE")
            self.assertEqual(reclaim_expired(connection, 1_999), 0)
            self.assertEqual(reclaim_expired(connection, 2_000), 1)
            connection.commit()
            reclaimed = claim_next(connection, "new-worker", 2_000, 1)
            self.assertEqual((reclaimed.job_id, reclaimed.attempts), (job_id, 2))
        finally:
            connection.close()


class NormalizationTests(ProcessingTestCase):
    def test_source_transition_and_waypoint_are_uncertain(self):
        self.queue(
            "90", {"_type": "transition", "tst": 100, "lat": 0.0, "lon": 0.0,
                    "acc": 5, "event": "enter"}, received_at_ms=100_000,
        )
        self.queue(
            "91", {"_type": "waypoint", "tst": 101, "lat": 0.0, "lon": 0.0,
                    "rad": 100, "desc": "synthetic-zone"}, received_at_ms=101_000,
        )
        process_one(self.configuration, "worker", 100_000)
        process_one(self.configuration, "worker", 101_000)
        connection = connect(self.configuration)
        try:
            source = connection.execute(
                "SELECT confidence,status,algorithm_version FROM transitions WHERE algorithm_version='owntracks-transition-v1'"
            ).fetchone()
            self.assertEqual(tuple(source), (0.5, "provisional", "owntracks-transition-v1"))
            flags = json.loads(connection.execute(
                "SELECT quality_flags_json FROM observations WHERE source_type='transition'"
            ).fetchone()[0])
            self.assertIn("source_transition_unconfirmed", flags)
            place = connection.execute("SELECT approval_state FROM places").fetchone()
            self.assertEqual(place[0], "proposed")
        finally:
            connection.close()

    def test_all_source_adapters_are_deterministic_and_idempotent(self):
        payloads = (
            {"_type": "location", "tst": 100, "lat": 1.0, "lon": 2.0, "acc": 4,
             "alt": 8, "vel": 3, "cog": 90, "batt": 80, "t": "u", "conn": "w"},
            {"_type": "transition", "tst": 101, "lat": 1.1, "lon": 2.1, "acc": 5},
            {"_type": "waypoint", "tst": 102, "lat": 1.2, "lon": 2.2, "acc": 6},
            {"_type": "status", "tst": 103},
        )
        for index, payload in enumerate(payloads, 1):
            self.queue(str(index), payload, received_at_ms=NOW_MS + index)
            self.assertEqual(process_one(self.configuration, "worker", NOW_MS + index).state, "processed")
        connection = connect(self.configuration)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM normalized_events").fetchone()[0], 4)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM outbox_records").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM processing_jobs WHERE state='processed'").fetchone()[0], 4)
            observation_schema = load_schema("observation")
            outbox_schema = load_schema("outbox-envelope")
            for row in connection.execute("SELECT payload_json FROM outbox_records ORDER BY sequence"):
                envelope = json.loads(row[0])
                self.assertFalse(validate(outbox_schema, envelope))
                self.assertFalse(validate(observation_schema, envelope["data"]))
            row = connection.execute(
                "SELECT altitude_m, velocity_mps, heading_deg, battery_percent, trigger, connectivity FROM observations ORDER BY captured_at_ms LIMIT 1"
            ).fetchone()
            self.assertEqual(tuple(row), (8.0, 3.0, 90.0, 80.0, "u", "w"))
            self.assertIsNone(process_one(self.configuration, "worker", NOW_MS + 10))
        finally:
            connection.close()

    def test_quality_flags_are_bounded_and_subject_scoped(self):
        self.queue("10", {"_type": "location", "tst": 100, "lat": 0.0, "lon": 0.0, "acc": 1}, received_at_ms=100_000)
        process_one(self.configuration, "worker", 100_000)
        self.queue("11", {"_type": "location", "tst": 101, "lat": 1.0, "lon": 1.0, "acc": 99}, received_at_ms=200_000)
        process_one(self.configuration, "worker", 200_000)
        self.queue("12", {"_type": "location", "tst": 50, "lat": 2.0, "lon": 2.0}, received_at_ms=200_000)
        process_one(self.configuration, "worker", 200_001)
        connection = connect(self.configuration)
        try:
            values = [set(json.loads(row[0])) for row in connection.execute(
                "SELECT quality_flags_json FROM observations ORDER BY captured_at_ms"
            )]
            combined = set().union(*values)
            self.assertTrue({"late", "missing_accuracy", "out_of_order", "poor_accuracy", "implausible_speed"} <= combined)
            self.assertNotIn("subject_id", combined)
        finally:
            connection.close()

    def test_crash_rolls_back_effects_then_expired_lease_replays_once(self):
        job_id = self.queue("20", {"_type": "location", "tst": 100, "lat": 1.0, "lon": 2.0}, received_at_ms=100_000)
        with self.assertRaisesRegex(RuntimeError, "crash"):
            process_one(
                self.configuration, "worker-a", 100_000,
                before_commit=lambda: (_ for _ in ()).throw(RuntimeError("crash")),
            )
        connection = connect(self.configuration)
        try:
            self.assertEqual(tuple(connection.execute(
                "SELECT state, attempts FROM processing_jobs WHERE job_id=?", (job_id,)
            ).fetchone()), ("processing", 1))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)
        finally:
            connection.close()
        result = process_one(self.configuration, "worker-b", 101_000)
        self.assertEqual(result.state, "processed")
        connection = connect(self.configuration)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM outbox_records").fetchone()[0], 1)
        finally:
            connection.close()

    def test_permanent_and_transient_failures_are_bounded(self):
        permanent_job = self.queue("30", {"_type": "status", "tst": 100}, received_at_ms=100_000)
        connection = connect(self.configuration)
        connection.execute("UPDATE raw_events SET payload = x'ff' WHERE ingest_id LIKE 'ing_%30'")
        connection.commit()
        connection.close()
        self.assertEqual(process_one(self.configuration, "worker", 100_000).state, "failed")
        connection = connect(self.configuration)
        try:
            row = connection.execute("SELECT state, error_code FROM processing_jobs WHERE job_id=?", (permanent_job,)).fetchone()
            self.assertEqual(tuple(row), ("failed", "source_contract_invalid"))
        finally:
            connection.close()

    def test_retry_backoff_and_terminal_attempt(self):
        job_id = self.queue("40", {"_type": "status", "tst": 100}, received_at_ms=100_000)
        connection = connect(self.configuration)
        try:
            job = claim_next(connection, "worker", 100_000, 1_000)
            state = fail_claimed(connection, self.configuration, job, 100_000, "database_error")
            self.assertEqual(state, "pending")
            row = connection.execute("SELECT next_attempt_ms FROM processing_jobs WHERE job_id=?", (job_id,)).fetchone()
            self.assertGreaterEqual(row[0], 100_100)
            connection.execute("UPDATE processing_jobs SET next_attempt_ms=100001")
            connection.commit()
            second = claim_next(connection, "worker", 100_001, 1_000)
            fail_claimed(connection, self.configuration, second, 100_001, "database_error")
            connection.execute("UPDATE processing_jobs SET next_attempt_ms=100002")
            connection.commit()
            third = claim_next(connection, "worker", 100_002, 1_000)
            self.assertEqual(fail_claimed(connection, self.configuration, third, 100_002, "database_error"), "failed")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
