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
from hermodr.cli import run
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
        self.assertEqual(report.schema_version, 2)
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
            "HermodrReportStale", "HermodrDiskPressure", "HermodrDatabaseIntegrity", "HermodrBackupStale",
        ):
            self.assertIn(alert, rules)
        dashboard = json.loads((ROOT / "deploy/monitoring/hermodr-dashboard.json").read_text(encoding="utf-8"))
        rows = [panel["title"] for panel in dashboard["panels"] if panel["type"] == "row"]
        self.assertEqual(rows, ["Ingestion", "Freshness", "Queue and processor", "Storage and recovery"])


if __name__ == "__main__":
    unittest.main()
