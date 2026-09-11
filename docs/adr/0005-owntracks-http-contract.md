# ADR 0005: Accept One OwnTracks Object per HTTP Request

- **Status:** Accepted with real-device verification deferred to commissioning
- **Date:** 2026-09-10
- **Backlog:** HMD-001, HMD-003

## Context

The receiver contract needs a request shape and response behavior compatible with OwnTracks queuing. No real device or production payload is available during the autonomous M0 spike.

The official [OwnTracks HTTP documentation](https://owntracks.org/booklet/tech/http/) says the app POSTs each publish's normal JSON payload to one configured endpoint, treats any `2xx` response as posted, queues when the endpoint is unreachable, and commonly expects `[]` from a `200` response. It also notes that zero-length publishes can occur and should be ignored. The [JSON reference](https://owntracks.org/booklet/tech/json/) defines mandatory `_type`, Unix-second `tst`, HTTP `tid`, HTTP-only `topic`, and the location, transition, waypoint, and status shapes. It does not document request arrays or retry intervals for non-`2xx` responses.

## Decision

- Accept one JSON object per request. Reject arrays with `422`; do not partially accept batches.
- Ignore a zero-length body with `200 []` and do not create evidence.
- Return `200 []` after a new event is durably committed and for an exact duplicate.
- Use bounded `4xx` errors for permanent request problems and `503` for transient storage failure.
- Initially require `application/json` or `application/*+json`; confirm the actual iOS content type before production.
- Treat `tst` as Unix seconds. Authentication owns subject/device identity; `tid` and `topic` are evidence checked against registration.

## Consequences

- This supersedes the design's provisional `202` response body.
- Non-`2xx` retry timing remains unverified; M8 must capture real-device behavior before activation.
- The M0 harness deliberately characterizes an array, alternate content type, empty body, duplicate, out-of-order delivery, and a `503` followed by `200` without claiming undocumented client backoff semantics.
