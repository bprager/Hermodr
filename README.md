# Hermóðr

Hermóðr is a local-first service for securely collecting location events, preserving their provenance, deriving deterministic visits and trips, and publishing approved canonical records through a guarded outbox.

The project has completed its protocol spike, contracts foundation, secure durable receiver, and synthetic-only operational deployment baseline. Real-device commissioning has not started.

## Architecture

```text
Location client
    |
    v
HTTPS gateway -> receiver -> durable restricted store
                                  |
                                  v
                              processor
                                  |
                                  v
                         canonical outbox
                                  |
                                  v
                    separately authorized importer
```

The receiver and processor are independent processes. The receiver acknowledges an event only after durable storage. In M3 the processor is a boot/recovery heartbeat sentinel; deterministic queue processing begins in M4. Direct graph-database writes are outside the service boundary.

## Design priorities

- Privacy-preserving local operation
- Immutable source evidence and explicit provenance
- Idempotent, event-time-aware processing
- Strict isolation between tracked subjects
- Automatic recovery after host reboots
- Metrics, alerts, audit records, and tested restoration
- No language-model dependency in the ingestion or derivation path

## Documentation

- [Product requirements](docs/HERMODR_PRD.md)
- [Implementation design](docs/IMPLEMENTATION_DESIGN.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Maintained backlog](docs/BACKLOG.md)
- [Architecture decisions](docs/adr/)
- [M0 protocol findings](docs/m0/OWNTRACKS_HTTP_FINDINGS.md)
- [M1 validation evidence](docs/m1/VALIDATION.md)
- [Observability and reboot contract](docs/m1/OBSERVABILITY.md)
- [M2 receiver validation evidence](docs/m2/VALIDATION.md)
- [M2 receiver observability](docs/m2/OBSERVABILITY.md)
- [M3 operations baseline](docs/m3/OPERATIONS.md)
- [M3 validation evidence](docs/m3/VALIDATION.md)
- [M3 operator runbook](docs/runbooks/M3_OPERATIONS.md)
- [Dependency and license report](docs/m1/DEPENDENCY_LICENSE_REPORT.md)
- [Approved SQLite runtime supply](docs/m1/SQLITE_RUNTIME.md)
- [Changelog](CHANGELOG.md)

Detailed product documentation is access-controlled project material. Never commit real coordinates, credentials, device identifiers, addresses, or production payloads.

## Commands

The reproducible wheel exposes one entry point with four command boundaries:

```text
hermodr receiver
hermodr processor
hermodr admin
hermodr migrate
```

Python 3.13 or newer is the selected implementation runtime. The receiver now serves authenticated ingestion plus separate private operations endpoints. The processor remains a fail-closed startup boundary until its processing milestone.

## Development

The repository uses only the Python standard library and synthetic data:

```shell
make demo
make check
make artifact
```

`make check` builds the artifact and runs unit, integration, contract, migration, isolation, observability, static, Markdown, and sensitive-pattern checks. Its line-coverage gate fails at 95% or below.

A non-production configuration template is available at `config/hermodr.example.json`. Initialize a disposable database and check each process boundary with:

```shell
PYTHONPATH=src:. python3 -m hermodr --config config/hermodr.example.json migrate up
PYTHONPATH=src:. python3 -m hermodr --config config/hermodr.example.json receiver --check
PYTHONPATH=src:. python3 -m hermodr --config config/hermodr.example.json processor --check
```

Receiver startup also requires schema migration 002, at least one active subject/device/credential mapping, a protected credential file, and a stable deduplication key file. Secret files must be outside source control, contain sufficiently long random values, and have mode `0600`. Run the receiver without `--check` only behind an approved TLS gateway:

```shell
PYTHONPATH=src:. python3 -m hermodr --config /path/to/protected-config.json receiver
```

M3 adds boot-enabled hardened units, gateway TLS controls, persistent metric collection, dashboard and alert provisioning, encrypted backup verification, isolated restore testing, and full-path reboot proof. The deployment remains synthetic-only until the M3 validation document's external notification gate passes.

Production startup is intentionally rejected unless the linked SQLite library satisfies the approved patched-version gate.

The approved SQLite 3.53.4 runtime is checksum-pinned and built into an isolated local prefix without replacing the system library:

```shell
make sqlite-runtime
make sqlite-runtime-check
make sqlite-validated-check
```

## Delivery sequence

1. Verify source-client and host behavior.
2. Build secure, durable collection with operational visibility.
3. Prove reboot recovery, backup restoration, and critical alerting.
4. Add deterministic normalization and derived records.
5. Complete retention, deletion, and guarded outbox integration.
6. Commission the first release.
7. Immediately add and validate isolated second-subject support.

## Project maintenance

- `docs/BACKLOG.md` is the source of truth for planned work and status. Update it whenever scope, priority, dependency, or completion state changes.
- `CHANGELOG.md` records notable user- and operator-visible changes under `Unreleased` as they land.
- Architectural choices with meaningful tradeoffs should receive an ADR before implementation.
- A backlog item is not complete until its acceptance evidence is linked or recorded.

## Security

Use synthetic fixtures only. Do not report security vulnerabilities in public issue content when doing so could expose location, identity, credentials, or infrastructure details; use the repository owner's private security-reporting channel.
