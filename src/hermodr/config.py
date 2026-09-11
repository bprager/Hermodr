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

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @property
    def fingerprint(self) -> str:
        safe = {
            "busy_timeout_ms": self.busy_timeout_ms,
            "environment": self.environment,
            "log_level": self.log_level,
            "operations_bind": self.operations_bind,
        }
        return hashlib.sha256(canonical_json(safe)).hexdigest()[:16]


def load_configuration(path: Path) -> Configuration:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("configuration_unreadable") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("configuration_not_object")
    allowed = {"environment", "database_path", "operations_bind", "log_level", "busy_timeout_ms"}
    if set(raw) - allowed or not allowed.issubset(raw):
        raise ConfigurationError("configuration_fields_invalid")
    environment = raw["environment"]
    database_path = raw["database_path"]
    operations_bind = raw["operations_bind"]
    log_level = raw["log_level"]
    timeout = raw["busy_timeout_ms"]
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
    return Configuration(environment, Path(database_path), operations_bind, log_level, timeout)
