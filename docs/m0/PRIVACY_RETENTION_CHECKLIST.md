# M0 Privacy and Retention Checklist

**Date:** 2026-09-10
**Status:** Retention, public route, and encrypted off-host destination approved; recovery-key custody remains a production gate

- [x] Synthetic fixtures use sentinel coordinates and synthetic identifiers only.
- [x] Capture records retain body length, digest, type, timestamp shape, and identity-field names but no payload or identity values.
- [x] Harness output omits coordinates, credentials, queries, raw bodies, and identifier values.
- [x] HTTP Basic credentials are scoped server-side to a device and subject.
- [x] README remains free of personal and infrastructure names.
- [x] Raw, normalized, derived, audit, and monitoring retention remain distinct policies.
- [x] Proposed defaults remain 90 days raw, 180 days normalized, indefinite confirmed derivations until deletion, and 30 days coordinate-free operational logs.
- [x] Version 2 requires a separately reviewed policy rather than implicit inheritance.
- [x] Data owner approves the version 1 retention defaults before production.
- [x] The writable off-host destination is the RAID-5-backed `saga` host; archives remain GPG AES-256 encrypted and restore-tested after transfer.
- [ ] A recovery-key custodian outside the application host is approved before production.
- [x] Public route is approved and tested without request-body or credential logging.

The remaining unchecked item requires external policy authority and blocks production acceptance.
