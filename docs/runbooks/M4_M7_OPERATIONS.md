# M4–M7 Processing and Lifecycle Runbook

Use a protected production configuration and the approved private SQLite runtime for every command. Command output contains counts and opaque identifiers, never coordinates or payloads.

## Processor and dead letters

1. Check `hermodr_processing_jobs`, oldest pending/failed age, processor heartbeat, and recompute-window metrics.
2. Inspect only bounded job state and error codes through the restricted database diagnostic. Do not print payload bytes.
3. Correct the bounded cause, then use audited reprocessing. Never update a failed job directly without preserving an audit record.
4. Restart the processor and verify its heartbeat, queue reduction, recompute completion, outbox head, and absence of duplicate event IDs.

## Reprocessing

Preview first:

```shell
hermodr --config /etc/hermodr/config.json admin reprocess-preview --subject-id SUBJECT --reason-code operator_review --run-id RUN
```

Apply with the same reason and a new run ID. Compare the returned impact counters, recompute metric, supersession events, and outbox checkpoint lag.

## Retention

Run `retention-apply` in batches no larger than 1,000. Verify raw-payload and normalized counts, `hermodr_retention_overdue_records`, database integrity, audit chain, and a fresh encrypted backup. Active time-range holds and evidence supporting provisional derivations must remain.

Coordinate-free operational logs use an independent 30-day system-journal policy; application data retention must not delete or extend those logs. Verify the host journal vacuum policy separately.

## Deletion

1. Create a subject/time-range plan with `deletion-plan`; save its opaque plan ID and exact counts in the restricted change record.
2. Review the scope. The plan expires after 24 hours and apply fails if any count changes.
3. Apply by plan ID with a new run ID. Never bypass stale-plan refusal.
4. Verify selected restricted payloads are absent, database integrity passes, tombstones are present, the fake/authorized importer acknowledges them, and `audit-verify` succeeds.
5. Create and restore-test a new encrypted backup. Existing older backups remain governed by their separate approved retention and deletion process.

## Guarded outbox

Consumers use an allowlisted identifier, version 1 envelopes, ascending sequence, and durable receipts. Observation events and unapproved places are acknowledged as rejected projections. Stop integration on unknown schema versions, malformed envelopes, or checkpoint inconsistencies. Hermóðr itself must never receive a graph credential.
