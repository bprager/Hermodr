"""Build and verify Hermodr's pinned private SQLite runtime."""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import urllib.error


SQLITE_VERSION = "3.53.4"
SQLITE_ARCHIVE = "sqlite-autoconf-3530400.tar.gz"
SQLITE_URL = f"https://www.sqlite.org/2026/{SQLITE_ARCHIVE}"
SQLITE_ARCHIVE_SHA3_256 = "454e45f61c6bd75b7420e7190732dea03ce6639c63ada47bbc592f67fc340338"
SQLITE_SOURCE_ID = "2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc"
COMPILE_FLAGS = (
    "-O2",
    "-fPIC",
    "-DSQLITE_DQS=0",
    "-DSQLITE_TRUSTED_SCHEMA=0",
    "-DSQLITE_SECURE_DELETE=1",
    "-DSQLITE_DEFAULT_WAL_SYNCHRONOUS=2",
)
CONFIGURE_FLAGS = (
    "--disable-static",
    "--disable-readline",
    "--disable-load-extension",
    "--soname=legacy",
)


class RuntimeSupplyError(RuntimeError):
    """A bounded source, build, or runtime validation error."""


@dataclass(frozen=True)
class RuntimeEvidence:
    version: str
    source_id: str
    threadsafety: int
    json_available: bool
    trusted_schema_default_off: bool
    secure_delete_default_on: bool
    load_extension_omitted: bool


def archive_digest(path: Path) -> str:
    digest = hashlib.sha3_256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(path: Path) -> None:
    try:
        digest = archive_digest(path)
    except OSError as exc:
        raise RuntimeSupplyError("sqlite_archive_unreadable") from exc
    if digest != SQLITE_ARCHIVE_SHA3_256:
        raise RuntimeSupplyError("sqlite_archive_checksum_mismatch")


def download_archive(destination: Path) -> None:
    partial = destination.with_suffix(destination.suffix + ".partial")
    try:
        with urllib.request.urlopen(SQLITE_URL, timeout=30) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        verify_archive(partial)
        partial.replace(destination)
    except RuntimeSupplyError:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError) as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeSupplyError("sqlite_download_failed") from exc


def extract_archive(archive: Path, destination: Path) -> Path:
    destination_resolved = destination.resolve()
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            for member in members:
                target = (destination / member.name).resolve()
                if not target.is_relative_to(destination_resolved) or not (member.isfile() or member.isdir()):
                    raise RuntimeSupplyError("sqlite_archive_unsafe")
            bundle.extractall(destination, members=members, filter="data")
    except RuntimeSupplyError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise RuntimeSupplyError("sqlite_archive_invalid") from exc
    source = destination / SQLITE_ARCHIVE.removesuffix(".tar.gz")
    if not (source / "configure").is_file() or not (source / "sqlite3.c").is_file():
        raise RuntimeSupplyError("sqlite_archive_layout_invalid")
    return source


def _execute(command: list[str], cwd: Path, environment: dict[str, str] | None = None) -> None:
    try:
        subprocess.run(command, cwd=cwd, env=environment, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeSupplyError("sqlite_build_failed") from exc


def runtime_environment(prefix: Path) -> dict[str, str]:
    environment = os.environ.copy()
    library = str((prefix / "lib").resolve())
    existing = environment.get("LD_LIBRARY_PATH")
    environment["LD_LIBRARY_PATH"] = library if not existing else f"{library}:{existing}"
    return environment


def verify_runtime(prefix: Path, python: str = sys.executable) -> RuntimeEvidence:
    library = prefix / "lib" / "libsqlite3.so.0"
    if not library.is_file():
        raise RuntimeSupplyError("sqlite_runtime_missing")
    probe = """import json, sqlite3
c = sqlite3.connect(':memory:')
options = {row[0] for row in c.execute('PRAGMA compile_options')}
print(json.dumps({
  'version': sqlite3.sqlite_version,
  'source_id': c.execute('SELECT sqlite_source_id()').fetchone()[0],
  'threadsafety': sqlite3.threadsafety,
  'json_available': bool(c.execute("SELECT json_valid('[]')").fetchone()[0]),
  'trusted_schema_default_off': not bool(c.execute('PRAGMA trusted_schema').fetchone()[0]),
  'secure_delete_default_on': bool(c.execute('PRAGMA secure_delete').fetchone()[0]),
  'load_extension_omitted': 'OMIT_LOAD_EXTENSION' in options,
}, sort_keys=True))
"""
    try:
        completed = subprocess.run(
            [python, "-I", "-c", probe],
            env=runtime_environment(prefix),
            check=True,
            capture_output=True,
            text=True,
        )
        evidence = RuntimeEvidence(**json.loads(completed.stdout))
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeSupplyError("sqlite_runtime_probe_failed") from exc
    if evidence.version != SQLITE_VERSION or evidence.source_id != SQLITE_SOURCE_ID:
        raise RuntimeSupplyError("sqlite_runtime_identity_mismatch")
    if not all((evidence.threadsafety > 0, evidence.json_available, evidence.trusted_schema_default_off, evidence.secure_delete_default_on, evidence.load_extension_omitted)):
        raise RuntimeSupplyError("sqlite_runtime_capability_mismatch")
    return evidence


def build_runtime(prefix: Path, archive: Path | None = None, jobs: int = 2) -> RuntimeEvidence:
    if jobs < 1 or jobs > 16:
        raise RuntimeSupplyError("sqlite_build_jobs_invalid")
    if prefix.exists():
        return verify_runtime(prefix)
    with tempfile.TemporaryDirectory(prefix="hermodr-sqlite-") as temporary:
        work = Path(temporary)
        source_archive = archive or work / SQLITE_ARCHIVE
        if archive is None:
            download_archive(source_archive)
        else:
            verify_archive(source_archive)
        source = extract_archive(source_archive, work / "source")
        environment = os.environ.copy()
        environment["CFLAGS"] = " ".join(COMPILE_FLAGS)
        _execute(
            [
                str(source / "configure"),
                f"--prefix={prefix.resolve()}",
                *CONFIGURE_FLAGS,
            ],
            source,
            environment,
        )
        _execute(["make", f"-j{jobs}"], source, environment)
        _execute(["make", "install"], source, environment)
    return verify_runtime(prefix)


def run(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sqlite-runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--prefix", type=Path, required=True)
    build.add_argument("--archive", type=Path)
    build.add_argument("--jobs", type=int, default=2)
    verify = commands.add_parser("verify")
    verify.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        evidence = build_runtime(args.prefix, args.archive, args.jobs) if args.command == "build" else verify_runtime(args.prefix)
    except RuntimeSupplyError as exc:
        print(json.dumps({"error": str(exc), "status": "error"}, sort_keys=True))
        return 2
    print(json.dumps({"evidence": asdict(evidence), "status": "ok"}, sort_keys=True))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
