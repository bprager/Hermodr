"""Reproducible build identity without host or user information."""

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
import os
import re

try:
    from ._artifact import COMMIT as ARTIFACT_COMMIT, VERSION as ARTIFACT_VERSION
except ImportError:
    ARTIFACT_COMMIT = None
    ARTIFACT_VERSION = None


SAFE_VALUE = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")


def _safe_environment(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    return value if SAFE_VALUE.fullmatch(value) else "unknown"


def _package_version() -> str:
    try:
        return version("hermodr")
    except PackageNotFoundError:
        return "0.1.0.dev0"


@dataclass(frozen=True)
class BuildInfo:
    version: str
    commit: str
    schema_version: str

    def labels(self) -> dict[str, str]:
        return {
            "version": self.version,
            "commit": self.commit,
            "schema_version": self.schema_version,
        }


BUILD = BuildInfo(
    version=_safe_environment("HERMODR_BUILD_VERSION", ARTIFACT_VERSION or _package_version()),
    commit=_safe_environment("HERMODR_BUILD_COMMIT", ARTIFACT_COMMIT or "unknown"),
    schema_version="1",
)
