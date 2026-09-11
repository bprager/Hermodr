"""Guarded SQLite connections and migration execution."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from importlib import resources
from pathlib import Path
import sqlite3
from typing import Iterator

from .config import Configuration


MINIMUM_SAFE_SQLITE = (3, 51, 3)
APPROVED_SQLITE_BUILDS = {
    (3, 53, 4): "2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc",
}


class DatabaseError(RuntimeError):
    """Bounded database startup or migration failure."""


def sqlite_version_supported(version: tuple[int, int, int] = sqlite3.sqlite_version_info) -> bool:
    return version >= MINIMUM_SAFE_SQLITE


def sqlite_source_id() -> str:
    connection = sqlite3.connect(":memory:")
    try:
        return str(connection.execute("SELECT sqlite_source_id()").fetchone()[0])
    finally:
        connection.close()


def sqlite_build_approved(
    version: tuple[int, int, int] = sqlite3.sqlite_version_info,
    source_id: str | None = None,
) -> bool:
    actual_source_id = sqlite_source_id() if source_id is None else source_id
    return APPROVED_SQLITE_BUILDS.get(version) == actual_source_id


def assert_runtime_supported(configuration: Configuration) -> None:
    if configuration.production and not sqlite_version_supported():
        raise DatabaseError("sqlite_version_unsupported")
    if configuration.production and not sqlite_build_approved():
        raise DatabaseError("sqlite_build_unapproved")


def connect(configuration: Configuration, *, allow_unsafe_production: bool = False) -> sqlite3.Connection:
    if not allow_unsafe_production:
        assert_runtime_supported(configuration)
    configuration.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(configuration.database_path, timeout=configuration.busy_timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {configuration.busy_timeout_ms}")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@dataclass(frozen=True)
class Migration:
    migration_id: int
    name: str
    sql: str
    checksum: str


def available_migrations() -> tuple[Migration, ...]:
    sql_root = resources.files("hermodr").joinpath("sql")
    migrations = []
    for entry in sorted(sql_root.iterdir(), key=lambda item: item.name):
        if entry.name.endswith(".sql"):
            raw = entry.read_text(encoding="utf-8")
            migrations.append(Migration(int(entry.name.split("_", 1)[0]), entry.name, raw, hashlib.sha256(raw.encode()).hexdigest()))
    return tuple(migrations)


def _statements(script: str) -> Iterator[str]:
    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                yield statement
            pending = ""
    if pending.strip():
        raise DatabaseError("migration_incomplete_statement")


def migrate(connection: sqlite3.Connection) -> tuple[int, ...]:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (migration_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, checksum TEXT NOT NULL, applied_at_ms INTEGER NOT NULL) STRICT"
    )
    applied = {row["migration_id"]: row["checksum"] for row in connection.execute("SELECT migration_id, checksum FROM schema_migrations")}
    completed = []
    for migration in available_migrations():
        if migration.migration_id in applied:
            if applied[migration.migration_id] != migration.checksum:
                raise DatabaseError("migration_checksum_mismatch")
            continue
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _statements(migration.sql):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, ?, unixepoch('subsec') * 1000)",
                (migration.migration_id, migration.name, migration.checksum),
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise DatabaseError("migration_failed") from exc
        completed.append(migration.migration_id)
    return tuple(completed)


def schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("SELECT COALESCE(MAX(migration_id), 0) FROM schema_migrations").fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0])


@contextmanager
def migrated_database(configuration: Configuration) -> Iterator[sqlite3.Connection]:
    connection = connect(configuration)
    try:
        migrate(connection)
        yield connection
    finally:
        connection.close()
