# M1 Validation Evidence

**Status:** Passed
**Validated:** 2026-09-10

## Scope

- Four command boundaries (`receiver`, `processor`, `admin`, and `migrate`) load the same strict configuration and fail closed.
- A dependency-free, reproducible PEP 517 wheel contains the runtime, migrations, contracts, generated build identity, and console entry point.
- Migration 001 creates the complete initial strict SQLite schema from an empty database and is idempotent on re-entry.
- Production startup rejects affected or unreviewed SQLite builds and accepts the exact pinned 3.53.4 version/source identity; test and development databases remain executable for repository validation.
- Subject and device relationships are composite-key scoped, and repository reads require an explicit subject.
- Seven canonical JSON Schema contracts have matching synthetic golden fixtures.
- Hashing, opaque identifiers, bounded enums, allowlist-only logging, bounded metric labels, build metadata, and durable metric reconstruction are tested.
- The zero-third-party dependency and license inventory is recorded in `docs/m1/DEPENDENCY_LICENSE_REPORT.md` and enforced through manifest and import scans.
- Existing M0 protocol behavior remains covered by the combined suite.

## Automated evidence

Run:

```shell
make check
make sqlite-validated-check
```

The gate performs whitespace and syntax checks, byte-compilation, AST-based unsafe-code and undeclared-external-import analysis, zero-runtime-dependency/license-policy verification, reproducible artifact construction, unit/integration/contract/privacy tests, aggregate line coverage, Markdown checks, sensitive-pattern scanning, and Git diff validation.

The final release-candidate run passed 41 tests and measured **100.00% line coverage (1856/1856 executable lines)**. The gate fails at 95% or below and measures all handwritten Python runtime, build-backend, harness, SQLite supply, static-analysis, and test code.

`make sqlite-validated-check` additionally checksum-builds and probes the approved SQLite 3.53.4 private library, confirms production startup accepts its exact source identity, and reruns the complete suite with Python dynamically linked to that library. The local release-candidate run passed both the system-library negative-gate suite and the approved-runtime suite.

## Boundaries not claimed

- The approved SQLite runtime supply is resolved; installation into the hardened service prefix and reboot drills remain M3 deployment work.
- Public routing, boot-enabled services, persistent Prometheus/dashboard deployment, and reboot drills are M3 work.
- Credential authentication and durable receiver ingestion are M2 work.
- No production host, credential, monitoring service, or location record was changed during M1.
