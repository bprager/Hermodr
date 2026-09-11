from __future__ import annotations

import io
import json
import runpy
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from tools.owntracks_spike.cli import DEFAULT_FIXTURES, _summarize, load_fixture, main, run_demo
from tools.owntracks_spike.harness import (
    CaptureRecord,
    CaptureState,
    PayloadSummary,
    authorization_scheme,
    post,
    running_capture,
    summarize_payload,
)
from tools.line_coverage import CoverageFailure, count_lines, enforce, main as coverage_main


class PayloadSummaryTests(unittest.TestCase):
    def test_classifies_every_json_shape_without_retaining_values(self) -> None:
        cases = [
            (b"", ("empty", "none", None, ())),
            (b"\xff", ("invalid_encoding", "unknown", None, ())),
            (b"{", ("invalid_json", "unknown", None, ())),
            (b"[]", ("batch", "multiple", None, ())),
            (b"42", ("scalar", "unknown", None, ())),
            (b"{}", ("object", "missing", None, ())),
            (b'{"_type":"status","tst":true}', ("object", "status", None, ())),
            (
                b'{"_type":"location","tid":"S1","topic":"synthetic","tst":123}',
                ("object", "location", 123, ("tid", "topic")),
            ),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                summary = summarize_payload(body)
                self.assertEqual(
                    (summary.kind, summary.source_type, summary.device_time, summary.identity_fields),
                    expected,
                )
                self.assertEqual(len(summary.digest), 64)
                self.assertNotIn("synthetic", summary.digest)

    def test_authorization_scheme_is_allowlisted(self) -> None:
        self.assertEqual(authorization_scheme(None), "none")
        self.assertEqual(authorization_scheme("Basic abc"), "basic")
        self.assertEqual(authorization_scheme("Bearer abc"), "bearer")
        self.assertEqual(authorization_scheme("Basic"), "malformed")
        self.assertEqual(authorization_scheme(" credential"), "malformed")


class CoverageGateTests(unittest.TestCase):
    def test_counts_trace_lines(self) -> None:
        lines = ["    2:covered\n", ">>>>>> missed\n", "       non-executable\n"]
        self.assertEqual(count_lines(lines), (1, 1))

    def test_threshold_is_strict_and_requires_evidence(self) -> None:
        self.assertEqual(enforce(96, 4), 96.0)
        with self.assertRaises(CoverageFailure):
            enforce(95, 5)
        with self.assertRaises(CoverageFailure):
            enforce(94, 6)
        with self.assertRaises(CoverageFailure):
            enforce(0, 0)

    def test_cli_aggregates_reports(self) -> None:
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.cover"
            second = Path(directory) / "second.cover"
            first.write_text("    1:covered\n", encoding="utf-8")
            second.write_text("    3:covered\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(coverage_main([str(first), str(second)]), 0)
        self.assertIn("100.00% (2/2)", output.getvalue())


class CaptureStateTests(unittest.TestCase):
    def test_response_plan_and_immutable_snapshot(self) -> None:
        state = CaptureState([503])
        self.assertEqual(state.next_status(), 503)
        self.assertEqual(state.next_status(), 200)
        record = CaptureRecord(
            method="POST",
            path="/v1/owntracks",
            content_type="application/json",
            body_length=2,
            authorization_scheme="none",
            payload=PayloadSummary("object", "missing", None, (), "0" * 64),
            response_status=200,
        )
        state.append(record)
        self.assertEqual(state.snapshot(), (record,))
        self.assertEqual(record.safe_dict()["payload"]["kind"], "object")


class HttpHarnessTests(unittest.TestCase):
    def test_success_error_content_type_path_and_authentication(self) -> None:
        with running_capture([202, 503]) as (url, state):
            success = post(
                f"{url}?u=must-not-be-recorded",
                {"_type": "status", "tst": 123},
                basic_auth=("synthetic-user", "synthetic-password"),
                content_type="application/json; charset=utf-8",
            )
            failure = post(url, b"not-json", content_type="text/plain")

        self.assertEqual((success.status, success.body), (202, b"[]"))
        self.assertEqual(failure.status, 503)
        self.assertEqual(json.loads(failure.body), {"error": "synthetic_response"})
        first, second = state.snapshot()
        self.assertEqual(first.path, "/v1/owntracks")
        self.assertNotIn("must-not-be-recorded", first.path)
        self.assertEqual(first.content_type, "application/json")
        self.assertEqual(first.authorization_scheme, "basic")
        self.assertEqual(second.payload.kind, "invalid_json")

    def test_empty_body_missing_content_type_and_invalid_length(self) -> None:
        with running_capture() as (url, state):
            result = post(url, None, content_type=None)
            host = url.removeprefix("http://").split("/", 1)[0]
            invalid_request = (
                f"POST /v1/owntracks HTTP/1.1\r\nHost: {host}\r\n"
                "Content-Length: invalid\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
            negative_request = (
                f"POST /v1/owntracks HTTP/1.1\r\nHost: {host}\r\n"
                "Content-Length: -1\r\nConnection: close\r\n\r\n"
            ).encode("ascii")
            import socket

            socket_host, socket_port = host.rsplit(":", 1)
            with socket.create_connection((socket_host, int(socket_port)), timeout=5) as connection:
                connection.sendall(invalid_request)
                invalid_response = connection.recv(512)
            with socket.create_connection((socket_host, int(socket_port)), timeout=5) as connection:
                connection.sendall(negative_request)
                negative_response = connection.recv(512)

        self.assertEqual(result.status, 200)
        self.assertIn(b"200 OK", invalid_response)
        self.assertIn(b"200 OK", negative_response)
        first, second, third = state.snapshot()
        self.assertEqual((first.content_type, first.payload.kind), ("none", "empty"))
        self.assertEqual(second.body_length, 0)
        self.assertEqual(third.body_length, 0)

    def test_get_is_rejected_and_network_errors_propagate(self) -> None:
        with running_capture() as (url, _state):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url, method="GET"), timeout=5)
            self.assertEqual(error.exception.code, 405)
        with self.assertRaises(URLError):
            post("http://127.0.0.1:1/v1/owntracks", None)

    def test_capture_state_is_safe_under_concurrent_requests(self) -> None:
        request_count = 24
        with running_capture([201] * request_count) as (url, state):
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = tuple(
                    executor.map(
                        lambda sequence: post(url, {"_type": "status", "tst": sequence}),
                        range(request_count),
                    )
                )

        self.assertEqual({result.status for result in results}, {201})
        self.assertEqual(len(state.snapshot()), request_count)


class DemoTests(unittest.TestCase):
    def test_fixture_loader(self) -> None:
        fixture = load_fixture(DEFAULT_FIXTURES, "location-current.json")
        self.assertEqual(fixture["_type"], "location")
        self.assertEqual((fixture["lat"], fixture["lon"]), (0.0, 0.0))

    def test_demo_covers_protocol_matrix_and_redacts_output(self) -> None:
        report = run_demo()
        self.assertEqual(report["request_count"], 11)
        self.assertEqual(report["retry_sequence"], [503, 200])
        self.assertEqual(report["duplicate_deliveries"], 4)
        self.assertTrue(report["out_of_order_observed"])
        self.assertEqual(report["authorization_schemes"], ["basic"])
        self.assertEqual(report["content_types"], ["application/json", "none", "text/plain"])
        self.assertEqual(report["payload_kinds"], {"batch": 1, "empty": 1, "object": 9})
        self.assertEqual(report["source_types"]["location"], 5)
        self.assertEqual(report["source_types"]["transition"], 1)
        self.assertEqual(report["source_types"]["waypoint"], 1)
        serialized = json.dumps(report)
        for forbidden in ("lat", "lon", "synthetic-subject", "synthetic-password", "S1"):
            self.assertNotIn(forbidden, serialized)

    def test_summary_handles_ordered_unique_input(self) -> None:
        records = (
            CaptureRecord(
                method="POST",
                path="/v1/owntracks",
                content_type="application/json",
                body_length=2,
                authorization_scheme="none",
                payload=PayloadSummary("object", "status", 1, (), "a" * 64),
                response_status=200,
            ),
        )
        report = _summarize(records, [200])
        self.assertFalse(report["out_of_order_observed"])
        self.assertEqual(report["duplicate_deliveries"], 0)

    def test_cli_and_module_entry_point(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--fixtures", str(DEFAULT_FIXTURES)]), 0)
        self.assertEqual(json.loads(output.getvalue())["request_count"], 11)

        old_argv = sys.argv
        try:
            sys.argv = ["owntracks-spike", "--fixtures", str(DEFAULT_FIXTURES)]
            with self.assertRaises(SystemExit) as exit_error, redirect_stdout(io.StringIO()):
                runpy.run_module("tools.owntracks_spike.__main__", run_name="__main__")
            self.assertEqual(exit_error.exception.code, 0)
        finally:
            sys.argv = old_argv

    def test_missing_fixture_is_reported(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_fixture(Path("/tmp/nonexistent-hermodr-fixtures"), "missing.json")
