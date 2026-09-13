from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from hermodr.backup import BackupError, TABLES, _protected_file, create_backup, verify_backup
from hermodr.audit import AuditError, record_change
from hermodr.cli import run
from hermodr.commissioning import (
    CommissioningError, commissioning_preflight, disable_device, enroll_device,
    revoke_credential, stage_credential,
)
from hermodr.config import Configuration
from hermodr.database import connect, migrate
from hermodr.metrics import reconstruct_critical_metrics
from hermodr.processor import heartbeat, serve
from hermodr.repository import Repository


ROOT = Path(__file__).resolve().parents[1]


class OperationsTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.configuration = Configuration(
            "test", self.root / "data" / "hermodr.sqlite", "127.0.0.1", "INFO", 1000,
        )
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({
            "environment": "test", "database_path": str(self.configuration.database_path),
            "operations_bind": "127.0.0.1", "log_level": "INFO", "busy_timeout_ms": 1000,
        }), encoding="utf-8")
        connection = connect(self.configuration)
        migrate(connection)
        repository = Repository(connection)
        repository.add_subject("sub_synthetic", "policy_synthetic", 1)
        repository.add_device("sub_synthetic", "dev_synthetic", 1, "ZZ")
        connection.close()
        self.passphrase = self.root / "backup.passphrase"
        self.passphrase.write_text("synthetic-test-passphrase-value", encoding="utf-8")
        self.passphrase.chmod(0o600)
        self.first_secret = self.root / "first.secret"
        self.first_secret.write_bytes(b"first-synthetic-secret-value")
        self.first_secret.chmod(0o600)
        connection = connect(self.configuration)
        Repository(connection).add_credential(
            "sub_synthetic", "dev_synthetic", "key_first", str(self.first_secret), 1,
        )
        connection.close()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def copy_runner(arguments, **_kwargs):
        output = Path(arguments[arguments.index("--output") + 1])
        shutil.copyfile(Path(arguments[-1]), output)
        return subprocess.CompletedProcess(arguments, 0, b"", b"")


class BackupTests(OperationsTestCase):
    def test_create_verify_restore_and_durable_metrics(self):
        archive = self.root / "backups" / "snapshot.tar.gpg"
        report = create_backup(
            self.configuration, archive, self.passphrase,
            now=datetime(2030, 1, 1, tzinfo=timezone.utc), runner=self.copy_runner,
        )
        self.assertEqual(report.status, "ok")
        self.assertEqual(report.schema_version, 6)
        self.assertEqual(report.tables["subjects"], 1)
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        verified = verify_backup(self.configuration, archive, self.passphrase, runner=self.copy_runner)
        restored = verify_backup(self.configuration, archive, self.passphrase, restore_test=True, runner=self.copy_runner)
        self.assertEqual(verified.database_sha256, restored.database_sha256)
        connection = connect(self.configuration)
        try:
            values = dict(connection.execute("SELECT state_key, state_value FROM operational_state"))
            self.assertEqual(values["backup_create_status"], 1)
            self.assertEqual(values["backup_verify_status"], 1)
            self.assertEqual(values["backup_restore_test_status"], 1)
            metrics = reconstruct_critical_metrics(connection, 1_893_456_000_000).render()
        finally:
            connection.close()
        self.assertIn('hermodr_backup_status{stage="restore_test"} 1', metrics)
        self.assertIn("hermodr_database_integrity_status 1", metrics)
        self.assertEqual(set(report.tables), set(TABLES))
        self.assertEqual(set(report.identifier_hashes), set(TABLES))
        self.assertTrue(all(len(value) == 64 for value in report.identifier_hashes.values()))

    def test_backup_rejects_unsafe_inputs_and_crypto_failure(self):
        unsafe = self.root / "unsafe"
        unsafe.write_text("short", encoding="utf-8")
        unsafe.chmod(0o644)
        with self.assertRaisesRegex(BackupError, "passphrase_permissions_invalid"):
            _protected_file(unsafe)
        with self.assertRaisesRegex(BackupError, "passphrase_unreadable"):
            _protected_file(self.root / "missing")
        archive = self.root / "snapshot.gpg"
        archive.write_bytes(b"exists")
        with self.assertRaisesRegex(BackupError, "backup_output_exists"):
            create_backup(self.configuration, archive, self.passphrase, runner=self.copy_runner)
        archive.unlink()

        def failed(arguments, **_kwargs):
            raise subprocess.CalledProcessError(2, arguments)

        with self.assertRaisesRegex(BackupError, "encryption_operation_failed"):
            create_backup(self.configuration, archive, self.passphrase, runner=failed)
        connection = connect(self.configuration)
        try:
            self.assertEqual(connection.execute(
                "SELECT state_value FROM operational_state WHERE state_key='backup_create_status'"
            ).fetchone()[0], 0)
        finally:
            connection.close()

    def test_verification_rejects_tamper_and_invalid_archive(self):
        archive = self.root / "snapshot.gpg"
        create_backup(self.configuration, archive, self.passphrase, runner=self.copy_runner)
        archive.write_bytes(b"not a tar")
        with self.assertRaisesRegex(BackupError, "backup_verification_failed"):
            verify_backup(self.configuration, archive, self.passphrase, runner=self.copy_runner)
        connection = connect(self.configuration)
        try:
            self.assertEqual(connection.execute(
                "SELECT state_value FROM operational_state WHERE state_key='backup_verify_status'"
            ).fetchone()[0], 0)
        finally:
            connection.close()


class ProcessorAndCliTests(OperationsTestCase):
    def test_audited_device_enrollment_is_atomic_and_case_preserving(self):
        connection = connect(self.configuration)
        try:
            audit_id = enroll_device(
                connection, self.configuration, subject_id="sub_synthetic",
                device_id="dev_second", source_tid="aZ", enrolled_at_ms=10,
                reason_code="commissioning", run_id="run_device_enroll",
            )
            device = connection.execute(
                "SELECT status,enrolled_at_ms,source_tid FROM devices WHERE device_id='dev_second'"
            ).fetchone()
            audit = connection.execute(
                "SELECT audit_id,subject_id,action,target_id FROM audit_events"
            ).fetchone()
            self.assertEqual(tuple(device), ("active", 10, "aZ"))
            self.assertEqual(
                tuple(audit),
                (audit_id, "sub_synthetic", "device_change", "dev_second"),
            )
            with self.assertRaisesRegex(CommissioningError, "device_conflict"):
                enroll_device(
                    connection, self.configuration, subject_id="sub_synthetic",
                    device_id="dev_second", source_tid="A9", enrolled_at_ms=11,
                    reason_code="commissioning", run_id="run_conflict",
                )
            with patch("hermodr.commissioning.record_change", side_effect=AuditError("audit_failed")):
                with self.assertRaisesRegex(AuditError, "audit_failed"):
                    enroll_device(
                        connection, self.configuration, subject_id="sub_synthetic",
                        device_id="dev_atomic", source_tid="Z1", enrolled_at_ms=12,
                        reason_code="commissioning", run_id="run_atomic",
                    )
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM devices WHERE device_id='dev_atomic'"
            ).fetchone())
        finally:
            connection.close()

    def test_device_enrollment_validates_authority_and_bounded_fields(self):
        connection = connect(self.configuration)
        try:
            for source_tid in ("Z", "ZZZ", "é1", "_1"):
                with self.subTest(source_tid=source_tid), self.assertRaisesRegex(
                    CommissioningError, "device_source_tid_invalid",
                ):
                    enroll_device(
                        connection, self.configuration, subject_id="sub_synthetic",
                        device_id="dev_second", source_tid=source_tid, enrolled_at_ms=10,
                        reason_code="commissioning", run_id="run_enroll",
                    )
            with self.assertRaisesRegex(CommissioningError, "device_fields_invalid"):
                enroll_device(
                    connection, self.configuration, subject_id="sub_synthetic",
                    device_id="Device_Upper", source_tid="Z1", enrolled_at_ms=10,
                    reason_code="commissioning", run_id="run_enroll",
                )
            with self.assertRaisesRegex(CommissioningError, "device_time_invalid"):
                enroll_device(
                    connection, self.configuration, subject_id="sub_synthetic",
                    device_id="dev_second", source_tid="Z1", enrolled_at_ms=-1,
                    reason_code="commissioning", run_id="run_enroll",
                )
            connection.execute("UPDATE subjects SET status='disabled'")
            connection.commit()
            with self.assertRaisesRegex(CommissioningError, "device_subject_inactive"):
                enroll_device(
                    connection, self.configuration, subject_id="sub_synthetic",
                    device_id="dev_second", source_tid="Z1", enrolled_at_ms=10,
                    reason_code="commissioning", run_id="run_enroll",
                )
            with self.assertRaisesRegex(CommissioningError, "device_subject_not_found"):
                enroll_device(
                    connection, self.configuration, subject_id="sub_missing",
                    device_id="dev_second", source_tid="Z1", enrolled_at_ms=10,
                    reason_code="commissioning", run_id="run_enroll",
                )
        finally:
            connection.close()

    def test_device_disable_guards_credentials_and_is_idempotent(self):
        connection = connect(self.configuration)
        try:
            with self.assertRaisesRegex(CommissioningError, "device_credential_usable"):
                disable_device(
                    connection, self.configuration, subject_id="sub_synthetic",
                    device_id="dev_synthetic", disabled_at_ms=10,
                    reason_code="retire", run_id="run_guard",
                )
            enroll_device(
                connection, self.configuration, subject_id="sub_synthetic",
                device_id="dev_second", source_tid="Q2", enrolled_at_ms=10,
                reason_code="commissioning", run_id="run_enroll",
            )
            audit_id, changed = disable_device(
                connection, self.configuration, subject_id="sub_synthetic",
                device_id="dev_second", disabled_at_ms=20,
                reason_code="retire", run_id="run_disable",
            )
            self.assertTrue(changed)
            self.assertIsNotNone(audit_id)
            self.assertEqual(disable_device(
                connection, self.configuration, subject_id="sub_synthetic",
                device_id="dev_second", disabled_at_ms=21,
                reason_code="retire", run_id="run_repeat",
            ), (None, False))
            row = connection.execute(
                "SELECT status,revoked_at_ms FROM devices WHERE device_id='dev_second'"
            ).fetchone()
            self.assertEqual(tuple(row), ("disabled", 20))
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE action='device_change'"
            ).fetchone()[0], 2)
            enroll_device(
                connection, self.configuration, subject_id="sub_synthetic",
                device_id="dev_future", source_tid="F3", enrolled_at_ms=20,
                reason_code="commissioning", run_id="run_future_enroll",
            )
            connection.execute(
                """INSERT INTO credentials(
                       subject_id,device_id,key_id,secret_ref,valid_from_ms,valid_until_ms
                   ) VALUES ('sub_synthetic','dev_future','key_future','/synthetic',30,NULL)"""
            )
            connection.commit()
            self.assertTrue(disable_device(
                connection, self.configuration, subject_id="sub_synthetic",
                device_id="dev_future", disabled_at_ms=20,
                reason_code="retire", run_id="run_future_disable",
            )[1])
            with self.assertRaisesRegex(CommissioningError, "device_not_found"):
                disable_device(
                    connection, self.configuration, subject_id="sub_synthetic",
                    device_id="dev_missing", disabled_at_ms=20,
                    reason_code="retire", run_id="run_missing",
                )
            connection.execute("UPDATE subjects SET status='disabled'")
            connection.commit()
            with self.assertRaisesRegex(CommissioningError, "device_subject_inactive"):
                disable_device(
                    connection, self.configuration, subject_id="sub_synthetic",
                    device_id="dev_synthetic", disabled_at_ms=20,
                    reason_code="retire", run_id="run_inactive_subject",
                )
        finally:
            connection.close()

    def test_device_cli_actions_and_missing_arguments(self):
        for action in ("device-enroll", "device-disable"):
            with self.subTest(action=action), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(run(["--config", str(self.config_path), "admin", action]), 2)
                self.assertIn("device_arguments_missing", output.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run([
                "--config", str(self.config_path), "admin", "device-enroll",
                "--subject-id", "sub_synthetic", "--device-id", "dev_second",
                "--source-tid", "B2", "--reason-code", "commissioning",
                "--run-id", "run_enroll", "--now-ms", "10",
            ]), 0)
            self.assertEqual(run([
                "--config", str(self.config_path), "admin", "device-disable",
                "--subject-id", "sub_synthetic", "--device-id", "dev_second",
                "--reason-code", "retire", "--run-id", "run_disable", "--now-ms", "20",
            ]), 0)
        reports = tuple(json.loads(line) for line in output.getvalue().splitlines())
        self.assertEqual([report["status"] for report in reports], ["enrolled", "disabled"])

    def test_privacy_safe_commissioning_preflight(self):
        connection = connect(self.configuration)
        try:
            not_ready = commissioning_preflight(connection, 5)
            self.assertFalse(not_ready.ready)
            self.assertIn("retention_policy_missing", not_ready.issues)
            self.assertIn("backup_restore_test_missing", not_ready.issues)
            connection.execute(
                "INSERT INTO retention_policies VALUES (?,?,?,?,?,?,?)",
                ("sub_synthetic", 30, 90, None, 14, 5, "v1"),
            )
            for stage in ("create", "verify", "restore_test"):
                connection.execute(
                    "INSERT INTO operational_state VALUES (?,?,?)",
                    (f"backup_{stage}_status", 1, 5),
                )
            connection.commit()
            ready = commissioning_preflight(connection, 5)
        finally:
            connection.close()
        self.assertTrue(ready.ready)
        self.assertEqual(ready.issues, ())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run([
                "--config", str(self.config_path), "admin", "commissioning-preflight", "--now-ms", "5",
            ]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "ready")
        rendered = output.getvalue()
        for sensitive in ("sub_synthetic", "dev_synthetic", "key_first", str(self.first_secret)):
            self.assertNotIn(sensitive, rendered)

    def test_commissioning_preflight_detects_invalid_protected_secret(self):
        self.first_secret.chmod(0o644)
        connection = connect(self.configuration)
        try:
            report = commissioning_preflight(connection, 5)
            with self.assertRaisesRegex(CommissioningError, "commissioning_time_invalid"):
                commissioning_preflight(connection, -1)
        finally:
            connection.close()
        self.assertFalse(report.ready)
        self.assertEqual(report.usable_credentials, 1)
        self.assertEqual(report.protected_credentials, 0)
        self.assertIn("protected_credential_invalid", report.issues)

    def test_audited_credential_rotation_and_last_credential_guard(self):
        second_secret = self.root / "second.secret"
        second_secret.write_bytes(b"second-synthetic-secret-value")
        second_secret.chmod(0o600)
        connection = connect(self.configuration)
        try:
            with self.assertRaisesRegex(CommissioningError, "credential_replacement_required"):
                revoke_credential(
                    connection, self.configuration, key_id="key_first", revoked_at_ms=10,
                    reason_code="rotation", run_id="run_guard",
                )
            audit_id = stage_credential(
                connection, self.configuration, subject_id="sub_synthetic",
                device_id="dev_synthetic", key_id="key_second", secret_ref=second_secret,
                valid_from_ms=5, valid_until_ms=None, reason_code="rotation", run_id="run_stage",
            )
            revoked_audit, changed = revoke_credential(
                connection, self.configuration, key_id="key_first", revoked_at_ms=10,
                reason_code="rotation_complete", run_id="run_revoke",
            )
            self.assertTrue(changed)
            self.assertIsNotNone(revoked_audit)
            self.assertNotEqual(audit_id, revoked_audit)
            self.assertEqual(connection.execute(
                "SELECT valid_until_ms FROM credentials WHERE key_id='key_first'"
            ).fetchone()[0], 10)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 2)
            self.assertEqual(revoke_credential(
                connection, self.configuration, key_id="key_first", revoked_at_ms=10,
                reason_code="rotation_complete", run_id="run_repeat",
            ), (None, False))
        finally:
            connection.close()

    def test_credential_cli_boundaries(self):
        second_secret = self.root / "second.secret"
        second_secret.write_bytes(b"second-synthetic-secret-value")
        second_secret.chmod(0o600)
        with redirect_stdout(io.StringIO()) as missing:
            self.assertEqual(run(["--config", str(self.config_path), "admin", "credential-stage"]), 2)
        self.assertIn("credential_arguments_missing", missing.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run([
                "--config", str(self.config_path), "admin", "credential-stage",
                "--subject-id", "sub_synthetic", "--device-id", "dev_synthetic",
                "--key-id", "key_second", "--secret-ref", str(second_secret),
                "--reason-code", "rotation", "--run-id", "run_stage", "--now-ms", "5",
            ]), 0)
            self.assertEqual(run([
                "--config", str(self.config_path), "admin", "credential-revoke",
                "--key-id", "key_first", "--reason-code", "rotation_complete",
                "--run-id", "run_revoke", "--now-ms", "10",
            ]), 0)
        self.assertIn('"status":"staged"', output.getvalue())
        self.assertIn('"status":"revoked"', output.getvalue())

    def test_append_only_audit_chain_and_cli_boundary(self):
        connection = connect(self.configuration)
        try:
            first = record_change(
                connection, self.configuration, "deployment", "release_1", "m3_activation", "run_1",
                now=datetime(2030, 1, 1, tzinfo=timezone.utc),
            )
            second = record_change(
                connection, self.configuration, "credential_change", "key_synthetic", "rotation_test", "run_2",
                now=datetime(2030, 1, 2, tzinfo=timezone.utc),
            )
            rows = tuple(connection.execute("SELECT audit_id, previous_hash, entry_hash FROM audit_events ORDER BY sequence"))
        finally:
            connection.close()
        self.assertEqual((rows[0][0], rows[1][0]), (first, second))
        self.assertIsNone(rows[0][1])
        self.assertEqual(rows[1][1], rows[0][2])
        with self.assertRaisesRegex(AuditError, "audit_fields_invalid"):
            connection = connect(self.configuration)
            try:
                record_change(connection, self.configuration, "delete", "bad value", "x", "y")
            finally:
                connection.close()
        with redirect_stdout(io.StringIO()) as missing:
            self.assertEqual(run(["--config", str(self.config_path), "admin", "audit-change"]), 2)
        self.assertIn("audit_arguments_missing", missing.getvalue())
    def test_processor_heartbeat_and_loop(self):
        heartbeat(self.configuration, 1234)
        connection = connect(self.configuration)
        try:
            self.assertEqual(tuple(connection.execute(
                "SELECT last_success_ms, status FROM service_heartbeats WHERE service='processor'"
            ).fetchone()), (1234, "healthy"))
        finally:
            connection.close()
        stop = Event()

        def one_wait(_interval):
            stop.set()
            return True

        stop.wait = one_wait
        serve(self.configuration, stop, 0.01)

    def test_cli_backup_actions_and_boundaries(self):
        archive = self.root / "snapshot.gpg"
        output = io.StringIO()
        with patch("hermodr.backup.subprocess.run", self.copy_runner), redirect_stdout(output):
            self.assertEqual(run([
                "--config", str(self.config_path), "admin", "backup-create",
                "--archive", str(archive), "--passphrase-file", str(self.passphrase),
            ]), 0)
            self.assertEqual(run([
                "--config", str(self.config_path), "admin", "backup-verify",
                "--archive", str(archive), "--passphrase-file", str(self.passphrase),
            ]), 0)
            self.assertEqual(run([
                "--config", str(self.config_path), "admin", "restore-test",
                "--archive", str(archive), "--passphrase-file", str(self.passphrase),
            ]), 0)
        self.assertEqual(output.getvalue().count('"status":"ok"'), 3)
        with redirect_stdout(io.StringIO()) as missing:
            self.assertEqual(run(["--config", str(self.config_path), "admin", "backup-create"]), 2)
        self.assertIn("backup_arguments_missing", missing.getvalue())
        with redirect_stdout(io.StringIO()) as invalid:
            self.assertEqual(run([
                "--config", str(self.config_path), "processor", "--interval-seconds", "0",
            ]), 2)
        self.assertIn("processor_interval_invalid", invalid.getvalue())
        with redirect_stdout(io.StringIO()) as check:
            self.assertEqual(run(["--config", str(self.config_path), "processor", "--check"]), 0)
        self.assertIn('"status":"ready"', check.getvalue())


class DeploymentArtifactTests(unittest.TestCase):
    def test_operational_artifacts_are_private_persistent_and_complete(self):
        receiver = (ROOT / "deploy/systemd/hermodr-receiver.service").read_text(encoding="utf-8")
        processor = (ROOT / "deploy/systemd/hermodr-processor.service").read_text(encoding="utf-8")
        timer = (ROOT / "deploy/systemd/hermodr-metrics-export.timer").read_text(encoding="utf-8")
        gateway = (ROOT / "deploy/fenrir/hermodr-location.conf").read_text(encoding="utf-8")
        rules = (ROOT / "deploy/monitoring/hermodr-recording-alerts.yml").read_text(encoding="utf-8")
        self.assertIn("Restart=on-failure", receiver)
        self.assertIn("ProtectSystem=strict", receiver)
        self.assertIn("processor --interval-seconds", processor)
        self.assertIn("Persistent=true", timer)
        self.assertIn("location = /v1/owntracks", gateway)
        self.assertNotIn("$request_body", gateway)
        for alert in (
            "HermodrDurableIngestUnavailable", "HermodrIngestErrors", "HermodrIngestLatency",
            "HermodrDatabaseErrors", "HermodrReportStale", "HermodrDiskPressure",
            "HermodrDatabaseIntegrity", "HermodrBackupStale", "HermodrProcessorBacklog",
            "HermodrDeadLetters", "HermodrRecomputeBacklog", "HermodrRetentionOverdue",
            "HermodrOutboxConsumerLag",
        ):
            self.assertIn(alert, rules)
        exporter = (ROOT / "deploy/systemd/hermodr-export-metrics").read_text(encoding="utf-8")
        self.assertIn("hermodr_receiver_ready 1", exporter)
        backup_unit = (ROOT / "deploy/systemd/hermodr-backup.service").read_text(encoding="utf-8")
        backup_script = (ROOT / "deploy/systemd/hermodr-backup").read_text(encoding="utf-8")
        self.assertIn("RequiresMountsFor=/mnt/saga/Hermodr", backup_unit)
        self.assertIn("ReadWritePaths=/var/lib/hermodr /var/backups/hermodr /mnt/saga/Hermodr", backup_unit)
        self.assertIn('cp "$archive" "$temporary"', backup_script)
        self.assertIn('mv "$temporary" "$offhost_archive"', backup_script)
        self.assertEqual(backup_script.count('restore-test --archive "$offhost_archive"'), 1)
        annotator = (ROOT / "deploy/monitoring/hermodr-annotate").read_text(encoding="utf-8")
        self.assertIn('"dashboardUID":"hermodr-operations"', annotator)
        mail_trust = (ROOT / "deploy/monitoring/grafana-mail-trust.Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("FROM grafana/grafana:11.4.0", mail_trust)
        self.assertIn("RUN update-ca-certificates", mail_trust)
        self.assertTrue(mail_trust.rstrip().endswith("USER grafana"))
        dashboard = json.loads((ROOT / "deploy/monitoring/hermodr-dashboard.json").read_text(encoding="utf-8"))
        rows = [panel["title"] for panel in dashboard["panels"] if panel["type"] == "row"]
        self.assertEqual(rows, ["Ingestion", "Freshness", "Queue and processor", "Storage and recovery"])


if __name__ == "__main__":
    unittest.main()
