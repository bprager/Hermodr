from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
import io

from hermodr.audit import AuditError, verify_chain
from hermodr.config import Configuration
from hermodr.contracts import load_schema, validate
from hermodr.database import connect, migrate
from hermodr.derivation import (
    DerivationError, preview_subject, register_place, reprocess_subject, schedule_recompute,
)
from hermodr.identifiers import deterministic_id
from hermodr.lifecycle import (
    DAY_MS, LifecycleError, apply_deletion, apply_retention, approve_default_policy,
    plan_deletion,
)
from hermodr.outbox import (
    FakeImporter, OutboxError, OutboxItem, acknowledge, read_batch, register_consumer,
)
from hermodr.processor import _outbox
from hermodr.cli import run


class IntegratedTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.configuration = Configuration(
            "test", Path(self.temporary.name) / "database.sqlite", "127.0.0.1", "INFO", 1000,
            visit_dwell_ms=100, coverage_gap_ms=500,
        )
        self.connection = connect(self.configuration)
        migrate(self.connection)
        self.subject = "sub_12345678"
        self.connection.execute(
            "INSERT INTO subjects VALUES (?, 'active', 'policy_v1', 'authorization_v1', 0, NULL)",
            (self.subject,),
        )
        self.connection.execute(
            "INSERT INTO devices(subject_id,device_id,status,enrolled_at_ms,revoked_at_ms) VALUES (?, 'device_1', 'active', 0, NULL)",
            (self.subject,),
        )
        self.connection.commit()
        self.config_path = Path(self.temporary.name) / "config.json"
        self.config_path.write_text(json.dumps({
            "environment": "test", "database_path": str(self.configuration.database_path),
            "operations_bind": "127.0.0.1", "log_level": "INFO", "busy_timeout_ms": 1000,
            "visit_dwell_ms": 100, "coverage_gap_ms": 500,
        }), encoding="utf-8")

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def observation(self, number, captured, latitude, longitude, accuracy=5):
        ingest = f"ing_{number:032x}"
        observation = f"obs_{number:032x}"
        digest = f"{number:064x}"
        payload = json.dumps({"_type": "location", "lat": latitude, "lon": longitude}).encode()
        self.connection.execute(
            """INSERT INTO raw_events(
                   subject_id,device_id,ingest_id,idempotency_key,source_digest,payload,
                   received_at_ms,captured_at_ms,source_type,disposition,synthetic)
               VALUES (?, 'device_1', ?, ?, ?, ?, ?, ?, 'location', 'accepted', 0)""",
            (self.subject, ingest, f"key_{number}", digest, payload, captured, captured),
        )
        self.connection.execute(
            """INSERT INTO observations(
                   subject_id,observation_id,device_id,ingest_id,schema_version,algorithm_version,
                   captured_at_ms,received_at_ms,latitude,longitude,horizontal_accuracy_m,
                   quality_flags_json,source_digest,processed_at_ms,source_type,algorithm_config_version)
               VALUES (?, ?, 'device_1', ?, '1', 'test', ?, ?, ?, ?, ?, '[]', ?, ?, 'location', ?)""",
            (self.subject, observation, ingest, captured, captured, latitude, longitude,
             accuracy, digest, captured, self.configuration.fingerprint),
        )
        self.connection.execute(
            """INSERT INTO normalized_events VALUES (
                   ?, ?, ?, 'device_1', 'location', ?, ?, ?, '1', 'test', ?, ?, '{}')""",
            (self.subject, f"nrm_{number:032x}", ingest, captured, captured, captured,
             self.configuration.fingerprint, digest),
        )
        self.connection.commit()
        return observation

    def route(self):
        register_place(
            self.connection, self.configuration, subject_id=self.subject, latitude=0,
            longitude=0, radius_m=100, sensitivity="restricted", approval_state="approved",
            effective_from_ms=0, now_ms=10,
        )
        register_place(
            self.connection, self.configuration, subject_id=self.subject, latitude=0,
            longitude=.01, radius_m=100, sensitivity="restricted", approval_state="approved",
            effective_from_ms=0, now_ms=11,
        )
        self.observation(1, 1000, 0, 0)
        self.observation(2, 1200, 0, 0)
        self.observation(3, 1400, 0, .005, 1)
        self.observation(4, 1600, 0, .01)
        self.observation(5, 1800, 0, .01)
        self.observation(6, 2500, 0, .01)


class DerivationTests(IntegratedTestCase):
    def test_controlled_route_contracts_and_gap(self):
        self.route()
        summary = reprocess_subject(self.connection, self.configuration, self.subject, 3000)
        self.assertEqual(summary.transitions, 2)
        self.assertEqual(summary.visits, 2)
        self.assertEqual(summary.trips, 1)
        self.assertEqual(summary.gaps, 1)
        for row in self.connection.execute(
            "SELECT event_type,payload_json FROM outbox_records WHERE event_type != 'observation.recorded'"
        ):
            envelope = json.loads(row[1])
            self.assertFalse(validate(load_schema("outbox-envelope"), envelope))
            name = row[0].split(".", 1)[0].replace("coverage_gap", "coverage-gap")
            self.assertFalse(validate(load_schema(name), envelope["data"]))

    def test_preview_is_non_mutating_and_recompute_coalesces(self):
        self.route()
        before = self.connection.total_changes
        summary = preview_subject(self.connection, self.configuration, self.subject, 3000)
        self.assertEqual(summary.visits, 2)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM visits").fetchone()[0], 0)
        first = schedule_recompute(self.connection, self.configuration, self.subject, 100, 200, "new_data", 1)
        second = schedule_recompute(self.connection, self.configuration, self.subject, 50, 300, "late_data", 2)
        self.connection.commit()
        self.assertEqual(first, second)
        self.assertEqual(tuple(self.connection.execute(
            "SELECT start_ms,end_ms,cause FROM recompute_windows"
        ).fetchone()), (50, 300, "late_data"))
        self.assertGreater(self.connection.total_changes, before)

    def test_place_boundaries_ambiguity_and_validation(self):
        first = register_place(
            self.connection, self.configuration, subject_id=self.subject, latitude=0,
            longitude=0, radius_m=100, sensitivity="private", approval_state="approved",
            effective_from_ms=0, now_ms=1, label="synthetic",
        )
        self.assertTrue(first.startswith("plc_"))
        with self.assertRaisesRegex(DerivationError, "place_geometry_invalid"):
            register_place(self.connection, self.configuration, subject_id=self.subject, latitude=91,
                           longitude=0, radius_m=1, sensitivity="private", approval_state="approved",
                           effective_from_ms=0, now_ms=1)
        with self.assertRaisesRegex(DerivationError, "place_policy_invalid"):
            register_place(self.connection, self.configuration, subject_id=self.subject, latitude=0,
                           longitude=0, radius_m=1, sensitivity="public", approval_state="approved",
                           effective_from_ms=0, now_ms=1)
        with self.assertRaisesRegex(DerivationError, "place_label_invalid"):
            register_place(self.connection, self.configuration, subject_id=self.subject, latitude=0,
                           longitude=0, radius_m=1, sensitivity="private", approval_state="approved",
                           effective_from_ms=0, now_ms=1, label="")
        with self.assertRaisesRegex(DerivationError, "recompute_request_invalid"):
            schedule_recompute(self.connection, self.configuration, self.subject, 2, 1, "bad", 1)

    def test_subject_isolation_and_missing_subject(self):
        self.route()
        other = "sub_abcdef12"
        self.connection.execute("INSERT INTO subjects VALUES (?, 'active', 'p', 'a', 0, NULL)", (other,))
        self.connection.commit()
        reprocess_subject(self.connection, self.configuration, self.subject, 3000)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM visits WHERE subject_id=?", (other,),
        ).fetchone()[0], 0)
        with self.assertRaisesRegex(DerivationError, "subject_not_found"):
            reprocess_subject(self.connection, self.configuration, "sub_deadbeef", 1)

    def test_algorithm_change_supersedes_prior_derivation(self):
        self.route()
        reprocess_subject(self.connection, self.configuration, self.subject, 3000)
        changed = Configuration(
            "test", self.configuration.database_path, "127.0.0.1", "INFO", 1000,
            visit_dwell_ms=101, coverage_gap_ms=500,
        )
        reprocess_subject(self.connection, changed, self.subject, 3100)
        superseded = self.connection.execute(
            "SELECT COUNT(*) FROM visits WHERE status='superseded'"
        ).fetchone()[0]
        self.assertGreater(superseded, 0)
        self.assertGreater(self.connection.execute(
            "SELECT COUNT(*) FROM outbox_records WHERE event_type='record.superseded'"
        ).fetchone()[0], 0)


class LifecycleTests(IntegratedTestCase):
    def invoke(self, *arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            result = run(["--config", str(self.config_path), "admin", *arguments])
        return result, json.loads(output.getvalue())

    def test_audited_cli_controls_and_boundaries(self):
        self.observation(1, 100, 0, 0)
        result, report = self.invoke(
            "retention-approve", "--subject-id", self.subject, "--run-id", "run_1", "--now-ms", "1000",
        )
        self.assertEqual((result, report["status"]), (0, "ok"))
        result, report = self.invoke(
            "reprocess-preview", "--subject-id", self.subject, "--reason-code", "review",
            "--run-id", "run_2", "--now-ms", "1000",
        )
        self.assertEqual((result, report["mode"]), (0, "preview"))
        result, report = self.invoke(
            "deletion-plan", "--subject-id", self.subject, "--start-ms", "1", "--end-ms", "200",
            "--run-id", "run_3", "--now-ms", "1000",
        )
        self.assertEqual((result, report["status"]), (0, "planned"))
        result, report = self.invoke("deletion-apply", "--plan-id", report["plan_id"], "--run-id", "run_4", "--now-ms", "1100")
        self.assertEqual((result, report["status"]), (0, "applied"))
        self.assertEqual(self.invoke("audit-verify")[1]["status"], "ok")
        result, report = self.invoke("retention-apply")
        self.assertEqual((result, report["error"]), (2, "retention_arguments_missing"))

    def test_approved_retention_scrubs_and_preserves_hold(self):
        now = 300 * DAY_MS
        self.observation(1, 1, 0, 0)
        self.observation(2, 2, 0, 0)
        self.connection.execute(
            "INSERT INTO retention_holds VALUES (?, 'hold_1', 2, 2, 'review', 3, NULL)",
            (self.subject,),
        )
        self.connection.commit()
        approve_default_policy(self.connection, self.configuration, self.subject, now, "run_1")
        counts = apply_retention(self.connection, self.configuration, self.subject, now, "run_2")
        self.assertEqual(counts, {"raw_payloads": 1, "normalized_events": 1, "observations": 1})
        rows = self.connection.execute(
            "SELECT length(payload),payload_expired_at_ms FROM raw_events ORDER BY captured_at_ms"
        ).fetchall()
        self.assertEqual(tuple(rows[0]), (0, now))
        self.assertIsNone(rows[1][1])
        self.assertEqual(verify_chain(self.connection), 2)

    def test_two_step_deletion_counts_tombstone_and_idempotency(self):
        self.route()
        reprocess_subject(self.connection, self.configuration, self.subject, 3000)
        plan_id, expected = plan_deletion(
            self.connection, self.configuration, self.subject, 900, 2600, 4000, "run_1",
        )
        self.assertGreater(expected["observations"], 0)
        applied = apply_deletion(self.connection, self.configuration, plan_id, 4500, "run_2")
        self.assertEqual(applied, expected)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)
        tombstones = self.connection.execute(
            "SELECT COUNT(*) FROM outbox_records WHERE event_type='record.tombstoned'"
        ).fetchone()[0]
        self.assertGreater(tombstones, 0)
        with self.assertRaisesRegex(LifecycleError, "deletion_plan_invalid"):
            apply_deletion(self.connection, self.configuration, plan_id, 4600, "run_3")

    def test_deletion_rejects_stale_expired_missing_and_bad_requests(self):
        self.observation(1, 100, 0, 0)
        with self.assertRaisesRegex(LifecycleError, "deletion_request_invalid"):
            plan_deletion(self.connection, self.configuration, self.subject, 2, 1, 3, "bad run")
        with self.assertRaisesRegex(LifecycleError, "subject_not_found"):
            plan_deletion(self.connection, self.configuration, "sub_deadbeef", 1, 2, 3, "run_1")
        plan_id, _ = plan_deletion(self.connection, self.configuration, self.subject, 1, 200, 300, "run_2")
        self.observation(2, 150, 0, 0)
        with self.assertRaisesRegex(LifecycleError, "deletion_plan_stale"):
            apply_deletion(self.connection, self.configuration, plan_id, 400, "run_3")
        second, _ = plan_deletion(self.connection, self.configuration, self.subject, 500, 600, 700, "run_4")
        with self.assertRaisesRegex(LifecycleError, "deletion_plan_expired"):
            apply_deletion(self.connection, self.configuration, second, 700 + DAY_MS + 1, "run_5")
        with self.assertRaisesRegex(LifecycleError, "deletion_plan_invalid"):
            apply_deletion(self.connection, self.configuration, "del_missing", 1, "run_6")
        with self.assertRaisesRegex(LifecycleError, "retention_policy_missing"):
            apply_retention(self.connection, self.configuration, self.subject, 1, "run_7")

    def test_audit_tamper_is_detected(self):
        approve_default_policy(self.connection, self.configuration, self.subject, 1, "run_1")
        self.connection.execute("UPDATE audit_events SET reason='tampered'")
        self.connection.commit()
        with self.assertRaisesRegex(AuditError, "audit_chain_invalid"):
            verify_chain(self.connection)


class OutboxTests(IntegratedTestCase):
    def test_checkpoint_replay_forbidden_type_and_tombstone(self):
        self.route()
        reprocess_subject(self.connection, self.configuration, self.subject, 3000)
        register_consumer(self.connection, "fake_importer", 1)
        importer = FakeImporter()
        first = importer.consume(self.connection, "fake_importer", 2)
        self.assertGreater(first, 0)
        self.assertEqual(importer.consume(self.connection, "fake_importer", 3), 0)
        forbidden = OutboxItem(1, "evt_" + "1" * 32, "observation.recorded", {"data": {}})
        with self.assertRaisesRegex(OutboxError, "outbox_type_rejected"):
            importer.apply(forbidden)
        record_id = next(iter(importer.projection))
        sequence = self.connection.execute("SELECT MAX(sequence) FROM outbox_records").fetchone()[0] + 1
        _outbox(
            self.connection, subject_id=self.subject,
            event_id=deterministic_id("evt", "record.tombstoned", record_id),
            aggregate_id=record_id, event_type="record.tombstoned", occurred_at_ms=4,
            published_at_ms=4, provenance=[], data={"record_type": "visit", "record_id": record_id},
        )
        self.connection.commit()
        importer.consume(self.connection, "fake_importer", 5)
        self.assertNotIn(record_id, importer.projection)
        self.assertGreater(sequence, 0)

    def test_boundary_rejects_bad_consumer_schema_and_checkpoint_gap(self):
        with self.assertRaisesRegex(OutboxError, "consumer_id_invalid"):
            register_consumer(self.connection, "bad id", 1)
        with self.assertRaisesRegex(OutboxError, "consumer_not_registered"):
            read_batch(self.connection, "missing")
        register_consumer(self.connection, "consumer", 1)
        with self.assertRaisesRegex(OutboxError, "outbox_request_invalid"):
            read_batch(self.connection, "consumer", 0)
        item = OutboxItem(2, "evt_" + "1" * 32, "visit.recorded", {"data": {}})
        with self.assertRaisesRegex(OutboxError, "outbox_item_invalid"):
            acknowledge(self.connection, "consumer", item, 2)
        self.route()
        self.connection.execute("UPDATE outbox_records SET schema_version='2' WHERE sequence=1")
        self.connection.commit()
        with self.assertRaisesRegex(OutboxError, "outbox_schema_rejected"):
            read_batch(self.connection, "consumer")


if __name__ == "__main__":
    unittest.main()
