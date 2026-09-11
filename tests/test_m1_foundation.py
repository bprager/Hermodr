from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import hermodr
from hermodr import build
from hermodr.cli import run
from hermodr.clock import SystemClock, unix_milliseconds
from hermodr.config import Configuration, ConfigurationError, load_configuration
from hermodr.contracts import CONTRACT_ROOT, load_schema, validate
from hermodr.database import (
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
)
from hermodr.enums import AuditAction, ErrorCode, JobState, METRIC_LABEL_VALUES, QualityFlag
from hermodr.identifiers import canonical_json, deterministic_id, idempotency_key, sortable_id, source_digest
from hermodr.logging import SafeLogger
from hermodr.metrics import MetricRegistry, reconstruct_critical_metrics
from hermodr.repository import NotFoundError, Repository
import hermodr_build_backend
from tools.static_analysis import Issue, analyze_source, python_files, run as static_run


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
        production = Configuration("production", self.database_path, "127.0.0.1", "INFO", 1000)
        with patch("hermodr.database.sqlite_version_supported", return_value=False):
            with self.assertRaisesRegex(DatabaseError, "sqlite_version_unsupported"):
                assert_runtime_supported(production)
            with self.assertRaisesRegex(DatabaseError, "sqlite_version_unsupported"):
                connect(production)
            connection = connect(production, allow_unsafe_production=True)
            connection.close()
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
