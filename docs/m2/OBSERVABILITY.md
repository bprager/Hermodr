# M2 Receiver Observability

## Boundary

The operations listener is distinct from the ingestion listener and is restricted to loopback by configuration validation. The public listener has no health, metrics, or administration route. A deployment gateway must expose only `POST /v1/owntracks`.

## Health

- `GET /health/live` proves that the operations HTTP loop is responsive and returns only status and build version.
- `GET /health/ready` fails while draining, below the configured free-space floor, at the wrong migration version, or when a bounded database write/read probe fails.
- Readiness does not depend on processor progress or an external graph system.

Health bodies contain bounded component codes only. They never include paths, SQL details, credentials, identifiers, payloads, or coordinates.

## Metrics

M2 emits bounded process counters and fixed-bucket histograms for:

- requests by normalized route, method, and status class;
- accepted, duplicate, rejected, quarantined, and failed ingests by supported source type;
- authentication and validation failures by bounded reason;
- durable commit result and duration;
- end-to-end receiver request duration.

Every scrape also reconstructs critical gauges from SQLite: build and SQLite identity, database/WAL/shared-memory size, filesystem free bytes, processing jobs and oldest pending age, quarantine inventory, outbox head, aggregate reporting-subject state, worst receipt/capture age, and backup workflow state.

Process counters and histograms reset when the receiver restarts. Critical gauges do not depend on those counters and reconstruct from durable state before a ready response. Persistent time-series history, alert state, dashboards, and automatic scrape recovery are M3 responsibilities.

No metric label accepts subject, device, credential, request, ingest, person, place, path, user-agent, or coordinate values. Aggregate freshness still reveals activity timing, so the operations listener remains private.

## Logs and correlation

Receiver events use an allowlist-only JSON logger. A successful durable ingest may contain only bounded state plus opaque request, ingest, and authenticated key identifiers. Parser exceptions and raw database errors are replaced by stable response codes. Request IDs that do not match the safe token grammar are replaced.

Stored transport evidence is limited to the normalized media type, byte length, normalized user-agent family, opaque request/key identifiers, and receiver build. Raw user-agent and authorization values are not retained.

Distributed tracing remains disabled. Local request IDs plus duration histograms are the M2 correlation mechanism. If tracing is introduced later, it must inherit the metric/log allowlist and reject public trace context.

## M3 monitoring work

M2 exports the signals but does not install their durable collection or alerting. M3 must add boot-enabled services, persistent Prometheus-compatible storage, the four-row dashboard, recording and alert rules, synthetic durable-ingest probing, alert delivery tests, and full-path reboot evidence.
