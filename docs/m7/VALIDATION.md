# M4–M7 Validation

**Date:** 2026-09-11
**Scope:** synthetic processing, derivation, lifecycle, and guarded integration

This is point-in-time M4–M7 evidence. M8 subsequently enrolled the first physical iPhone and accepted real events; the synthetic-only statements in the final section describe the M7 exit boundary, not current deployment state.

## Capabilities

- The durable worker atomically claims subject-partitioned jobs, reclaims expired leases, applies bounded deterministic backoff, dead-letters terminal failures, and resumes pending recomputation after restart.
- All supported source types normalize with immutable source digests, processing and event timestamps, schema/algorithm/config versions, and bounded quality flags. Source transitions remain provisional until reconciled; waypoint places remain proposed until approved.
- Approved places use great-circle distance plus reported accuracy. Event-time ordering derives visits, transitions, trips, and explicit silence gaps. Ambiguity splits evidence runs rather than manufacturing continuity.
- Recompute windows are subject-scoped, horizon-expanded, and coalesced. Deterministic IDs prevent duplicate active effects; behavior-version changes preserve provenance and append supersession events.
- Retention uses the approved 90-day raw-payload, 180-day normalized-observation, indefinite-derived, and 30-day coordinate-free-log policy. Explicit holds and unresolved provisional evidence prevent expiration.
- Deletion requires a 24-hour count-checked plan followed by apply. It removes selected restricted records in dependency order, emits idempotent non-location tombstones, and records a chained audit event.
- The outbox boundary validates version 1 envelopes, maintains durable consumer checkpoints and receipts, rejects observation and unapproved-place projection, preserves uncertainty, and applies replay/tombstones exactly once in the fake importer.
- Critical state is reconstructed as aggregate metrics for worker backlog/failures, recomputation, retention overdue count, planned deletions, outbox head/checkpoint lag, database integrity, backup, and reporting freshness.

## Automated evidence

`make check` builds the wheel and runs migration, contract, crash, concurrent-claim, controlled-route, late-data, isolation, retention-hold, deletion, audit-tamper, importer, observable-output, and sensitive-pattern checks. The strict project gate requires aggregate executable-line coverage greater than 95 percent.

The processor unit permits only local Unix sockets, has no graph dependency or credential, starts after migrations, restarts after failure, and uses persistent database state. The monitoring bundle includes processor-backlog, dead-letter, recompute-backlog, retention-overdue, and outbox-consumer-lag alerts.

## Constraints and next milestone

- At the M7 exit, no production phone had been registered and no real location event had been accepted; M8 commissioning was the next milestone.
- No production place is created automatically; proposed waypoint places require explicit review.
- The fake importer proves the contract boundary but is not the separately owned production graph importer.
- Encrypted off-host backup and restore testing use the approved RAID-5-backed `saga` destination, Bernd is the recovery-key custodian, and the independent Bitwarden/SOPS retrieval drill passed.
- Device-derived battery behavior, event frequency, significant-change behavior, offline upload behavior, and threshold tuning require real-device evidence in M8.
