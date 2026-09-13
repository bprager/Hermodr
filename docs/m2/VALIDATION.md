# M2 Secure Durable Receiver Validation

**Completed:** 2026-09-11

## Delivered capability

- Two independent HTTP listeners: ingestion accepts only the OwnTracks route; operations provides liveness, readiness, and metrics.
- HTTP Basic authentication resolves an opaque key ID through one active credential, device, and subject. Multiple time-overlapping credentials support rotation.
- Strict bounded request validation covers content length, media type, UTF-8 encoding, JSON shape, supported source type, Unix timestamp, coordinate ranges, and registered `tid` agreement.
- Successful evidence is canonicalized and committed with source digest, keyed idempotency, bounded request/content/user-agent/build metadata, and one pending processing job in a single synchronous-FULL transaction.
- Exact retries return the original ingest ID without a second raw event or job. Materially future but structurally valid evidence is durably quarantined without a processing job.
- Shutdown stops public acceptance and waits for bounded in-flight requests. Readiness checks drain state, migration version, free disk, and a database write/read transaction.
- Private metrics expose bounded receiver behavior and reconstruct critical gauges from durable state.

## Automated evidence

The repository test suite contains 61 tests covering success, boundary, failure, duplicate, rotation, cross-subject, crash-before-commit, drain, readiness, listener isolation, malformed HTTP, privacy canary, and metric constraints.

```text
make test
Ran 61 tests
OK

make coverage
Hermodr line coverage: 100.00% (2944/2944)
```

The loopback load test sends 25 distinct authenticated events through the real HTTP listener with SQLite `synchronous=FULL`. It fails unless throughput is at least 10 requests/second and observed p95 end-to-end acceptance is below 500 ms. CI runs the same gate.

The full release gate is:

```text
make sqlite-validated-check
```

It builds and verifies the checksum-pinned SQLite 3.53.4 runtime, confirms its exact source identity, then runs artifact, static, dependency, unit/integration, 100%-coverage, Markdown, privacy, and diff checks with that runtime preloaded.

## Crash and privacy findings

- An injected SQLite failure immediately before commit returns `503`; raw event, processing job, and quarantine tables remain unchanged.
- A retry after the failure commits once. A retry after a completed commit returns the first ingest ID.
- Authorization and secret canaries, raw coordinate field names, and database exception text do not occur in responses, application logs, or metrics.
- The stored payload remains restricted evidence by design and therefore requires M3 filesystem, backup, and service-account controls before real data.

## Constraints and limitations

- Public TLS, rate limiting, request normalization, and access-log policy remain gateway responsibilities and are not installed by M2.
- The receiver can preserve data through restart, but no boot-enabled unit, restart backoff, or full-path host reboot drill exists yet.
- Metrics are exported, but time-series history, dashboard state, alert evaluation, and alert delivery are not yet persistent or tested.
- Credential records and protected files can be consumed safely, but the audited operator rotation workflow and runbook are M3 work.
- Encrypted backups, integrity scheduling, isolated restore, WAL-pressure automation, and recovery drills are not implemented.
- At the M2 exit, real-device content type, retry timing, battery behavior, and gateway interaction remained commissioning gates.
- The processor is not implemented, so accepted jobs intentionally remain pending.

The next recommended milestone is M3: deploy and reboot-harden the receiver boundary, monitoring stack, alerts, and backup/restore workflow before accepting real location evidence.

Subsequent milestones completed that M3 operational work and accepted the first physical iPhone during controlled M8 commissioning. The limitations above remain the historical M2 exit boundary; exact iOS non-`2xx` retry timing and battery impact are still open M8 evidence.
