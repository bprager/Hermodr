# Hermóðr

Hermóðr is a local-first service for securely collecting location events, preserving their provenance, deriving deterministic visits and trips, and publishing approved canonical records through a guarded outbox.

The project has completed its protocol and deployment decision spike. Production service implementation has not started.

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

The receiver and processor are independent processes. The receiver acknowledges an event only after durable storage. The processor performs deterministic, versioned normalization and derivation asynchronously. Direct graph-database writes are outside the service boundary.

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
- [Changelog](CHANGELOG.md)

Detailed product documentation is access-controlled project material. Never commit real coordinates, credentials, device identifiers, addresses, or production payloads.

## Planned commands

The recommended release artifact will expose four commands:

```text
hermodr receiver
hermodr processor
hermodr admin
hermodr migrate
```

Python 3.13 or newer is the selected implementation runtime. Production packaging is finalized during the repository-foundation milestone.

## Development

The M0 protocol harness uses only the Python standard library and synthetic data:

```shell
make demo
make check
```

`make check` runs tests, static checks, Markdown and sensitive-pattern validation, and a strict line-coverage gate that fails at 95% or below.

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
