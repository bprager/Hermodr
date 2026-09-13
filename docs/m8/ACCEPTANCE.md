# M8 Version 1 Acceptance Record

**Status:** Awaiting real-device execution and owner approval
**Evidence rule:** store no credentials, hostnames, coordinates, routes, place names, screenshots, raw payloads, or device identifiers here

## Automated preflight

Run this after deploying the M8 artifact and again immediately before credential cutover:

```sh
sudo -u hermodr env LD_PRELOAD=/opt/hermodr/sqlite/lib/libsqlite3.so.0 \
  /opt/hermodr/venv/bin/hermodr --config /etc/hermodr/config.json \
  admin commissioning-preflight
```

The command is read-only. It emits aggregate JSON and no authority or location identifiers. `status=ready` means the repository-controlled prerequisites pass: exactly one active version 1 subject, at least one active device, all active devices have a source identity, every active subject has an approved retention policy, every currently usable credential has a readable protected secret, durable work has converged, quarantine review is empty, database and audit chains are valid, and backup create/verify/restore-test stages have succeeded.

It does not prove TLS reachability, iPhone behavior, current off-host archive presence, alert delivery, battery impact, human approval, or signature. Those remain explicit rows below.

## Evidence checklist

Use UTC timestamps and bounded audit/run IDs only.

| Gate | Required evidence | Result |
| --- | --- | --- |
| Repository preflight | Redacted aggregate JSON has `status=ready` | Complete 2026-09-12; build `debca4c964b5` |
| TLS route | iPhone trusts certificate; operations listener remains unreachable from gateway | Complete 2026-09-12 |
| Manual location | One foreground publish accepted and processed | Complete 2026-09-12 |
| Significant change | Background update accepted with capture/receipt delay recorded | Complete; 14 updates processed, maximum observed delay 3.754 seconds |
| Region transition | One enter and one leave for owner-selected temporary region | Complete; temporary region removed |
| Device status | Background refresh status observed; headers/payload shape recorded without values | Complete after `a9abb6342216`; timestamp-less status accepted and processed, field names only inspected |
| Connectivity loss | One queued publish drains after connectivity restoration without duplicate canonical effects | Partial; natural 25-minute delayed delivery and controlled reconnect/idempotency pass, controlled capture-before-receipt interval not proven |
| Credential cutover | New credential succeeds; audited bootstrap revocation; old credential fails | Complete 2026-09-12; new iPhone credential accepted before and after cutover, bootstrap revoked through audited control, old login returned `401`, placeholder device disabled, and old secret removed |
| Processing/outbox | Jobs and recompute converge; approved projection is idempotent | Complete; real-device jobs converged, reconnect window had zero duplicate raw/canonical effects, and the post-cutover publish processed on its first attempt |
| Observability | Dashboard current; alert test delivered; logs pass redaction inspection | Dashboard/rules/metrics current; real-event inspection pending |
| Recovery | Fresh encrypted Saga archive verifies and restores in isolation | Complete 2026-09-12 after real-device events; create, off-host verify, and isolated restore succeeded |
| Rollback | Client Quiet/removal and server endpoint shutdown procedures rehearsed | Pending iPhone |
| Configuration | Accepted mode and thresholds recorded as a redacted fingerprint | Pending observed behavior |

## Owner decisions

These decisions cannot be inferred or automated:

| Decision | Approved value/result | Approval reference |
| --- | --- | --- |
| Normal monitoring mode | Significant | Interactive commissioning, 2026-09-12 |
| Battery impact | Pending | Pending |
| Event frequency | Pending | Pending |
| Retained known-place regions | Pending | Pending |
| Accuracy threshold | Pending | Pending |
| Dwell threshold | Pending | Pending |
| Trip threshold | Pending | Pending |
| Coverage-gap threshold | Pending | Pending |
| Gateway rate limit | Pending | Pending |
| Version 1 production activation | Pending | Pending |

M8 and HMD-026 become complete only when every evidence row passes, every owner decision has an approval reference, the accepted redacted configuration fingerprint is recorded, and Bernd signs the production activation decision.
