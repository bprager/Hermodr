"""Strict, non-secret JSON configuration."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .identifiers import canonical_json


class ConfigurationError(ValueError):
    """A bounded configuration error safe to show to an operator."""


@dataclass(frozen=True)
class Configuration:
    environment: str
    database_path: Path
    operations_bind: str
    log_level: str
    busy_timeout_ms: int
    public_bind: str = "127.0.0.1"
    public_port: int = 8080
    operations_port: int = 8081
    max_body_bytes: int = 65_536
    disk_floor_bytes: int = 1_048_576
    drain_timeout_ms: int = 5_000
    max_future_seconds: int = 300
    dedupe_key_path: Path | None = None
    processor_lease_ms: int = 60_000
    processor_max_attempts: int = 5
    processor_base_backoff_ms: int = 1_000
    processor_max_backoff_ms: int = 300_000
    poor_accuracy_m: int = 100
    implausible_speed_mps: int = 100
    late_after_ms: int = 21_600_000
    visit_dwell_ms: int = 600_000
    coverage_gap_ms: int = 21_600_000

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @property
    def fingerprint(self) -> str:
        safe = {
            "busy_timeout_ms": self.busy_timeout_ms,
            "disk_floor_bytes": self.disk_floor_bytes,
            "drain_timeout_ms": self.drain_timeout_ms,
            "environment": self.environment,
            "log_level": self.log_level,
            "max_body_bytes": self.max_body_bytes,
            "max_future_seconds": self.max_future_seconds,
            "operations_bind": self.operations_bind,
            "operations_port": self.operations_port,
            "public_bind": self.public_bind,
            "public_port": self.public_port,
            "processor_base_backoff_ms": self.processor_base_backoff_ms,
            "processor_lease_ms": self.processor_lease_ms,
            "processor_max_attempts": self.processor_max_attempts,
            "processor_max_backoff_ms": self.processor_max_backoff_ms,
            "poor_accuracy_m": self.poor_accuracy_m,
            "implausible_speed_mps": self.implausible_speed_mps,
            "late_after_ms": self.late_after_ms,
            "visit_dwell_ms": self.visit_dwell_ms,
            "coverage_gap_ms": self.coverage_gap_ms,
        }
        return hashlib.sha256(canonical_json(safe)).hexdigest()[:16]


def load_configuration(path: Path) -> Configuration:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("configuration_unreadable") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("configuration_not_object")
    required = {"environment", "database_path", "operations_bind", "log_level", "busy_timeout_ms"}
    allowed = required | {
        "public_bind", "public_port", "operations_port", "max_body_bytes",
        "disk_floor_bytes", "drain_timeout_ms", "max_future_seconds", "dedupe_key_path",
        "processor_lease_ms", "processor_max_attempts", "processor_base_backoff_ms",
        "processor_max_backoff_ms", "poor_accuracy_m", "implausible_speed_mps", "late_after_ms",
        "visit_dwell_ms", "coverage_gap_ms",
    }
    if set(raw) - allowed or not required.issubset(raw):
        raise ConfigurationError("configuration_fields_invalid")
    environment = raw["environment"]
    database_path = raw["database_path"]
    operations_bind = raw["operations_bind"]
    log_level = raw["log_level"]
    timeout = raw["busy_timeout_ms"]
    public_bind = raw.get("public_bind", "127.0.0.1")
    public_port = raw.get("public_port", 8080)
    operations_port = raw.get("operations_port", 8081)
    max_body_bytes = raw.get("max_body_bytes", 65_536)
    disk_floor_bytes = raw.get("disk_floor_bytes", 1_048_576)
    drain_timeout_ms = raw.get("drain_timeout_ms", 5_000)
    max_future_seconds = raw.get("max_future_seconds", 300)
    dedupe_path = raw.get("dedupe_key_path")
    processor_lease_ms = raw.get("processor_lease_ms", 60_000)
    processor_max_attempts = raw.get("processor_max_attempts", 5)
    processor_base_backoff_ms = raw.get("processor_base_backoff_ms", 1_000)
    processor_max_backoff_ms = raw.get("processor_max_backoff_ms", 300_000)
    poor_accuracy_m = raw.get("poor_accuracy_m", 100)
    implausible_speed_mps = raw.get("implausible_speed_mps", 100)
    late_after_ms = raw.get("late_after_ms", 21_600_000)
    visit_dwell_ms = raw.get("visit_dwell_ms", 600_000)
    coverage_gap_ms = raw.get("coverage_gap_ms", 21_600_000)
    if not isinstance(environment, str) or environment not in {"development", "test", "production"}:
        raise ConfigurationError("environment_invalid")
    if not isinstance(database_path, str) or not database_path or database_path == ":memory:":
        raise ConfigurationError("database_path_invalid")
    if not isinstance(operations_bind, str) or operations_bind not in {"127.0.0.1", "::1"}:
        raise ConfigurationError("operations_bind_invalid")
    if not isinstance(log_level, str) or log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ConfigurationError("log_level_invalid")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 100 <= timeout <= 60_000:
        raise ConfigurationError("busy_timeout_invalid")
    if not isinstance(public_bind, str) or not public_bind:
        raise ConfigurationError("public_bind_invalid")
    for value, error in ((public_port, "public_port_invalid"), (operations_port, "operations_port_invalid")):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 65_535:
            raise ConfigurationError(error)
    if environment == "production" and (public_port == 0 or operations_port == 0):
        raise ConfigurationError("listener_port_invalid")
    if public_bind == operations_bind and public_port == operations_port:
        raise ConfigurationError("listener_collision")
    limits = (
        (max_body_bytes, 1, 1_048_576, "max_body_bytes_invalid"),
        (disk_floor_bytes, 0, 2**63 - 1, "disk_floor_bytes_invalid"),
        (drain_timeout_ms, 1, 300_000, "drain_timeout_invalid"),
        (max_future_seconds, 0, 86_400, "max_future_seconds_invalid"),
    )
    for value, low, high, error in limits:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigurationError(error)
    if dedupe_path is not None and (not isinstance(dedupe_path, str) or not dedupe_path):
        raise ConfigurationError("dedupe_key_path_invalid")
    processor_limits = (
        (processor_lease_ms, 1_000, 3_600_000, "processor_lease_invalid"),
        (processor_max_attempts, 1, 100, "processor_attempts_invalid"),
        (processor_base_backoff_ms, 1, 3_600_000, "processor_backoff_invalid"),
        (processor_max_backoff_ms, 1, 86_400_000, "processor_max_backoff_invalid"),
        (poor_accuracy_m, 1, 100_000, "poor_accuracy_invalid"),
        (implausible_speed_mps, 1, 10_000, "implausible_speed_invalid"),
        (late_after_ms, 1, 2_592_000_000, "late_after_invalid"),
        (visit_dwell_ms, 1, 604_800_000, "visit_dwell_invalid"),
        (coverage_gap_ms, 1, 2_592_000_000, "coverage_gap_invalid"),
    )
    for value, low, high, error in processor_limits:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigurationError(error)
    if processor_max_backoff_ms < processor_base_backoff_ms:
        raise ConfigurationError("processor_backoff_order_invalid")
    return Configuration(
        environment, Path(database_path), operations_bind, log_level, timeout,
        public_bind, public_port, operations_port, max_body_bytes, disk_floor_bytes,
        drain_timeout_ms, max_future_seconds, None if dedupe_path is None else Path(dedupe_path),
        processor_lease_ms, processor_max_attempts, processor_base_backoff_ms,
        processor_max_backoff_ms, poor_accuracy_m, implausible_speed_mps, late_after_ms,
        visit_dwell_ms, coverage_gap_ms,
    )
