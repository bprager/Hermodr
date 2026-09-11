# M0 Validation Evidence

**Date:** 2026-09-10
**Command:** `make check`
**Result:** pass

## Automated Results

- 15 standard-library unit and integration tests passed.
- The HTTP integration tests used an ephemeral loopback endpoint and completed a real request/response exchange.
- Measured M0 line coverage: **100.00% (428/428)**.
- Coverage includes all handwritten Python harness and test modules; generated and third-party code is excluded.
- Tests prove the coverage gate passes above 95 percent, fails at exactly 95 percent and below, and rejects missing evidence.
- Python compilation and `tabnanny` static checks passed.
- Markdown target, trailing-whitespace, sensitive-pattern, and Git diff checks passed.
- Python's standard library does not provide a general race detector. Thread-safe response-plan consumption and capture recording are stressed with 24 concurrent HTTP clients; later SQLite concurrency requires the patched-library stress tests mandated by ADR 0002.

## Behavioral Matrix

| Behavior | Evidence |
| --- | --- |
| Location, transition, waypoint, status | Synthetic fixtures replayed and captured by type |
| Duplicate | Identical body digests counted without retaining bodies |
| Delayed/out-of-order | Descending adjacent device timestamps detected |
| Retry-relevant response | Scripted `503` followed by `200` for the same payload |
| Content type | JSON with charset, plain text, and absent header characterized |
| Timestamp | Unix-second integer captured; Boolean/non-integer rejected as timestamp evidence |
| Identity fields | Only field names (`tid`, `topic`) reported, never values |
| Single/batch | Object and array classified distinctly |
| Empty publish | Zero-length POST succeeds and is classified without payload retention |
| HTTP method | GET rejected with `405` |
| Safe metadata | Query removed from recorded path; only authorization scheme retained |
| Failure | HTTP errors returned to caller; connection errors propagate |

## Manual Evidence Reviewed

- Official OwnTracks HTTP, JSON, waypoint, and Recorder documentation is cited in the findings and ADRs.
- Read-only host inventory distinguishes verified facts from facts hidden by workspace isolation.
- The installed SQLite version is recorded as a production blocker under the current upstream WAL advisory.
- All fixtures use sentinel coordinates and synthetic identities.

## External Gates Not Claimed as Complete

- Real-device headers, offline ordering, and non-`2xx` retry timing.
- Live application-host service manager and boot-order verification.
- Retention, public-route, backup destination, and recovery-key approval.
- Patched production SQLite installation and concurrency validation.

These items require hardware, host, or policy authority and remain assigned to commissioning or the relevant later milestone. M0's repository-executable scope is complete without misrepresenting them as verified.
