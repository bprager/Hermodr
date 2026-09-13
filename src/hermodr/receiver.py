"""Authenticated, durable OwnTracks receiver with private operations endpoints."""

from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from dataclasses import dataclass
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import stat
from threading import Condition, Lock, Thread
import time
from typing import Callable, Iterator

from .build import BUILD
from .clock import Clock, SystemClock, unix_milliseconds
from .config import Configuration
from .database import connect, schema_version
from .enums import ErrorCode
from .identifiers import canonical_json, idempotency_key, sortable_id, source_digest
from .logging import SafeLogger
from .metrics import MetricRegistry, reconstruct_critical_metrics
from .repository import Credential, Repository


INGEST_PATH = "/v1/owntracks"
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SUPPORTED_TYPES = frozenset({"location", "transition", "waypoint", "status"})


class ReceiverError(RuntimeError):
    """A bounded receiver startup error."""


@dataclass(frozen=True)
class RequestFailure(Exception):
    status: int
    code: str


@dataclass(frozen=True)
class Authentication:
    credential: Credential
    source_tid: str | None


@dataclass(frozen=True)
class IngestRequest:
    authorization: str | None
    content_type: str | None
    content_encoding: str | None
    body: bytes
    request_id: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


def load_protected_secret(path: Path, *, minimum_bytes: int) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            os.close(descriptor)
            raise ReceiverError("secret_permissions_invalid")
        with os.fdopen(descriptor, "rb") as stream:
            value = stream.read(4097).rstrip(b"\r\n")
    except OSError as exc:
        raise ReceiverError("secret_unreadable") from exc
    if not minimum_bytes <= len(value) <= 4096:
        raise ReceiverError("secret_length_invalid")
    return value


def parse_basic(value: str | None) -> tuple[str, bytes] | None:
    if value is None or len(value) > 8192 or not value.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(value[6:], validate=True)
        username, secret = decoded.split(b":", 1)
        key_id = username.decode("ascii")
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    if SAFE_REQUEST_ID.fullmatch(key_id) is None or not secret:
        return None
    return key_id, secret


class Authenticator:
    def authenticate(self, repository: Repository, header: str | None, now_ms: int) -> Authentication | None:
        parsed = parse_basic(header)
        if parsed is None:
            return None
        key_id, presented = parsed
        resolved = repository.credential(key_id, now_ms)
        if resolved is None:
            return None
        credential, source_tid = resolved
        try:
            expected = load_protected_secret(Path(credential.secret_ref), minimum_bytes=24)
        except ReceiverError:
            return None
        if not hmac.compare_digest(presented, expected):
            return None
        return Authentication(credential, source_tid)

    def has_usable_credential(self, repository: Repository, now_ms: int) -> bool:
        for credential, _source_tid in repository.usable_credentials(now_ms):
            try:
                load_protected_secret(Path(credential.secret_ref), minimum_bytes=24)
            except ReceiverError:
                continue
            return True
        return False


class InflightGate:
    def __init__(self):
        self._condition = Condition(Lock())
        self._draining = False
        self._inflight = 0

    @contextmanager
    def request(self) -> Iterator[bool]:
        with self._condition:
            accepted = not self._draining
            if accepted:
                self._inflight += 1
        try:
            yield accepted
        finally:
            if accepted:
                with self._condition:
                    self._inflight -= 1
                    self._condition.notify_all()

    def drain(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            self._draining = True
            while self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    @property
    def draining(self) -> bool:
        with self._condition:
            return self._draining


def normalized_content_type(value: str | None) -> str:
    if value is None:
        raise RequestFailure(415, ErrorCode.CONTRACT_INVALID.value)
    media, *parameters = (part.strip() for part in value.split(";"))
    if not (media == "application/json" or media.startswith("application/") and media.endswith("+json")):
        raise RequestFailure(415, ErrorCode.CONTRACT_INVALID.value)
    for parameter in parameters:
        if parameter.lower() != "charset=utf-8":
            raise RequestFailure(415, ErrorCode.CONTRACT_INVALID.value)
    return media


def parse_payload(body: bytes) -> dict[str, object]:
    try:
        value = json.loads(
            body.decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non_finite")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RequestFailure(400, ErrorCode.CONTRACT_INVALID.value) from exc
    if isinstance(value, list):
        raise RequestFailure(422, ErrorCode.CONTRACT_INVALID.value)
    if not isinstance(value, dict):
        raise RequestFailure(400, ErrorCode.CONTRACT_INVALID.value)
    source_type = value.get("_type")
    if source_type not in SUPPORTED_TYPES:
        raise RequestFailure(422, ErrorCode.UNSUPPORTED_MESSAGE_TYPE.value)
    timestamp = value.get("tst")
    if "tst" not in value and source_type == "status":
        timestamp = None
    elif isinstance(timestamp, bool) or not isinstance(timestamp, int) or not 0 <= timestamp <= 9_223_372_036_854_775:
        raise RequestFailure(400, ErrorCode.CONTRACT_INVALID.value)
    if source_type in {"location", "transition", "waypoint"}:
        latitude = value.get("lat")
        longitude = value.get("lon")
        if (
            isinstance(latitude, bool) or not isinstance(latitude, (int, float))
            or isinstance(longitude, bool) or not isinstance(longitude, (int, float))
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180
        ):
            raise RequestFailure(400, ErrorCode.CONTRACT_INVALID.value)
    return value


def user_agent_family(value: str | None) -> str:
    if value is None or not value:
        return "unknown"
    normalized = value.lower()
    if "owntracks" in normalized and ("ios" in normalized or "iphone" in normalized):
        return "owntracks_ios"
    if "owntracks" in normalized:
        return "owntracks_other"
    return "other"


class ReceiverService:
    def __init__(
        self,
        configuration: Configuration,
        output,
        *,
        clock: Clock | None = None,
        metrics: MetricRegistry | None = None,
        before_commit: Callable[[], None] | None = None,
    ):
        if configuration.dedupe_key_path is None:
            raise ReceiverError("dedupe_key_missing")
        self.configuration = configuration
        self.clock = clock or SystemClock()
        self.metrics = metrics or MetricRegistry()
        self.logger = SafeLogger(output)
        self.gate = InflightGate()
        self.authenticator = Authenticator()
        self.dedupe_key = load_protected_secret(configuration.dedupe_key_path, minimum_bytes=32)
        self.before_commit = before_commit

    def _connection(self) -> sqlite3.Connection:
        return connect(self.configuration)

    def startup_check(self) -> None:
        connection = self._connection()
        try:
            if schema_version(connection) != int(BUILD.schema_version):
                raise ReceiverError("schema_version_invalid")
            if not self.authenticator.has_usable_credential(Repository(connection), unix_milliseconds(self.clock.now())):
                raise ReceiverError("credential_unavailable")
        finally:
            connection.close()

    def ingest(self, request: IngestRequest) -> Response:
        started = time.monotonic()
        request_id = request.request_id if request.request_id and SAFE_REQUEST_ID.fullmatch(request.request_id) else os.urandom(12).hex()
        status = 500
        source_type = "unknown"
        with self.gate.request() as admitted:
            if not admitted:
                response = self._error(503, ErrorCode.DATABASE_BUSY.value, request_id)
                self._record_http("ingest", "POST", response.status, started)
                return response
            connection: sqlite3.Connection | None = None
            try:
                connection = self._connection()
                repository = Repository(connection)
                now = self.clock.now()
                now_ms = unix_milliseconds(now)
                authentication = self.authenticator.authenticate(repository, request.authorization, now_ms)
                if authentication is None:
                    self.metrics.increment("hermodr_auth_failures_total", reason=ErrorCode.AUTH_INVALID.value)
                    response = self._error(401, ErrorCode.AUTH_INVALID.value, request_id, authenticate=True)
                    status = response.status
                    return response
                if len(request.body) > self.configuration.max_body_bytes:
                    raise RequestFailure(413, ErrorCode.CONTRACT_INVALID.value)
                if request.content_encoding not in {None, "", "identity"}:
                    raise RequestFailure(415, ErrorCode.CONTRACT_INVALID.value)
                content_type = normalized_content_type(request.content_type)
                if not request.body:
                    status = 200
                    return Response(200, b"[]", (("Content-Type", "application/json"), ("X-Request-ID", request_id)))
                payload = parse_payload(request.body)
                source_type = str(payload["_type"])
                tid = payload.get("tid")
                if tid is not None and tid != authentication.source_tid:
                    raise RequestFailure(400, ErrorCode.IDENTITY_MISMATCH.value)
                canonical = canonical_json(payload)
                ingest_id = sortable_id("ing", now)
                captured_at_ms = (
                    int(payload["tst"]) * 1000
                    if "tst" in payload
                    else None
                )
                disposition = (
                    "quarantined"
                    if captured_at_ms is not None
                    and captured_at_ms > now_ms + self.configuration.max_future_seconds * 1000
                    else "accepted"
                )
                storage_started = time.monotonic()
                persisted = repository.persist_ingest(
                    subject_id=authentication.credential.subject_id,
                    device_id=authentication.credential.device_id,
                    ingest_id=ingest_id,
                    idempotency_key=idempotency_key(
                        self.dedupe_key,
                        authentication.credential.subject_id,
                        authentication.credential.device_id,
                        payload,
                    ),
                    source_digest=source_digest(payload),
                    payload=canonical,
                    received_at_ms=now_ms,
                    captured_at_ms=captured_at_ms,
                    source_type=source_type,
                    disposition=disposition,
                    request_id=request_id,
                    key_id=authentication.credential.key_id,
                    content_type=content_type,
                    content_length=len(request.body),
                    user_agent_family=user_agent_family(request.user_agent),
                    receiver_build=BUILD.version,
                    quarantine_reason=ErrorCode.CONTRACT_INVALID.value if disposition == "quarantined" else None,
                    before_commit=self.before_commit,
                )
                self.metrics.observe("hermodr_storage_operation_duration_seconds", time.monotonic() - storage_started, operation="commit")
                self.metrics.increment("hermodr_storage_operations_total", operation="commit", result="success")
                self.metrics.increment("hermodr_ingest_events_total", result=persisted.result, source_type=source_type)
                self.logger.emit(
                    level="INFO", service="receiver", event="ingest", message="request_completed",
                    result=persisted.result, request_id=request_id, ingest_id=persisted.ingest_id,
                    key_id=authentication.credential.key_id,
                )
                status = 200
                return Response(
                    200,
                    b"[]",
                    (("Content-Type", "application/json"), ("X-Request-ID", request_id), ("X-Hermodr-Ingest-ID", persisted.ingest_id)),
                )
            except RequestFailure as exc:
                self.metrics.increment("hermodr_validation_failures_total", reason=exc.code)
                self.metrics.increment("hermodr_ingest_events_total", result="rejected", source_type=source_type)
                status = exc.status
                return self._error(exc.status, exc.code, request_id)
            except (OSError, sqlite3.Error):
                if "storage_started" in locals():
                    self.metrics.observe("hermodr_storage_operation_duration_seconds", time.monotonic() - storage_started, operation="commit")
                self.metrics.increment("hermodr_storage_operations_total", operation="commit", result="failed")
                self.metrics.increment("hermodr_ingest_events_total", result="failed", source_type=source_type)
                status = 503
                return self._error(503, ErrorCode.DATABASE_ERROR.value, request_id)
            finally:
                if connection is not None:
                    connection.close()
                self._record_http("ingest", "POST", status, started)

    def _record_http(self, route: str, method: str, status: int, started: float) -> None:
        status_class = f"{status // 100}xx"
        self.metrics.increment(
            "hermodr_http_requests_total", service="receiver", route=route, method=method, status_class=status_class,
        )
        self.metrics.observe(
            "hermodr_http_request_duration_seconds", time.monotonic() - started,
            service="receiver", route=route, method=method,
        )

    @staticmethod
    def _error(status: int, code: str, request_id: str, authenticate: bool = False) -> Response:
        headers = [("Content-Type", "application/json"), ("X-Request-ID", request_id)]
        if authenticate:
            headers.append(("WWW-Authenticate", 'Basic realm="hermodr"'))
        return Response(status, canonical_json({"error": code}), tuple(headers))

    def readiness(self) -> tuple[bool, str]:
        if self.gate.draining:
            return False, "draining"
        try:
            if shutil.disk_usage(self.configuration.database_path.parent).free < self.configuration.disk_floor_bytes:
                return False, "disk_floor"
            connection = self._connection()
            try:
                if schema_version(connection) != int(BUILD.schema_version):
                    return False, "migration"
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO operational_state VALUES ('readiness_probe', 1, 0) "
                    "ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value"
                )
                connection.execute("SELECT state_value FROM operational_state WHERE state_key = 'readiness_probe'").fetchone()
                reconstruct_critical_metrics(connection, unix_milliseconds(self.clock.now()))
                connection.rollback()
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            return False, "storage"
        return True, "ready"

    def metrics_text(self) -> str:
        connection = self._connection()
        try:
            durable = reconstruct_critical_metrics(connection, unix_milliseconds(self.clock.now())).render()
        finally:
            connection.close()
        return durable + self.metrics.render()


class ReceiverApplication:
    def __init__(self, service: ReceiverService):
        self.service = service
        self.public = ThreadingHTTPServer(
            (service.configuration.public_bind, service.configuration.public_port), self._public_handler()
        )
        self.operations = ThreadingHTTPServer(
            (service.configuration.operations_bind, service.configuration.operations_port), self._operations_handler()
        )
        self._threads: list[Thread] = []

    @staticmethod
    def _send(handler: BaseHTTPRequestHandler, response: Response) -> None:
        handler.send_response(response.status)
        for key, value in response.headers:
            handler.send_header(key, value)
        handler.send_header("Content-Length", str(len(response.body)))
        handler.end_headers()
        handler.wfile.write(response.body)

    def _public_handler(self):
        service = self.service

        class PublicHandler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:
                started = time.monotonic()
                request_id = self.headers.get("X-Request-ID")
                safe_id = request_id if request_id and SAFE_REQUEST_ID.fullmatch(request_id) else os.urandom(12).hex()
                if self.path != INGEST_PATH:
                    response = ReceiverService._error(404, ErrorCode.CONTRACT_INVALID.value, safe_id)
                    service._record_http("other", "POST", response.status, started)
                    ReceiverApplication._send(self, response)
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                    if length < 0:
                        raise ValueError
                except ValueError:
                    self._reject(400, safe_id, started)
                    return
                if length > service.configuration.max_body_bytes:
                    self._reject(413, safe_id, started)
                    return
                body = self.rfile.read(length)
                if len(body) != length:
                    self._reject(400, safe_id, started)
                    return
                response = service.ingest(IngestRequest(
                    self.headers.get("Authorization"), self.headers.get("Content-Type"),
                    self.headers.get("Content-Encoding"), body, safe_id,
                    self.headers.get("User-Agent"),
                ))
                ReceiverApplication._send(self, response)

            def _reject(self, status: int, request_id: str, started: float) -> None:
                service.metrics.increment("hermodr_validation_failures_total", reason=ErrorCode.CONTRACT_INVALID.value)
                service.metrics.increment("hermodr_ingest_events_total", result="rejected", source_type="unknown")
                service._record_http("ingest", "POST", status, started)
                ReceiverApplication._send(self, ReceiverService._error(status, ErrorCode.CONTRACT_INVALID.value, request_id))

            def do_GET(self) -> None:
                started = time.monotonic()
                service._record_http("other", "GET", 405, started)
                ReceiverApplication._send(self, Response(405, b"", (("Allow", "POST"),)))

        return PublicHandler

    def _operations_handler(self):
        service = self.service

        class OperationsHandler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_GET(self) -> None:
                started = time.monotonic()
                if self.path == "/health/live":
                    route = "live"
                    body = canonical_json({"build": BUILD.version, "status": "live"})
                    response = Response(200, body, (("Content-Type", "application/json"),))
                elif self.path == "/health/ready":
                    route = "ready"
                    ready, component = service.readiness()
                    body = canonical_json({"build": BUILD.version, "component": component, "status": "ready" if ready else "not_ready"})
                    response = Response(200 if ready else 503, body, (("Content-Type", "application/json"),))
                elif self.path == "/metrics":
                    route = "metrics"
                    response = Response(200, service.metrics_text().encode(), (("Content-Type", "text/plain; version=0.0.4"),))
                else:
                    route = "other"
                    response = Response(404, b"")
                service._record_http(route, "GET", response.status, started)
                ReceiverApplication._send(self, response)

            def do_POST(self) -> None:
                started = time.monotonic()
                service._record_http("other", "POST", 405, started)
                ReceiverApplication._send(self, Response(405, b"", (("Allow", "GET"),)))

        return OperationsHandler

    def start(self) -> None:
        self.service.startup_check()
        for server, name in ((self.public, "hermodr-public"), (self.operations, "hermodr-operations")):
            thread = Thread(target=server.serve_forever, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def shutdown(self) -> bool:
        self.public.shutdown()
        drained = self.service.gate.drain(self.service.configuration.drain_timeout_ms / 1000)
        self.operations.shutdown()
        self.public.server_close()
        self.operations.server_close()
        for thread in self._threads:
            thread.join(timeout=1)
        return drained

    def serve(self) -> None:
        stopped = Condition()

        def stop(_signum, _frame) -> None:
            with stopped:
                stopped.notify()

        previous = {item: signal.signal(item, stop) for item in (signal.SIGINT, signal.SIGTERM)}
        self.start()
        try:
            with stopped:
                stopped.wait()
        finally:
            self.shutdown()
            for item, handler in previous.items():
                signal.signal(item, handler)
