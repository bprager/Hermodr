from __future__ import annotations

import base64
from contextlib import redirect_stdout
from datetime import datetime, timezone
import http.client
import io
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from hermodr.cli import run
from hermodr.config import Configuration, ConfigurationError, load_configuration
from hermodr.database import connect, migrate
from hermodr.metrics import MetricRegistry
from hermodr.receiver import (
    Authenticator,
    InflightGate,
    IngestRequest,
    ReceiverApplication,
    ReceiverError,
    ReceiverService,
    load_protected_secret,
    normalized_content_type,
    parse_basic,
    parse_payload,
    user_agent_family,
)
from hermodr.repository import Repository


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
NOW_SECONDS = int(NOW.timestamp())


class FixedClock:
    def now(self):
        return NOW


class ReceiverTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "data" / "events.sqlite"
        self.dedupe_path = self.secret("dedupe", b"d" * 32)
        self.first_secret = self.secret("first", b"first-secret-value-000000000")
        self.rotated_secret = self.secret("rotated", b"rotated-secret-value-000000")
        self.second_secret = self.secret("second", b"second-secret-value-00000000")
        self.configuration = Configuration(
            "test", self.database_path, "127.0.0.1", "INFO", 1000,
            "127.0.0.1", 0, 0, 1024, 0, 100, 300, self.dedupe_path,
        )
        connection = connect(self.configuration)
        migrate(connection)
        repository = Repository(connection)
        repository.add_subject("sub_00000000", "policy_1", 1)
        repository.add_device("sub_00000000", "dev_00000000", 1, "S1")
        repository.add_credential("sub_00000000", "dev_00000000", "key_first", str(self.first_secret), 1)
        repository.add_credential("sub_00000000", "dev_00000000", "key_rotated", str(self.rotated_secret), 1)
        repository.add_subject("sub_11111111", "policy_2", 1)
        repository.add_device("sub_11111111", "dev_11111111", 1, "S2")
        repository.add_credential("sub_11111111", "dev_11111111", "key_second", str(self.second_secret), 1)
        repository.add_credential("sub_00000000", "dev_00000000", "key_expired", str(self.first_secret), 1, 2)
        connection.close()
        self.output = io.StringIO()
        self.service = ReceiverService(self.configuration, self.output, clock=FixedClock())

    def tearDown(self):
        self.temporary.cleanup()

    def secret(self, name: str, value: bytes) -> Path:
        path = self.root / name
        path.write_bytes(value)
        path.chmod(0o600)
        return path

    @staticmethod
    def authorization(key: str = "key_first", secret: bytes = b"first-secret-value-000000000") -> str:
        return "Basic " + base64.b64encode(key.encode() + b":" + secret).decode()

    @staticmethod
    def payload(**changes):
        value = {"_type": "location", "lat": 0.0, "lon": 0.0, "tid": "S1", "tst": NOW_SECONDS}
        value.update(changes)
        return value

    def request(self, payload=None, **changes):
        body = json.dumps(self.payload() if payload is None else payload).encode()
        values = {
            "authorization": self.authorization(),
            "content_type": "application/json; charset=utf-8",
            "content_encoding": None,
            "body": body,
            "request_id": "req_0001",
            "user_agent": "OwnTracks/iOS",
        }
        values.update(changes)
        return IngestRequest(**values)

    def counts(self):
        connection = connect(self.configuration)
        try:
            return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("raw_events", "processing_jobs", "quarantine"))
        finally:
            connection.close()


class ConfigurationAndSecretTests(ReceiverTestCase):
    def test_m2_configuration_and_fingerprint(self):
        config_path = self.root / "config.json"
        values = {
            "environment": "test", "database_path": str(self.database_path), "operations_bind": "127.0.0.1",
            "log_level": "INFO", "busy_timeout_ms": 1000, "public_bind": "0.0.0.0", "public_port": 8082,
            "operations_port": 8083, "max_body_bytes": 2048, "disk_floor_bytes": 0, "drain_timeout_ms": 10,
            "max_future_seconds": 12, "dedupe_key_path": str(self.dedupe_path),
        }
        config_path.write_text(json.dumps(values), encoding="utf-8")
        loaded = load_configuration(config_path)
        self.assertEqual((loaded.public_bind, loaded.public_port, loaded.operations_port), ("0.0.0.0", 8082, 8083))
        self.assertNotIn(str(self.dedupe_path), loaded.fingerprint)

    def test_every_m2_configuration_boundary(self):
        base = {
            "environment": "test", "database_path": str(self.database_path), "operations_bind": "127.0.0.1",
            "log_level": "INFO", "busy_timeout_ms": 1000,
        }
        cases = (
            ({"public_bind": 1}, "public_bind_invalid"), ({"public_bind": ""}, "public_bind_invalid"),
            ({"public_port": True}, "public_port_invalid"), ({"public_port": 65536}, "public_port_invalid"),
            ({"operations_port": -1}, "operations_port_invalid"),
            ({"environment": "production", "public_port": 0}, "listener_port_invalid"),
            ({"public_port": 8080, "operations_port": 8080}, "listener_collision"),
            ({"max_body_bytes": 0}, "max_body_bytes_invalid"), ({"max_body_bytes": 1048577}, "max_body_bytes_invalid"),
            ({"disk_floor_bytes": -1}, "disk_floor_bytes_invalid"), ({"drain_timeout_ms": 0}, "drain_timeout_invalid"),
            ({"max_future_seconds": 86401}, "max_future_seconds_invalid"),
            ({"dedupe_key_path": ""}, "dedupe_key_path_invalid"), ({"dedupe_key_path": 1}, "dedupe_key_path_invalid"),
        )
        path = self.root / "config.json"
        for change, error in cases:
            with self.subTest(error=error):
                path.write_text(json.dumps(base | change), encoding="utf-8")
                with self.assertRaisesRegex(ConfigurationError, error):
                    load_configuration(path)

    def test_protected_secret_and_basic_parser_boundaries(self):
        self.assertEqual(load_protected_secret(self.dedupe_path, minimum_bytes=32), b"d" * 32)
        unsafe = self.secret("unsafe", b"x" * 32)
        unsafe.chmod(0o644)
        directory = self.root / "directory"
        directory.mkdir()
        for path, error in ((unsafe, "secret_permissions_invalid"), (directory, "secret_permissions_invalid"), (self.root / "missing", "secret_unreadable")):
            with self.subTest(error=error), self.assertRaisesRegex(ReceiverError, error):
                load_protected_secret(path, minimum_bytes=32)
        short = self.secret("short", b"x")
        with self.assertRaisesRegex(ReceiverError, "secret_length_invalid"):
            load_protected_secret(short, minimum_bytes=32)
        huge = self.secret("huge", b"x" * 4097)
        with self.assertRaisesRegex(ReceiverError, "secret_length_invalid"):
            load_protected_secret(huge, minimum_bytes=1)
        link = self.root / "link"
        link.symlink_to(self.dedupe_path)
        with self.assertRaisesRegex(ReceiverError, "secret_unreadable"):
            load_protected_secret(link, minimum_bytes=32)
        self.assertEqual(parse_basic(self.authorization())[0], "key_first")
        for value in (None, "Bearer token", "Basic !!!", "Basic " + base64.b64encode(b"no-colon").decode(), "Basic " + base64.b64encode(b"bad key:value").decode(), "Basic " + base64.b64encode(b"key:").decode(), "Basic " + "a" * 9000):
            self.assertIsNone(parse_basic(value))
        self.first_secret.chmod(0o644)
        connection = connect(self.configuration)
        repository = Repository(connection)
        try:
            self.assertIsNone(Authenticator().authenticate(repository, self.authorization(), NOW_SECONDS * 1000))
            self.assertTrue(Authenticator().has_usable_credential(repository, NOW_SECONDS * 1000))
        finally:
            connection.close()

    def test_receiver_requires_dedupe_key(self):
        config = Configuration("test", self.database_path, "127.0.0.1", "INFO", 1000)
        with self.assertRaisesRegex(ReceiverError, "dedupe_key_missing"):
            ReceiverService(config, io.StringIO())


class AuthenticationAndIngestionTests(ReceiverTestCase):
    def test_rotation_authentication_and_subject_isolation(self):
        first = self.service.ingest(self.request())
        rotated = self.service.ingest(self.request(self.payload(tst=NOW_SECONDS - 1), authorization=self.authorization("key_rotated", b"rotated-secret-value-000000")))
        second_payload = self.payload(tid="S2", tst=NOW_SECONDS - 2)
        second = self.service.ingest(self.request(second_payload, authorization=self.authorization("key_second", b"second-secret-value-00000000")))
        self.assertEqual((first.status, rotated.status, second.status), (200, 200, 200))
        connection = connect(self.configuration)
        try:
            subjects = tuple(row[0] for row in connection.execute("SELECT subject_id FROM raw_events ORDER BY captured_at_ms DESC"))
            self.assertEqual(subjects, ("sub_00000000", "sub_00000000", "sub_11111111"))
        finally:
            connection.close()
        mismatch = self.service.ingest(self.request(self.payload(tid="S2", tst=NOW_SECONDS - 3)))
        self.assertEqual((mismatch.status, json.loads(mismatch.body)["error"]), (400, "identity_mismatch"))
        self.assertNotIn("S2", mismatch.body.decode())

    def test_authentication_failures_are_indistinguishable(self):
        cases = (
            None,
            self.authorization(secret=b"wrong-secret-value-000000000"),
            self.authorization("key_missing", b"first-secret-value-000000000"),
            self.authorization("key_expired", b"first-secret-value-000000000"),
        )
        bodies = []
        for authorization in cases:
            response = self.service.ingest(self.request(authorization=authorization))
            self.assertEqual(response.status, 401)
            self.assertIn(("WWW-Authenticate", 'Basic realm="hermodr"'), response.headers)
            bodies.append(response.body)
        self.assertEqual(len(set(bodies)), 1)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_atomic_acceptance_duplicate_and_safe_metadata(self):
        response = self.service.ingest(self.request())
        duplicate = self.service.ingest(self.request(request_id="unsafe request id"))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b"[]")
        self.assertEqual(dict(response.headers)["X-Hermodr-Ingest-ID"], dict(duplicate.headers)["X-Hermodr-Ingest-ID"])
        self.assertRegex(dict(duplicate.headers)["X-Request-ID"], r"^[0-9a-f]{24}$")
        self.assertEqual(self.counts(), (1, 1, 0))
        connection = connect(self.configuration)
        try:
            row = connection.execute(
                "SELECT payload, request_id, key_id, content_type, disposition, content_length, user_agent_family, receiver_build FROM raw_events"
            ).fetchone()
            self.assertEqual(row[0], b'{"_type":"location","lat":0.0,"lon":0.0,"tid":"S1","tst":1893456000}')
            self.assertEqual(tuple(row[2:7]), ("key_first", "application/json", "accepted", len(self.request().body), "owntracks_ios"))
            self.assertTrue(row[7])
            self.assertEqual(row[1], "req_0001")
        finally:
            connection.close()
        rendered = self.service.metrics.render()
        self.assertIn('result="accepted"', rendered)
        self.assertIn('result="duplicate"', rendered)
        self.assertNotIn("first-secret", rendered + self.output.getvalue())
        self.assertNotIn('"lat"', self.output.getvalue())

    def test_future_event_is_durably_quarantined(self):
        response = self.service.ingest(self.request(self.payload(tst=NOW_SECONDS + 301)))
        self.assertEqual(response.status, 200)
        self.assertEqual(self.counts(), (1, 0, 1))
        connection = connect(self.configuration)
        try:
            self.assertEqual(connection.execute("SELECT disposition FROM raw_events").fetchone()[0], "quarantined")
            self.assertEqual(tuple(connection.execute("SELECT reason_code, details_code FROM quarantine").fetchone()), ("contract_invalid", "future_timestamp"))
        finally:
            connection.close()

    def test_commit_failure_is_not_acknowledged_and_rolls_back(self):
        self.service.before_commit = lambda: (_ for _ in ()).throw(sqlite3.OperationalError("SENSITIVE_CANARY"))
        response = self.service.ingest(self.request())
        self.assertEqual((response.status, self.counts()), (503, (0, 0, 0)))
        self.assertNotIn("SENSITIVE_CANARY", response.body.decode() + self.output.getvalue() + self.service.metrics.render())
        self.service.before_commit = None
        self.assertEqual(self.service.ingest(self.request()).status, 200)
        with patch.object(self.service, "_connection", side_effect=sqlite3.OperationalError("secret")):
            self.assertEqual(self.service.ingest(self.request()).status, 503)

    def test_zero_length_publish_is_authenticated_but_not_persisted(self):
        response = self.service.ingest(self.request(body=b""))
        self.assertEqual(response.status, 200)
        self.assertNotIn("X-Hermodr-Ingest-ID", dict(response.headers))
        self.assertEqual(self.counts(), (0, 0, 0))


class ValidationTests(ReceiverTestCase):
    def test_content_boundaries(self):
        self.assertEqual(normalized_content_type("application/vnd.test+json"), "application/vnd.test+json")
        cases = (
            (self.request(content_type=None), 415, "contract_invalid"),
            (self.request(content_type="text/plain"), 415, "contract_invalid"),
            (self.request(content_type="application/json; charset=latin-1"), 415, "contract_invalid"),
            (self.request(content_encoding="gzip"), 415, "contract_invalid"),
            (self.request(body=b"x" * 1025), 413, "contract_invalid"),
        )
        for request, status, code in cases:
            with self.subTest(status=status):
                response = self.service.ingest(request)
                self.assertEqual((response.status, json.loads(response.body)["error"]), (status, code))

    def test_json_shape_type_timestamp_and_coordinates(self):
        malformed = (b"{", b'"scalar"', b'{"_type":"location","tst":NaN}', b"\xff")
        requests = [self.request(body=item) for item in malformed]
        requests.extend((
            self.request([]), self.request({"_type": "unknown", "tst": NOW_SECONDS}),
            self.request({"_type": "status"}), self.request({"_type": "status", "tst": True}),
            self.request({"_type": "status", "tst": -1}),
            self.request({"_type": "status", "tst": 9_223_372_036_854_776}),
            self.request(self.payload(lat=True)), self.request(self.payload(lon=False)),
            self.request(self.payload(lat=91)), self.request(self.payload(lon=-181)),
            self.request({"_type": "transition", "tst": NOW_SECONDS, "lat": 0}),
        ))
        statuses = [self.service.ingest(request).status for request in requests]
        self.assertEqual(statuses[4], 422)
        self.assertEqual(statuses[5], 422)
        self.assertTrue(all(status == 400 for index, status in enumerate(statuses) if index not in {4, 5}))
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_payload_parser_accepts_each_supported_shape(self):
        for value in (
            self.payload(),
            {"_type": "transition", "tst": NOW_SECONDS, "lat": 0.0, "lon": 0.0},
            {"_type": "waypoint", "tst": NOW_SECONDS, "lat": 0.0, "lon": 0.0},
            {"_type": "status", "tst": NOW_SECONDS},
        ):
            self.assertEqual(parse_payload(json.dumps(value).encode())["_type"], value["_type"])
        self.assertEqual(user_agent_family(None), "unknown")
        self.assertEqual(user_agent_family(""), "unknown")
        self.assertEqual(user_agent_family("OwnTracks Android"), "owntracks_other")
        self.assertEqual(user_agent_family("Example"), "other")


class OperationsAndRuntimeTests(ReceiverTestCase):
    def test_startup_and_readiness_boundaries(self):
        self.service.startup_check()
        self.assertEqual(self.service.readiness(), (True, "ready"))
        self.assertIn("hermodr_processing_jobs", self.service.metrics_text())
        with patch("hermodr.receiver.shutil.disk_usage") as usage:
            usage.return_value.free = -1
            self.assertEqual(self.service.readiness(), (False, "disk_floor"))
        with patch("hermodr.receiver.schema_version", return_value=1):
            self.assertEqual(self.service.readiness(), (False, "migration"))
        with patch.object(self.service, "_connection", side_effect=sqlite3.OperationalError("private")):
            self.assertEqual(self.service.readiness(), (False, "storage"))
            with self.assertRaises(sqlite3.OperationalError):
                self.service.metrics_text()
        self.service.gate.drain(0)
        self.assertEqual(self.service.readiness(), (False, "draining"))

    def test_startup_rejects_schema_or_credentials(self):
        with patch("hermodr.receiver.schema_version", return_value=1), self.assertRaisesRegex(ReceiverError, "schema_version_invalid"):
            self.service.startup_check()
        connection = connect(self.configuration)
        connection.execute("UPDATE credentials SET valid_until_ms = 2")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(ReceiverError, "credential_unavailable"):
            self.service.startup_check()
        repository = Repository(connect(self.configuration))
        self.assertFalse(Authenticator().has_usable_credential(repository, NOW_SECONDS * 1000))
        repository._connection.close()

    def test_inflight_gate_waits_and_times_out(self):
        gate = InflightGate()
        entered = Event()
        release = Event()

        def work():
            with gate.request() as accepted:
                self.assertTrue(accepted)
                entered.set()
                release.wait(1)

        thread = Thread(target=work)
        thread.start()
        entered.wait(1)
        self.assertFalse(gate.drain(0))
        release.set()
        thread.join()
        self.assertTrue(gate.drain(0.1))
        with gate.request() as accepted:
            self.assertFalse(accepted)

        waiting_gate = InflightGate()
        entered.clear()
        release.clear()

        def briefly_block():
            with waiting_gate.request():
                entered.set()
                time.sleep(0.02)

        waiting_thread = Thread(target=briefly_block)
        waiting_thread.start()
        entered.wait(1)
        self.assertTrue(waiting_gate.drain(0.5))
        waiting_thread.join()

    def test_metric_counter_histogram_validation(self):
        metrics = MetricRegistry()
        metrics.increment("hermodr_http_requests_total", service="receiver", route="ingest", method="POST", status_class="2xx")
        metrics.observe("hermodr_http_request_duration_seconds", 0.02, service="receiver", route="ingest", method="POST")
        rendered = metrics.render()
        self.assertIn("_bucket", rendered)
        self.assertIn("_sum", rendered)
        self.assertIn("_count", rendered)
        for call in (
            lambda: metrics.increment("hermodr_processing_jobs", state="pending"),
            lambda: metrics.observe("hermodr_processing_jobs", 1, state="pending"),
            lambda: metrics.increment("hermodr_http_requests_total", -1, service="receiver", route="ingest", method="POST", status_class="2xx"),
            lambda: metrics.observe("hermodr_http_request_duration_seconds", -1, service="receiver", route="ingest", method="POST"),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_cli_receiver_check(self):
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps({
            "environment": "test", "database_path": str(self.database_path), "operations_bind": "127.0.0.1",
            "log_level": "INFO", "busy_timeout_ms": 1000, "dedupe_key_path": str(self.dedupe_path),
        }), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run(["--config", str(config_path), "receiver", "--check"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "ready")
        with patch("hermodr.cli.ReceiverApplication") as application, redirect_stdout(io.StringIO()):
            self.assertEqual(run(["--config", str(config_path), "receiver"]), 0)
            application.return_value.serve.assert_called_once()

    def test_dual_listener_http_contract_and_load(self):
        application = ReceiverApplication(self.service)
        application.start()
        public_port = application.public.server_address[1]
        operations_port = application.operations.server_address[1]
        self.assertNotEqual(public_port, operations_port)
        try:
            headers = {"Authorization": self.authorization(), "Content-Type": "application/json", "X-Request-ID": "req_http"}
            durations = []
            for offset in range(25):
                body = json.dumps(self.payload(tst=NOW_SECONDS - offset)).encode()
                started = time.monotonic()
                connection = http.client.HTTPConnection("127.0.0.1", public_port, timeout=2)
                connection.request("POST", "/v1/owntracks", body, headers)
                response = connection.getresponse()
                self.assertEqual((response.status, response.read()), (200, b"[]"))
                durations.append(time.monotonic() - started)
                connection.close()
            elapsed = sum(durations)
            p95 = sorted(durations)[int(len(durations) * 0.95) - 1]
            self.assertGreaterEqual(len(durations) / elapsed, 10)
            self.assertLess(p95, 0.5)
            for path, expected in (("/health/live", 200), ("/health/ready", 200), ("/metrics", 200), ("/missing", 404)):
                connection = http.client.HTTPConnection("127.0.0.1", operations_port, timeout=2)
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                self.assertNotIn(b'"lat"', response.read())
                connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", public_port, timeout=2)
            connection.request("GET", "/health/live")
            self.assertEqual(connection.getresponse().status, 405)
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", public_port, timeout=2)
            connection.request("POST", "/missing", b"{}", headers)
            self.assertEqual(connection.getresponse().status, 404)
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", public_port, timeout=2)
            connection.request("POST", "/v1/owntracks", b"x" * 1025, headers)
            self.assertEqual(connection.getresponse().status, 413)
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", operations_port, timeout=2)
            connection.request("POST", "/metrics", b"")
            self.assertEqual(connection.getresponse().status, 405)
            connection.close()
            raw = socket.create_connection(("127.0.0.1", public_port), timeout=2)
            raw.sendall(b"POST /v1/owntracks HTTP/1.1\r\nHost: localhost\r\nContent-Length: -1\r\n\r\n")
            self.assertIn(b"400", raw.recv(1024))
            raw.close()
            raw = socket.create_connection(("127.0.0.1", public_port), timeout=2)
            raw.sendall(b"POST /v1/owntracks HTTP/1.1\r\nHost: localhost\r\nContent-Length: 5\r\n\r\n{}")
            raw.shutdown(socket.SHUT_WR)
            self.assertIn(b"400", raw.recv(1024))
            raw.close()
        finally:
            self.assertTrue(application.shutdown())

    def test_draining_ingest_and_serve_signal_path(self):
        self.service.gate.drain(0)
        self.assertEqual(self.service.ingest(self.request()).status, 503)
        application = ReceiverApplication(self.service)
        handlers = []

        class ImmediateCondition:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def notify(self):
                return None

            def wait(self):
                handlers[0](None, None)

        def install(_signal, handler):
            handlers.append(handler)
            return signal.SIG_DFL

        import signal
        with patch("hermodr.receiver.Condition", return_value=ImmediateCondition()), patch("hermodr.receiver.signal.signal", side_effect=install), patch.object(application, "start"), patch.object(application, "shutdown", return_value=True):
            application.serve()
        application.public.server_close()
        application.operations.server_close()
