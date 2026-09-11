# ADR 0001: Use Python for the Hermóðr Service

- **Status:** Accepted
- **Date:** 2026-09-10
- **Backlog:** HMD-003

## Context

The application host currently provides Python 3.13 but no Go toolchain. Hermóðr's expected load is small, its receiver and processor are I/O-bound, and Python's standard library supports HTTP, hashing, structured data, process control, testing, and SQLite without a mandatory package download. The implementation design explicitly allowed the initial Go recommendation to change before scaffolding.

## Decision

Implement Hermóðr in Python 3.13 or newer. Use type annotations, narrow modules, deterministic serialization, standard-library primitives where they are adequate, and pinned reviewed dependencies only when a later milestone demonstrates a need.

The M0 capture/replay harness therefore uses only the Python standard library. Production packaging will use an isolated environment managed by deployment tooling, not packages installed into the system interpreter.

## Evidence

- The application workspace reports Python 3.13.7 and no installed Go executable.
- The [Python standard library](https://docs.python.org/3.13/library/) includes HTTP, JSON, hashing, testing, and persistence modules needed for the foundation.
- The [Python `sqlite3` documentation](https://docs.python.org/3.13/library/sqlite3.html) describes the supported DB-API interface and migration path to larger databases.

## Consequences

- The planned repository layout changes from Go-style `cmd/` and `internal/` packages to a Python `src/hermodr/` package when M1 begins.
- CI tests the minimum supported Python minor version.
- CPU-heavy derivation must be benchmarked, but the 10-request/second requirement does not justify a second runtime today.
- SQLite library safety remains a separate decision and startup gate; choosing Python does not approve the currently linked SQLite build.
