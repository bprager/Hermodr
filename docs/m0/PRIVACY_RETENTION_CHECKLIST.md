# M0 Privacy and Retention Checklist

**Date:** 2026-09-10
**Status:** Repository-complete; owner approval remains a production gate

- [x] Synthetic fixtures use sentinel coordinates and synthetic identifiers only.
- [x] Capture records retain body length, digest, type, timestamp shape, and identity-field names but no payload or identity values.
- [x] Harness output omits coordinates, credentials, queries, raw bodies, and identifier values.
- [x] HTTP Basic credentials are scoped server-side to a device and subject.
- [x] README remains free of personal and infrastructure names.
- [x] Raw, normalized, derived, audit, and monitoring retention remain distinct policies.
- [x] Proposed defaults remain 90 days raw, 180 days normalized, indefinite confirmed derivations until deletion, and 30 days coordinate-free operational logs.
- [x] Version 2 requires a separately reviewed policy rather than implicit inheritance.
- [ ] Data owner approves or changes retention defaults before production.
- [ ] Backup destination, encryption method, and recovery-key custodian are approved before production.
- [ ] Public route is approved and tested without request-body or credential logging.

Unchecked items require external policy or infrastructure authority. They are not silently treated as accepted by this autonomous spike and do not block repository-only M1 work.
