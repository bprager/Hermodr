# M1 Observability and Reboot Contract

**Status:** Implemented repository foundation; deployment activation belongs to M3
**Last verified:** 2026-09-10

## Privacy boundary

Metrics and structured logs use allowlists. Metric labels are bounded enums. Subject, device, credential, request, location, payload, path, agent, and arbitrary exception values are prohibited as metric dimensions. Logs admit only the fields declared in `hermodr.logging.ALLOWED_FIELDS`; raw payload and location fields cannot be emitted through that facade.

The operations listener must remain private. Aggregate freshness still reveals activity timing and therefore receives the same restricted network treatment as the rest of the metrics endpoint.

## Critical state after process restart

`reconstruct_critical_metrics` reads the following from SQLite on every collection. It does not need a post-restart event to recreate them:

| Signal | Durable source | Restart semantics |
| --- | --- | --- |
| Queue inventory by bounded state | `processing_jobs` | Exact current inventory |
| Oldest pending age | Oldest durable pending job plus current clock | Age continues across restart |
| Outbox head | Maximum `outbox_records.sequence` | Monotonic committed head |
| Aggregate reporting inventory | Active/disabled `subjects` | No identifying label |
| Worst authenticated ingest age | Per-active-subject latest real `raw_events.received_at_ms` | Synthetic events excluded |
| Worst captured-event age | Per-active-subject latest real `raw_events.captured_at_ms` | Delayed uploads remain visible |
| Quarantine inventory | Pending `quarantine` rows by bounded reason | Review backlog survives restart |
| Backup create/verify/restore-test state and time | `operational_state` | Explicit zero until recorded |
| Build identity | Reproducible artifact metadata | Process identity, value always one |

Database/WAL size and filesystem capacity are sampled from the current persistent volume rather than retained in process memory. Integrity results and maintenance heartbeats will use `operational_state` and `service_heartbeats` when their workflows land.

Process-lifetime counters may reset. Alerts for durability, freshness, queue depth, quarantine, backup, integrity, storage, and outbox state must use reconstructed gauges rather than counters alone.

## Monitoring-store reboot behavior

The M3 deployment must place the Prometheus-compatible time-series directory, dashboard state, and alert-evaluator state on named persistent host storage. All three services must be boot-enabled and ordered after their mounts. Configuration, dashboards, recording rules, and alert rules remain checked-in release assets. A full-path drill must reboot both service roles and prove:

1. metric scraping and alert evaluation resume automatically;
2. prior time series remain queryable;
3. reconstructed gauges have correct values before any new source event;
4. alert `for` state behaves according to the selected persistent evaluator;
5. the operations route remains unreachable through the public gateway.

This is a contract, not evidence that M3 infrastructure is deployed. M1 tests prove application-side reconstruction against a fresh process and durable database.
