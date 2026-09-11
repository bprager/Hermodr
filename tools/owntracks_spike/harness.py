"""Privacy-safe HTTP capture primitives used by the M0 protocol spike."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PayloadSummary:
    """Non-sensitive facts derived from a request body."""

    kind: str
    source_type: str
    device_time: int | None
    identity_fields: tuple[str, ...]
    digest: str


@dataclass(frozen=True)
class CaptureRecord:
    """Allowlisted request metadata; the raw payload is never retained."""

    method: str
    path: str
    content_type: str
    body_length: int
    authorization_scheme: str
    payload: PayloadSummary
    response_status: int

    def safe_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable safe representation."""

        return asdict(self)


@dataclass(frozen=True)
class ReplayResult:
    """HTTP outcome observed by the replay client."""

    status: int
    body: bytes


def summarize_payload(body: bytes) -> PayloadSummary:
    """Classify a body without retaining location or identity values."""

    digest = hashlib.sha256(body).hexdigest()
    if not body:
        return PayloadSummary("empty", "none", None, (), digest)

    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        return PayloadSummary("invalid_encoding", "unknown", None, (), digest)

    try:
        value = json.loads(decoded)
    except json.JSONDecodeError:
        return PayloadSummary("invalid_json", "unknown", None, (), digest)

    if isinstance(value, list):
        return PayloadSummary("batch", "multiple", None, (), digest)
    if not isinstance(value, dict):
        return PayloadSummary("scalar", "unknown", None, (), digest)

    source_type = value.get("_type")
    if not isinstance(source_type, str):
        source_type = "missing"
    device_time = value.get("tst")
    if isinstance(device_time, bool) or not isinstance(device_time, int):
        device_time = None
    identity_fields = tuple(key for key in ("tid", "topic") if key in value)
    return PayloadSummary("object", source_type, device_time, identity_fields, digest)


def authorization_scheme(value: str | None) -> str:
    """Return only the normalized scheme, never credential material."""

    if value is None:
        return "none"
    scheme, separator, _credential = value.partition(" ")
    if not separator or not scheme:
        return "malformed"
    return scheme.lower()


class CaptureState:
    """Thread-safe capture log with a deterministic HTTP response plan."""

    def __init__(self, responses: Sequence[int] = ()) -> None:
        self._responses = deque(responses)
        self._records: list[CaptureRecord] = []
        self._lock = threading.Lock()

    def next_status(self) -> int:
        """Consume the next scripted status or return the success default."""

        with self._lock:
            return self._responses.popleft() if self._responses else 200

    def append(self, record: CaptureRecord) -> None:
        """Append one safe record."""

        with self._lock:
            self._records.append(record)

    def snapshot(self) -> tuple[CaptureRecord, ...]:
        """Return an immutable snapshot of captured records."""

        with self._lock:
            return tuple(self._records)


class _CaptureServer(ThreadingHTTPServer):
    state: CaptureState


class _CaptureHandler(BaseHTTPRequestHandler):
    server: _CaptureServer

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        """Capture a bounded safe summary and return the scripted response."""

        try:
            body_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            body_length = 0
        body = self.rfile.read(max(body_length, 0))
        status = self.server.state.next_status()
        content_type = self.headers.get("Content-Type", "none").split(";", 1)[0].lower()
        record = CaptureRecord(
            method="POST",
            path=urlsplit(self.path).path,
            content_type=content_type,
            body_length=len(body),
            authorization_scheme=authorization_scheme(self.headers.get("Authorization")),
            payload=summarize_payload(body),
            response_status=status,
        )
        self.server.state.append(record)
        self._respond(status)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        """Make the harness's POST-only behavior explicit."""

        self._respond(405)

    def _respond(self, status: int) -> None:
        body = b"[]" if 200 <= status < 300 else b'{"error":"synthetic_response"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        """Suppress BaseHTTPRequestHandler logs, which may contain raw paths."""


@contextmanager
def running_capture(responses: Sequence[int] = ()) -> Iterator[tuple[str, CaptureState]]:
    """Run an ephemeral loopback-only capture server."""

    state = CaptureState(responses)
    server = _CaptureServer(("127.0.0.1", 0), _CaptureHandler)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1/owntracks", state
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def post(
    url: str,
    payload: Mapping[str, Any] | list[Any] | bytes | None,
    *,
    basic_auth: tuple[str, str] | None = None,
    content_type: str | None = "application/json",
) -> ReplayResult:
    """POST one source payload and return both success and HTTP error outcomes."""

    if payload is None:
        body = b""
    elif isinstance(payload, bytes):
        body = payload
    else:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    headers: dict[str, str] = {}
    if content_type is not None:
        headers["Content-Type"] = content_type
    if basic_auth is not None:
        token = base64.b64encode(":".join(basic_auth).encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request_body = None if payload is None else body
    request = Request(url, data=request_body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=5) as response:
            return ReplayResult(response.status, response.read())
    except HTTPError as error:
        return ReplayResult(error.code, error.read())
