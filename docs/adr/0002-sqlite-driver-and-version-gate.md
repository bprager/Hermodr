# ADR 0002: Use Python sqlite3 With a Pinned Private SQLite Runtime

- **Status:** Accepted; runtime supply resolved
- **Date:** 2026-09-10
- **Backlog:** HMD-003

## Context

The PRD selects SQLite WAL for the initial durable store. The application host's Python runtime links SQLite 3.46.1. Hermóðr plans multiple processes that can write or checkpoint the same WAL database.

SQLite's current [WAL documentation](https://www.sqlite.org/wal.html) identifies a WAL-reset race affecting versions through 3.51.2 in a multi-connection write/checkpoint pattern. It lists 3.51.3 as fixed, with selected backports. The same documentation requires all WAL users to remain on one host, explains that only one writer proceeds at a time, and states that `synchronous=FULL` syncs each commit. Python exposes SQLite through its standard [`sqlite3` module](https://docs.python.org/3.13/library/sqlite3.html).

## Decision

Use Python's standard `sqlite3` driver, but do not activate production WAL processing with the installed SQLite 3.46.1 library. Supply SQLite 3.53.4 as a private shared library built from the checksum-pinned official archive. Production startup accepts only the exact allowlisted version and upstream source ID; a different later version requires review and a new allowlist entry.

Select the exact private library through `LD_PRELOAD` and a private-first `LD_LIBRARY_PATH` before Python starts. Do not replace the operating-system library or rely on a process-wide library-path change after `_sqlite3` has loaded. Build and verification details are recorded in `docs/m1/SQLITE_RUNTIME.md` and `supply-chain/sqlite-runtime.json`.

Use one local database, short transactions, `journal_mode=WAL`, `synchronous=FULL`, foreign keys, and a bounded busy timeout. Receiver, processor, and maintenance processes remain on the same host. Use Python's connection backup API for live backups.

## Consequences

- The official fixed library is reproducibly available without changing system packages.
- Startup checks both version and source identity and exposes a safe version/source-hash metric.
- Concurrent checkpoint and crash tests must run against the exact deployed library.
- CI builds the pinned library and executes the full suite with Python linked to it.
- M3 must install the verified prefix on persistent storage and set the loader environment in hardened service units.
- This avoids a Python native-extension package while retaining a future PostgreSQL migration boundary.
