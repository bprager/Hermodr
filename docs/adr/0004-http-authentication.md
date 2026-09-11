# ADR 0004: Use HTTP Basic Authentication over TLS

- **Status:** Accepted
- **Date:** 2026-09-10
- **Backlog:** HMD-003

## Context

The receiver needs an authentication mode supported by OwnTracks on iOS and later by a second independently scoped device. Authentication must never allow payload-controlled subject selection.

The official [OwnTracks HTTP documentation](https://owntracks.org/booklet/tech/http/) documents HTTP Basic credentials in application settings and strongly recommends TLS. The iOS configuration format can add custom headers, but Basic is the directly documented cross-platform HTTP authentication mechanism.

## Decision

Use high-entropy HTTP Basic credentials over gateway-terminated TLS. Each credential maps server-side to exactly one device and subject. Ignore query/header/payload user or device fields as authority; where present, validate them against the credential mapping. Support two overlapping hashes for rotation and independent revocation per device.

The M0 harness records only the authentication scheme and never credentials.

## Consequences

- The public gateway must reject cleartext and redact `Authorization` completely.
- Credential usernames are opaque key identifiers, not names.
- Bearer authentication is not part of V1; it can be added without changing canonical records if later client evidence justifies it.
