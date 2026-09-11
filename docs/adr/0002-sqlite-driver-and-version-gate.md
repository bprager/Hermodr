# ADR 0002: Use Python sqlite3 Behind a Patched-Version Gate

- **Status:** Accepted with production prerequisite
- **Date:** 2026-09-10
- **Backlog:** HMD-003

## Context

The PRD selects SQLite WAL for the initial durable store. The application host's Python runtime links SQLite 3.46.1. Hermóðr plans multiple processes that can write or checkpoint the same WAL database.

SQLite's current [WAL documentation](https://www.sqlite.org/wal.html) identifies a WAL-reset race affecting versions through 3.51.2 in a multi-connection write/checkpoint pattern. It lists 3.51.3 as fixed, with selected backports. The same documentation requires all WAL users to remain on one host, explains that only one writer proceeds at a time, and states that `synchronous=FULL` syncs each commit. Python exposes SQLite through its standard [`sqlite3` module](https://docs.python.org/3.13/library/sqlite3.html).

## Decision

Use Python's standard `sqlite3` driver, but do not activate production WAL processing with the installed SQLite 3.46.1 library. M1 must fail startup unless the linked SQLite is at least 3.51.3. A reviewed vendor-backported build may be allowlisted later by exact version and provenance.

Use one local database, short transactions, `journal_mode=WAL`, `synchronous=FULL`, foreign keys, and a bounded busy timeout. Receiver, processor, and maintenance processes remain on the same host. Use Python's connection backup API for live backups.

## Consequences

- Upgrading or bundling a patched SQLite library is a production prerequisite.
- M1 adds a tested startup version guard and exposes only a safe version/build metric.
- Concurrent checkpoint and crash tests must run against the exact deployed library.
- This avoids CGO/native-extension package selection while retaining a future PostgreSQL migration boundary.
