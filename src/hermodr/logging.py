"""Allowlist-only structured event rendering."""

import json
import math
import re
from typing import TextIO

from .enums import ErrorCode


ALLOWED_FIELDS = frozenset({
    "attempt", "audit_id", "build", "config_fingerprint", "duration_ms",
    "event", "ingest_id", "key_id", "level", "message", "request_id",
    "reason", "result", "run_id", "service", "stage", "timestamp",
})
BOUNDED_FIELDS = {
    "event": frozenset({"failure", "ingest", "migration", "ready", "startup"}),
    "level": frozenset({"DEBUG", "INFO", "WARNING", "ERROR"}),
    "message": frozenset({"operation_failed", "request_completed", "service_ready", "service_starting"}),
    "reason": frozenset(item.value for item in ErrorCode),
    "result": frozenset({"accepted", "duplicate", "failure", "quarantined", "rejected", "success"}),
    "service": frozenset({"admin", "migrate", "processor", "receiver"}),
    "stage": frozenset({"configuration", "migration", "startup", "storage"}),
}
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
NUMERIC_FIELDS = frozenset({"attempt", "duration_ms"})


class SafeLogger:
    def __init__(self, output: TextIO):
        self._output = output

    def emit(self, **fields: object) -> str:
        unknown = set(fields) - ALLOWED_FIELDS
        if unknown:
            raise ValueError("log_field_not_allowed")
        if "event" not in fields or "level" not in fields or "service" not in fields:
            raise ValueError("log_fields_required")
        for field, allowed in BOUNDED_FIELDS.items():
            if field in fields and fields[field] not in allowed:
                raise ValueError("log_value_not_allowed")
        for field, value in fields.items():
            if field in BOUNDED_FIELDS:
                continue
            if field in NUMERIC_FIELDS:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("log_value_not_allowed")
            elif not isinstance(value, str) or SAFE_TOKEN.fullmatch(value) is None:
                raise ValueError("log_value_not_allowed")
        rendered = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self._output.write(rendered + "\n")
        return rendered
