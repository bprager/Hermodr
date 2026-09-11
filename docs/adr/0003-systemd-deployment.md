# ADR 0003: Deploy Hermóðr with systemd

- **Status:** Accepted
- **Date:** 2026-09-10
- **Backlog:** HMD-003

## Context

Hermóðr must recover automatically after reboot, order startup after durable storage and networking, run receiver and processor independently, and expose private health and metrics listeners. The gateway host uses systemd and already runs its gateway service and node exporter as enabled units. The application host has systemd tooling installed, although its live host service state was not visible from the restricted workspace.

## Decision

Deploy receiver, processor, and scheduled administrative maintenance as hardened systemd units/timers on the application host. Keep the existing separately managed gateway service on the gateway host. Bind ingestion only to the private interface and bind health/metrics to loopback or a dedicated operations interface.

Units will use explicit users, writable paths, dependency ordering, readiness, bounded restart backoff, resource controls, and boot enablement. M3 must verify these properties on the live application host before activation.

## Consequences

- No container runtime is required for Hermóðr.
- Unit files and runbooks are versioned under `deploy/systemd/`.
- Live application-host boot state remains a documented follow-up because non-interactive host SSH was unavailable during M0.
- Full-path reboot testing includes the existing gateway unit and the eventual monitoring collector, dashboard, and alert evaluator.
