# M8 Real-Device Commissioning

**Status:** In progress; pre-device controls and post-reboot baseline complete
**Activation scope:** synthetic data only until every production gate below passes

## Post-reboot baseline

On 2026-09-11 the application host entered a new boot with build `619145e` and schema version 6. The receiver, processor, metrics timer, and backup timer returned enabled and active without operator restart. Private liveness and storage-backed readiness returned success.

Durable state reconstructed with one processed job, zero pending/processing/failed/quarantined jobs, one outbox record, no consumer lag, a current processor heartbeat, successful create/verify/restore-test backup gauges, and a valid audit chain. The dedicated persistent Prometheus instance exposed 33 Hermóðr series. The build series contained five samples before and seventeen samples after the reboot boundary in the inspected window. Grafana reported a healthy database and the rules configuration validated. The only firing Hermóðr alert was the expected report-freshness warning while no real device is active.

The gateway host remained available, could reach the ingestion listener, and could not reach the private operations listener. Repository validation passed 90 tests and the complete static, contract, privacy, artifact, and coverage gates at 97.91 percent line coverage.

## Commissioning sequence

1. Use the approved RAID-5-backed `saga` destination and record an isolated restore from its encrypted copy. Assign recovery-key custody outside the application host.
2. Create a new protected credential file with mode `0600`. Stage it through `admin credential-stage`; do not edit the database directly.
3. Configure the real device through the approved TLS route. Keep the bootstrap credential active during a bounded overlap.
4. Verify a current location, significant-change update, selected-geofence transition, status message, and delayed upload. Evidence records counts, timestamp shapes, response classes, and bounded identifiers only.
5. Force loss of connectivity, restore it, and record queue ordering plus retry behavior for non-success responses without retaining request bodies or coordinates in general evidence.
6. Confirm processing convergence, outbox behavior, aggregate freshness, dashboard recovery, alert delivery, log redaction, database integrity, and fresh off-host backup restoration.
7. Revoke the bootstrap credential with `admin credential-revoke`. The command refuses to revoke a subject's final usable protected credential. Prove the new credential succeeds and the old credential fails.
8. Tune and approve event frequency, battery impact, accuracy, dwell, trip, gap, and rate-limit thresholds from observed behavior. Record the approved configuration fingerprint.
9. Exercise rollback and emergency shutdown, then sign the version 1 acceptance checklist.

## Remaining external evidence

- Independent recovery-key custodian outside the application host
- Real-device access and observed iOS behavior
- Data-owner approval of battery behavior, event frequency, known-place setup, and tuned thresholds
- Signed version 1 production acceptance

Production activation and version 2 enrollment remain blocked until these items are complete.
