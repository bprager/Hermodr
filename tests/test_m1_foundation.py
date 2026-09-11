from contextlib import redirect_stdout
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import warnings
import zipfile

import hermodr
from hermodr import build
from hermodr.cli import run
from hermodr.clock import SystemClock, unix_milliseconds
from hermodr.config import Configuration, ConfigurationError, load_configuration
from hermodr.contracts import CONTRACT_ROOT, load_schema, validate
from hermodr.database import (
    APPROVED_SQLITE_BUILDS,
    DatabaseError,
    Migration,
    _statements,
    assert_runtime_supported,
    available_migrations,
    connect,
    migrate,
    migrated_database,
    schema_version,
    sqlite_version_supported,
    sqlite_build_approved,
    sqlite_source_id,
)
from hermodr.enums import AuditAction, ErrorCode, JobState, METRIC_LABEL_VALUES, QualityFlag
from hermodr.identifiers import canonical_json, deterministic_id, idempotency_key, sortable_id, source_digest
from hermodr.logging import SafeLogger
from hermodr.metrics import MetricRegistry, reconstruct_critical_metrics
from hermodr.repository import NotFoundError, Repository
import hermodr_build_backend
from tools.static_analysis import Issue, analyze_source, python_files, run as static_run
from tools import sqlite_runtime


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "testdata" / "synthetic" / "contracts"


class FoundationTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config_path = self.root / "config.json"
        self.database_path = self.root / "data" / "hermodr.sqlite"
        self.write_config()

    def tearDown(self):
        self.temporary.cleanup()

    def write_config(self, **changes):
        value = {
            "environment": "test",
            "database_path": str(self.database_path),
            "operations_bind": "127.0.0.1",
            "log_level": "INFO",
            "busy_timeout_ms": 1000,
        }
        value.update(changes)
        self.config_path.write_text(json.dumps(value), encoding="utf-8")
        return value

    def database(self):
        configuration = load_configuration(self.config_path)
        connection = connect(configuration)
        migrate(connection)
        return connection


class ConfigurationTests(FoundationTestCase):
    def test_valid_configuration_and_safe_fingerprint(self):
        configuration = load_configuration(self.config_path)
        self.assertEqual(configuration.environment, "test")
        self.assertFalse(configuration.production)
        self.assertEqual(len(configuration.fingerprint), 16)
        self.write_config(environment="production", operations_bind="::1", log_level="DEBUG", busy_timeout_ms=60_000)
        self.assertTrue(load_configuration(self.config_path).production)

    def test_unreadable_and_nonobject_configuration(self):
        with self.assertRaisesRegex(ConfigurationError, "configuration_unreadable"):
            load_configuration(self.root / "absent")
        self.config_path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "configuration_not_object"):
            load_configuration(self.config_path)
        self.config_path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "configuration_unreadable"):
            load_configuration(self.config_path)

    def test_every_configuration_boundary(self):
        cases = (
            ({"extra": True}, "configuration_fields_invalid"),
            ({"environment": "invalid"}, "environment_invalid"),
            ({"environment": []}, "environment_invalid"),
            ({"database_path": ""}, "database_path_invalid"),
            ({"database_path": 1}, "database_path_invalid"),
            ({"operations_bind": "0.0.0.0"}, "operations_bind_invalid"),
            ({"operations_bind": 1}, "operations_bind_invalid"),
            ({"log_level": "TRACE"}, "log_level_invalid"),
            ({"log_level": []}, "log_level_invalid"),
            ({"busy_timeout_ms": True}, "busy_timeout_invalid"),
            ({"busy_timeout_ms": 99}, "busy_timeout_invalid"),
            ({"busy_timeout_ms": 60_001}, "busy_timeout_invalid"),
        )
        for changes, error in cases:
            with self.subTest(error=error):
                self.write_config(**changes)
                with self.assertRaisesRegex(ConfigurationError, error):
                    load_configuration(self.config_path)
        value = self.write_config()
        del value["log_level"]
        self.config_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "configuration_fields_invalid"):
            load_configuration(self.config_path)


class IdentifierAndBuildTests(unittest.TestCase):
    def test_clock_hashes_and_identifiers_are_deterministic(self):
        timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertGreater(SystemClock().now(), timestamp)
        self.assertEqual(unix_milliseconds(timestamp), 1_767_225_600_000)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            unix_milliseconds(datetime(2026, 1, 1))
        payload = {"b": 2, "a": 1}
        self.assertEqual(canonical_json(payload), b'{"a":1,"b":2}')
        self.assertEqual(len(source_digest(payload)), 64)
        self.assertEqual(idempotency_key(b"zero" * 8, "sub_00000000", "dev_00000000", payload), idempotency_key(b"zero" * 8, "sub_00000000", "dev_00000000", payload))
        self.assertEqual(sortable_id("ing", timestamp, b"\0" * 10), "ing_0019b76daa80000000000000000000000")
        self.assertEqual(deterministic_id("obs", "a", "b"), deterministic_id("obs", "a", "b"))
        with self.assertRaisesRegex(ValueError, "prefix"):
            sortable_id("bad-prefix", timestamp, b"\0" * 10)
        with self.assertRaisesRegex(ValueError, "entropy"):
            sortable_id("ing", timestamp, b"short")
        generated = sortable_id("ing", timestamp)
        self.assertTrue(generated.startswith("ing_"))
        with self.assertRaises(ValueError):
            canonical_json(float("nan"))

    def test_build_identity_and_reproducible_wheel(self):
        self.assertEqual(hermodr.__version__, hermodr.BUILD.version)
        self.assertEqual(set(build.BUILD.labels()), {"version", "commit", "schema_version"})
        with patch.dict("os.environ", {"M1_UNRELATED": "ignored"}):
            self.assertEqual(build._safe_environment("MISSING_BUILD_VALUE", "fallback"), "fallback")
        with patch.dict("os.environ", {"TEST_BUILD_VALUE": "unsafe value"}):
            self.assertEqual(build._safe_environment("TEST_BUILD_VALUE", "fallback"), "unknown")
        with patch("hermodr.build.version", side_effect=build.PackageNotFoundError):
            self.assertEqual(build._package_version(), "0.1.0.dev0")
        self.assertEqual(hermodr_build_backend.get_requires_for_build_wheel({}), [])
        with tempfile.TemporaryDirectory() as output:
            name = hermodr_build_backend.build_wheel(output, {}, "unused")
            first = (Path(output) / name).read_bytes()
            self.assertEqual(name, hermodr_build_backend.build_wheel(output))
            self.assertEqual(first, (Path(output) / name).read_bytes())
            with zipfile.ZipFile(Path(output) / name) as wheel:
                members = set(wheel.namelist())
                self.assertTrue(all(item.date_time == (1980, 1, 1, 0, 0, 0) for item in wheel.infolist()))
                self.assertIn("hermodr/cli.py", members)
                self.assertIn("hermodr/_artifact.py", members)
                self.assertIn("hermodr/sql/001_initial.sql", members)
                self.assertIn("hermodr/contracts/v1/observation.schema.json", members)
                self.assertIn(f"{hermodr_build_backend.DIST_INFO}/entry_points.txt", members)
            command = (
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "from hermodr.contracts import load_schema; "
                "from hermodr.database import available_migrations; "
                "from hermodr import BUILD; "
                "assert load_schema('observation')['type'] == 'object'; "
                "assert len(available_migrations()) == 1; "
                "assert BUILD.version == '0.1.0.dev0'"
            )
            completed = subprocess.run([sys.executable, "-I", "-c", command, str(Path(output) / name)], check=False)
            self.assertEqual(completed.returncode, 0)
            with patch.dict("os.environ", {"HERMODR_BUILD_COMMIT": "unsafe value"}):
                hermodr_build_backend.build_wheel(output)
            with zipfile.ZipFile(Path(output) / name) as wheel:
                self.assertIn(b'COMMIT = "unknown"', wheel.read("hermodr/_artifact.py"))
                self.assertIn(f"{hermodr_build_backend.DIST_INFO}/RECORD", members)

    def test_all_bounded_enums_have_unique_safe_values(self):
        for enum_type in (ErrorCode, QualityFlag, JobState, AuditAction):
            values = [item.value for item in enum_type]
            self.assertEqual(len(values), len(set(values)))
            self.assertTrue(all(value.replace("_", "").isalnum() for value in values))
        self.assertIn("unknown", METRIC_LABEL_VALUES["state"])


class ContractTests(unittest.TestCase):
    def test_all_contract_fixtures_validate(self):
        names = {path.name.removesuffix(".schema.json") for path in CONTRACT_ROOT.glob("*.schema.json")}
        self.assertEqual(names, {path.stem for path in FIXTURES.glob("*.json")})
        for name in sorted(names):
            with self.subTest(contract=name):
                fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
                self.assertEqual(validate(load_schema(name), fixture), ())
        with self.assertRaisesRegex(ValueError, "schema_name_invalid"):
            load_schema("../invalid")
        with patch("hermodr.contracts.CONTRACT_ROOT", ROOT / "absent"), patch("hermodr.contracts.resources.files", return_value=ROOT):
            self.assertEqual(load_schema("observation")["type"], "object")

    def test_validator_reports_bounded_paths_and_codes(self):
        schema = {
            "type": "object",
            "required": ["required"],
            "additionalProperties": False,
            "properties": {
                "required": {"type": "string", "minLength": 2, "pattern": "^ok$", "const": "ok", "enum": ["ok"]},
                "number": {"type": "number", "minimum": 0, "maximum": 1},
                "items": {"type": "array", "minItems": 2, "items": {"type": "integer"}},
            },
        }
        codes = {item.code for item in validate(schema, {"required": "x", "number": 2, "items": [True], "extra": None})}
        self.assertEqual(codes, {"const", "enum", "pattern", "minLength", "maximum", "minItems", "type", "additionalProperties"})
        self.assertEqual(validate(schema, []), (validate(schema, [])[0],))
        self.assertEqual(validate({"type": "number"}, float("inf"))[0].code, "type")
        self.assertEqual(validate({"type": "number", "minimum": 1}, 0)[0].code, "minimum")
        self.assertEqual(validate({"type": ["string", "null"]}, None), ())
        missing = validate(schema, {})
        self.assertEqual(missing[0].path, "$.required")


class DatabaseAndRepositoryTests(FoundationTestCase):
    def test_empty_database_migrates_idempotently_with_expected_schema(self):
        configuration = load_configuration(self.config_path)
        with migrated_database(configuration) as connection:
            self.assertEqual(schema_version(connection), 1)
            self.assertEqual(migrate(connection), ())
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            expected = {"subjects", "devices", "credentials", "raw_events", "processing_jobs", "observations", "places", "transitions", "visits", "trips", "coverage_gaps", "record_evidence", "recompute_windows", "outbox_records", "quarantine", "audit_events", "service_heartbeats", "retention_holds", "operational_state", "schema_migrations"}
            self.assertTrue(expected <= tables)
            subject_scoped = expected - {"operational_state", "schema_migrations", "service_heartbeats"}
            for table in subject_scoped:
                columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                self.assertIn("subject_id", columns, table)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_migration_integrity_and_failure_are_bounded(self):
        connection = self.database()
        connection.execute("UPDATE schema_migrations SET checksum = 'changed'")
        connection.commit()
        with self.assertRaisesRegex(DatabaseError, "migration_checksum_mismatch"):
            migrate(connection)
        connection.execute("DELETE FROM schema_migrations")
        connection.commit()
        broken = Migration(2, "002_broken.sql", "INVALID SQL;", "0" * 64)
        with patch("hermodr.database.available_migrations", return_value=(broken,)):
            with self.assertRaisesRegex(DatabaseError, "migration_failed"):
                migrate(connection)
        self.assertFalse(connection.in_transaction)
        with self.assertRaisesRegex(DatabaseError, "migration_incomplete_statement"):
            tuple(_statements("CREATE TABLE incomplete ("))
        connection.close()

    def test_schema_version_before_migration_and_version_gate(self):
        connection = sqlite3.connect(":memory:")
        self.assertEqual(schema_version(connection), 0)
        connection.close()
        self.assertTrue(sqlite_version_supported((3, 51, 3)))
        self.assertFalse(sqlite_version_supported((3, 51, 2)))
        self.assertTrue(sqlite_source_id())
        approved_source = sqlite_runtime.SQLITE_SOURCE_ID
        self.assertTrue(sqlite_build_approved((3, 53, 4), approved_source))
        self.assertFalse(sqlite_build_approved((3, 53, 4), "unapproved"))
        with patch("hermodr.database.sqlite_source_id", return_value=approved_source):
            self.assertTrue(sqlite_build_approved((3, 53, 4)))
        production = Configuration("production", self.database_path, "127.0.0.1", "INFO", 1000)
        with patch("hermodr.database.sqlite_version_supported", return_value=False):
            with self.assertRaisesRegex(DatabaseError, "sqlite_version_unsupported"):
                assert_runtime_supported(production)
            with self.assertRaisesRegex(DatabaseError, "sqlite_version_unsupported"):
                connect(production)
            connection = connect(production, allow_unsafe_production=True)
            connection.close()
        with patch("hermodr.database.sqlite_version_supported", return_value=True), patch("hermodr.database.sqlite_build_approved", return_value=False):
            with self.assertRaisesRegex(DatabaseError, "sqlite_build_unapproved"):
                assert_runtime_supported(production)
        assert_runtime_supported(Configuration("test", self.database_path, "127.0.0.1", "INFO", 1000))

    def test_subject_scoping_and_storage_invariants(self):
        connection = self.database()
        repository = Repository(connection)
        first = repository.add_subject("sub_00000000", "policy_1", 1000)
        second = repository.add_subject("sub_11111111", "policy_2", 1000)
        self.assertEqual(repository.get_subject(first.subject_id), first)
        repository.add_device(first.subject_id, "dev_00000000", 1000)
        repository.add_device(second.subject_id, "dev_11111111", 1000)
        self.assertEqual(repository.get_device(first.subject_id, "dev_00000000").subject_id, first.subject_id)
        with self.assertRaisesRegex(NotFoundError, "device_not_found"):
            repository.get_device(second.subject_id, "dev_00000000")
        with self.assertRaisesRegex(NotFoundError, "subject_not_found"):
            repository.get_subject("sub_22222222")
        repository.add_raw_event(subject_id=first.subject_id, device_id="dev_00000000", ingest_id="ing_00000000000000000000", idempotency_key="0" * 64, source_digest="0" * 64, payload=b"{}", received_at_ms=2000, captured_at_ms=1500, source_type="location")
        self.assertEqual(repository.raw_event_ids(first.subject_id), ("ing_00000000000000000000",))
        self.assertEqual(repository.raw_event_ids(second.subject_id), ())
        with self.assertRaises(sqlite3.IntegrityError):
            repository.add_raw_event(subject_id=second.subject_id, device_id="dev_00000000", ingest_id="ing_11111111111111111111", idempotency_key="1" * 64, source_digest="1" * 64, payload=b"{}", received_at_ms=2000, captured_at_ms=None, source_type="status")
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO observations VALUES ('sub_00000000','obs_bad','dev_00000000','ing_00000000000000000000','1','1',1,1,91.0,0.0,1.0,'[]',?)", ("0" * 64,))
        connection.close()


class ObservabilityTests(FoundationTestCase):
    def test_safe_logger_is_allowlist_only(self):
        output = io.StringIO()
        logger = SafeLogger(output)
        rendered = logger.emit(level="INFO", service="receiver", event="ready", config_fingerprint="0" * 16)
        self.assertEqual(json.loads(rendered)["event"], "ready")
        self.assertEqual(output.getvalue(), rendered + "\n")
        with self.assertRaisesRegex(ValueError, "log_field_not_allowed"):
            logger.emit(level="ERROR", service="receiver", event="failure", payload="SENSITIVE_CANARY")
        with self.assertRaisesRegex(ValueError, "log_fields_required"):
            logger.emit(level="INFO", service="receiver")
        with self.assertRaisesRegex(ValueError, "log_value_not_allowed"):
            logger.emit(level="INFO", service="receiver", event="unbounded")
        with self.assertRaisesRegex(ValueError, "log_value_not_allowed"):
            logger.emit(level="INFO", service="receiver", event="ready", request_id="unsafe value")
        with self.assertRaisesRegex(ValueError, "log_value_not_allowed"):
            logger.emit(level="INFO", service="receiver", event="ready", duration_ms=-1)
        logger.emit(level="INFO", service="receiver", event="ready", duration_ms=1.5, message="service_ready")

    def test_metric_facade_rejects_unbounded_inputs(self):
        registry = MetricRegistry()
        registry.build_info()
        registry.set("hermodr_processing_jobs", 2, state="pending")
        rendered = registry.render()
        self.assertIn("hermodr_build_info", rendered)
        self.assertNotIn("SENSITIVE_CANARY", rendered)
        for call, error in (
            (("unknown_metric", 1, {}), "metric_not_allowed"),
            (("hermodr_processing_jobs", 1, {}), "metric_labels_invalid"),
            (("hermodr_processing_jobs", 1, {"state": "SENSITIVE_CANARY"}), "metric_label_value_invalid"),
            (("hermodr_processing_jobs", 1, {"state": 1}), "metric_label_value_invalid"),
            (("hermodr_quarantine_events", 1, {"reason": "INVALID VALUE"}), "metric_label_value_invalid"),
            (("hermodr_processing_jobs", float("inf"), {"state": "pending"}), "metric_value_invalid"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                call[2]
                registry.set(call[0], call[1], **call[2])
        unsafe = build.BuildInfo("unsafe value", "unknown", "1")
        with self.assertRaisesRegex(ValueError, "metric_label_value_invalid"):
            registry.build_info(unsafe)
        self.assertEqual(MetricRegistry().render(), "")

    def test_critical_metrics_reconstruct_from_database(self):
        connection = self.database()
        repository = Repository(connection)
        repository.add_subject("sub_00000000", "policy_1", 1000)
        repository.add_subject("sub_11111111", "policy_2", 1000)
        connection.execute("UPDATE subjects SET status = 'disabled' WHERE subject_id = 'sub_11111111'")
        repository.add_device("sub_00000000", "dev_00000000", 1000)
        repository.add_raw_event(subject_id="sub_00000000", device_id="dev_00000000", ingest_id="ing_00000000000000000000", idempotency_key="0" * 64, source_digest="0" * 64, payload=b"{}", received_at_ms=8000, captured_at_ms=7000, source_type="location")
        connection.execute("INSERT INTO processing_jobs(subject_id,job_id,state,attempts,next_attempt_ms,created_at_ms,updated_at_ms) VALUES ('sub_00000000','job_0','pending',0,0,5000,5000)")
        connection.execute("INSERT INTO quarantine VALUES ('sub_00000000','qua_0','ing_00000000000000000000','contract_invalid',NULL,'pending',9000,NULL)")
        connection.execute("INSERT INTO operational_state VALUES ('backup_verify_status',1,9000)")
        connection.execute("INSERT INTO operational_state VALUES ('backup_verify_last_success_ms',8000,9000)")
        connection.commit()
        connection.close()
        connection = connect(load_configuration(self.config_path))
        rendered = reconstruct_critical_metrics(connection, 10_000).render()
        self.assertIn('hermodr_processing_jobs{state="pending"} 1', rendered)
        self.assertIn("hermodr_processing_oldest_pending_age_seconds 5", rendered)
        self.assertIn("hermodr_worst_ingest_age_seconds 2", rendered)
        self.assertIn("hermodr_worst_capture_age_seconds 3", rendered)
        self.assertIn('hermodr_quarantine_events{reason="contract_invalid"} 1', rendered)
        self.assertIn('hermodr_backup_status{stage="verify"} 1', rendered)
        self.assertIn("hermodr_sqlite_build_info", rendered)
        connection.close()
        connection_path = self.database_path
        self.database_path = self.root / "empty" / "hermodr.sqlite"
        self.write_config()
        empty = self.database()
        empty_rendered = reconstruct_critical_metrics(empty, 10_000).render()
        self.assertIn("hermodr_worst_ingest_age_seconds 0", empty_rendered)
        empty.close()
        self.database_path = connection_path


class CommandTests(FoundationTestCase):
    def invoke(self, *arguments):
        output = io.StringIO()
        with redirect_stdout(output):
            result = run(["--config", str(self.config_path), *arguments])
        return result, output.getvalue()

    def test_migrate_and_all_command_scaffolds(self):
        result, output = self.invoke("migrate", "up")
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output)["applied"], [1])
        for arguments in (("receiver", "--check"), ("processor", "--check"), ("migrate", "status"), ("admin", "build-info"), ("admin", "metrics")):
            with self.subTest(arguments=arguments):
                result, output = self.invoke(*arguments)
                self.assertEqual(result, 0)
                self.assertTrue(output)

    def test_commands_fail_closed_on_config_schema_and_production(self):
        self.config_path.write_text("{}", encoding="utf-8")
        result, output = self.invoke("migrate", "up")
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output)["status"], "error")
        self.write_config()
        result, output = self.invoke("receiver", "--check")
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output)["error"], "schema_version_invalid")
        self.write_config(environment="production")
        with patch("hermodr.database.sqlite_version_supported", return_value=False):
            result, output = self.invoke("migrate", "up")
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output)["error"], "sqlite_version_unsupported")
        self.write_config()
        with patch("hermodr.cli.connect", side_effect=sqlite3.OperationalError("SENSITIVE_CANARY")):
            result, output = self.invoke("migrate", "up")
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output)["error"], "database_unavailable")
        with patch("hermodr.cli.connect", side_effect=OSError("SENSITIVE_CANARY")):
            result, output = self.invoke("migrate", "up")
        self.assertEqual(result, 2)
        self.assertNotIn("SENSITIVE_CANARY", output)

    def test_module_entry_point(self):
        self.invoke("migrate", "up")
        output = io.StringIO()
        argv = ["hermodr", "--config", str(self.config_path), "admin", "build-info"]
        with patch("sys.argv", argv), redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            runpy.run_module("hermodr", run_name="__main__")
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("schema_version", output.getvalue())


class StaticAnalysisTests(unittest.TestCase):
    def test_security_checks_and_file_discovery(self):
        source = """from module import *
try:
    eval('value')
except:
    subprocess.run(['value'], shell=True)
"""
        issues = analyze_source(source, "synthetic.py")
        self.assertEqual({issue.code for issue in issues}, {"external_dependency", "wildcard_import", "dynamic_execution", "bare_exception", "shell_execution"})
        self.assertEqual(analyze_source("import external_package")[0].code, "external_dependency")
        self.assertTrue(all(isinstance(issue, Issue) and issue.path == "synthetic.py" for issue in issues))
        self.assertEqual(analyze_source("value = 1"), ())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.py"
            second = root / "nested" / "second.py"
            second.parent.mkdir()
            first.write_text("value = 1\n", encoding="utf-8")
            second.write_text("value = 2\n", encoding="utf-8")
            self.assertEqual(python_files((root, first)), (first, second))
            self.assertEqual(static_run([str(root)]), 0)
            second.write_text("exec('value')\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(static_run([str(root)]), 1)
            self.assertIn("dynamic_execution", output.getvalue())

    def test_static_analysis_module_entry_point(self):
        argv = ["static-analysis", "src"]
        with warnings.catch_warnings(), patch("sys.argv", argv), self.assertRaises(SystemExit) as raised:
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("tools.static_analysis", run_name="__main__")
        self.assertEqual(raised.exception.code, 0)


class SQLiteRuntimeSupplyTests(unittest.TestCase):
    def _archive(self, path: Path, entries: dict[str, bytes], *, symlink: str | None = None):
        with tarfile.open(path, "w:gz") as bundle:
            for name, content in entries.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
            if symlink:
                member = tarfile.TarInfo(symlink)
                member.type = tarfile.SYMTYPE
                member.linkname = "target"
                bundle.addfile(member)

    def _evidence(self, **changes):
        values = {
            "version": sqlite_runtime.SQLITE_VERSION,
            "source_id": sqlite_runtime.SQLITE_SOURCE_ID,
            "threadsafety": 3,
            "json_available": True,
            "trusted_schema_default_off": True,
            "secure_delete_default_on": True,
            "load_extension_omitted": True,
        }
        values.update(changes)
        return sqlite_runtime.RuntimeEvidence(**values)

    def test_supply_manifest_matches_enforced_identity(self):
        manifest = json.loads((ROOT / "supply-chain" / "sqlite-runtime.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], sqlite_runtime.SQLITE_VERSION)
        self.assertEqual(manifest["url"], sqlite_runtime.SQLITE_URL)
        self.assertEqual(manifest["archive"], sqlite_runtime.SQLITE_ARCHIVE)
        self.assertEqual(manifest["archive_sha3_256"], sqlite_runtime.SQLITE_ARCHIVE_SHA3_256)
        self.assertEqual(manifest["source_id"], sqlite_runtime.SQLITE_SOURCE_ID)
        version = tuple(int(part) for part in manifest["version"].split("."))
        self.assertEqual(APPROVED_SQLITE_BUILDS[version], manifest["source_id"])
        self.assertEqual(manifest["compile_flags"], list(sqlite_runtime.COMPILE_FLAGS))
        self.assertEqual(manifest["configure_flags"], list(sqlite_runtime.CONFIGURE_FLAGS))

    def test_archive_hash_download_and_bounded_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive.tar.gz"
            archive.write_bytes(b"source")
            digest = hashlib.sha3_256(b"source").hexdigest()
            self.assertEqual(sqlite_runtime.archive_digest(archive), digest)
            with patch.object(sqlite_runtime, "SQLITE_ARCHIVE_SHA3_256", digest):
                sqlite_runtime.verify_archive(archive)
                destination = root / "download.tar.gz"
                with patch.object(sqlite_runtime, "SQLITE_URL", "data:application/octet-stream;base64,c291cmNl"):
                    sqlite_runtime.download_archive(destination)
                self.assertEqual(destination.read_bytes(), b"source")
            with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "checksum_mismatch"):
                sqlite_runtime.verify_archive(archive)
            with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "archive_unreadable"):
                sqlite_runtime.verify_archive(root / "missing")
            destination = root / "wrong-download.tar.gz"
            with patch.object(sqlite_runtime, "SQLITE_ARCHIVE_SHA3_256", "0" * 64), patch.object(sqlite_runtime, "SQLITE_URL", "data:application/octet-stream;base64,c291cmNl"):
                with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "checksum_mismatch"):
                    sqlite_runtime.download_archive(destination)
            self.assertFalse(destination.with_suffix(".gz.partial").exists())
            destination = root / "failed.tar.gz"
            with patch("tools.sqlite_runtime.urllib.request.urlopen", side_effect=urllib.error.URLError("synthetic")):
                with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "download_failed"):
                    sqlite_runtime.download_archive(destination)
            self.assertFalse(destination.with_suffix(".gz.partial").exists())

    def test_safe_archive_extraction_and_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            name = sqlite_runtime.SQLITE_ARCHIVE.removesuffix(".tar.gz")
            archive = root / "valid.tar.gz"
            self._archive(archive, {f"{name}/configure": b"#!/bin/sh\n", f"{name}/sqlite3.c": b"/* synthetic */\n"})
            source = sqlite_runtime.extract_archive(archive, root / "valid")
            self.assertTrue((source / "sqlite3.c").is_file())
            unsafe = root / "unsafe.tar.gz"
            self._archive(unsafe, {"../outside": b"value"})
            with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "archive_unsafe"):
                sqlite_runtime.extract_archive(unsafe, root / "unsafe")
            linked = root / "linked.tar.gz"
            self._archive(linked, {}, symlink=f"{name}/linked")
            with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "archive_unsafe"):
                sqlite_runtime.extract_archive(linked, root / "linked")
            incomplete = root / "incomplete.tar.gz"
            self._archive(incomplete, {f"{name}/sqlite3.c": b"value"})
            with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "layout_invalid"):
                sqlite_runtime.extract_archive(incomplete, root / "incomplete")
            corrupt = root / "corrupt.tar.gz"
            corrupt.write_bytes(b"not-an-archive")
            with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "archive_invalid"):
                sqlite_runtime.extract_archive(corrupt, root / "corrupt")

    def test_execution_environment_and_probe_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            (prefix / "lib").mkdir()
            (prefix / "lib" / "libsqlite3.so.0").write_bytes(b"synthetic")
            with patch.dict("os.environ", {}, clear=True):
                environment = sqlite_runtime.runtime_environment(prefix)
                self.assertEqual(environment["LD_LIBRARY_PATH"], str((prefix / "lib").resolve()))
                self.assertEqual(environment["LD_PRELOAD"], str((prefix / "lib" / "libsqlite3.so.0").resolve()))
            with patch.dict("os.environ", {"LD_LIBRARY_PATH": "/existing", "LD_PRELOAD": "/existing/library.so"}, clear=True):
                environment = sqlite_runtime.runtime_environment(prefix)
                self.assertTrue(environment["LD_LIBRARY_PATH"].endswith(":/existing"))
                self.assertTrue(environment["LD_PRELOAD"].endswith(":/existing/library.so"))
            output = json.dumps(asdict(self._evidence()))
            completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
            with patch("tools.sqlite_runtime.subprocess.run", return_value=completed):
                self.assertEqual(sqlite_runtime.verify_runtime(prefix), self._evidence())
            for result, error in (
                (subprocess.CalledProcessError(1, []), "probe_failed"),
                (subprocess.CompletedProcess([], 0, stdout="not-json", stderr=""), "probe_failed"),
                (subprocess.CompletedProcess([], 0, stdout=json.dumps(asdict(self._evidence(version="0.0.0"))), stderr=""), "identity_mismatch"),
                (subprocess.CompletedProcess([], 0, stdout=json.dumps(asdict(self._evidence(json_available=False))), stderr=""), "capability_mismatch"),
            ):
                with self.subTest(error=error), patch("tools.sqlite_runtime.subprocess.run", side_effect=result if isinstance(result, Exception) else None, return_value=None if isinstance(result, Exception) else result):
                    with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, error):
                        sqlite_runtime.verify_runtime(prefix)
            (prefix / "lib" / "libsqlite3.so.0").unlink()
            with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "runtime_missing"):
                sqlite_runtime.verify_runtime(prefix)
        sqlite_runtime._execute([sys.executable, "-c", "pass"], ROOT)
        with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "build_failed"):
            sqlite_runtime._execute([sys.executable, "-c", "raise SystemExit(1)"], ROOT)

    def test_build_orchestration_existing_and_new(self):
        evidence = self._evidence()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            existing = root / "existing"
            existing.mkdir()
            with patch("tools.sqlite_runtime.verify_runtime", return_value=evidence) as verify:
                self.assertEqual(sqlite_runtime.build_runtime(existing), evidence)
                verify.assert_called_once_with(existing)
            with self.assertRaisesRegex(sqlite_runtime.RuntimeSupplyError, "jobs_invalid"):
                sqlite_runtime.build_runtime(root / "new", jobs=0)
            source = root / "source"
            source.mkdir()
            (source / "configure").write_text("", encoding="utf-8")
            calls = []
            with patch("tools.sqlite_runtime.download_archive") as download, patch("tools.sqlite_runtime.extract_archive", return_value=source), patch("tools.sqlite_runtime._execute", side_effect=lambda *args: calls.append(args)), patch("tools.sqlite_runtime.verify_runtime", return_value=evidence):
                self.assertEqual(sqlite_runtime.build_runtime(root / "new"), evidence)
            self.assertTrue(download.called)
            self.assertEqual(len(calls), 3)
            supplied = root / "supplied.tar.gz"
            supplied.write_bytes(b"synthetic")
            with patch("tools.sqlite_runtime.verify_archive") as verify_archive, patch("tools.sqlite_runtime.extract_archive", return_value=source), patch("tools.sqlite_runtime._execute"), patch("tools.sqlite_runtime.verify_runtime", return_value=evidence):
                self.assertEqual(sqlite_runtime.build_runtime(root / "other", supplied, 16), evidence)
            verify_archive.assert_called_once_with(supplied)

    def test_cli_and_module_entry_point(self):
        evidence = self._evidence()
        output = io.StringIO()
        with patch("tools.sqlite_runtime.verify_runtime", return_value=evidence), redirect_stdout(output):
            self.assertEqual(sqlite_runtime.run(["verify", "--prefix", "/synthetic"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "ok")
        output = io.StringIO()
        with patch("tools.sqlite_runtime.build_runtime", side_effect=sqlite_runtime.RuntimeSupplyError("bounded_failure")), redirect_stdout(output):
            self.assertEqual(sqlite_runtime.run(["build", "--prefix", "/synthetic", "--jobs", "1"]), 2)
        self.assertNotIn("SENSITIVE_CANARY", output.getvalue())
        argv = ["sqlite-runtime", "verify", "--prefix", "/synthetic"]
        with warnings.catch_warnings(), patch("sys.argv", argv), patch("tools.sqlite_runtime.verify_runtime", return_value=evidence), redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            warnings.simplefilter("ignore", RuntimeWarning)
            runpy.run_module("tools.sqlite_runtime", run_name="__main__")
        self.assertEqual(raised.exception.code, 2)
