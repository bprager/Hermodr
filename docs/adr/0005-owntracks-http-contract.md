# ADR 0005: Accept One OwnTracks Object per HTTP Request

- **Status:** Accepted; amended by real-device commissioning
- **Date:** 2026-09-10
- **Backlog:** HMD-001, HMD-003

## Context

The receiver contract needs a request shape and response behavior compatible with OwnTracks queuing. No real device or production payload is available during the autonomous M0 spike.

The official [OwnTracks HTTP documentation](https://owntracks.org/booklet/tech/http/) says the app POSTs each publish's normal JSON payload to one configured endpoint, treats any `2xx` response as posted, queues when the endpoint is unreachable, and commonly expects `[]` from a `200` response. It also notes that zero-length publishes can occur and should be ignored. The [JSON reference](https://owntracks.org/booklet/tech/json/) defines `_type`, Unix-second `tst` for location-bearing reports, HTTP `tid`, HTTP-added `topic`, and the location, transition, waypoint, and status shapes. It does not document request arrays or retry intervals for non-`2xx` responses.

Real-device commissioning with OwnTracks iOS 26.2.2 established that **Send Debug Status** emits `_type=status` plus an `iOS` object and HTTP-added `topic`, but no `tst` or `tid`. The original synthetic status fixture had invented a `tst`, so it did not prove compatibility with that wire shape.

## Decision

- Accept one JSON object per request. Reject arrays with `422`; do not partially accept batches.
- Ignore a zero-length body with `200 []` and do not create evidence.
- Return `200 []` after a new event is durably committed and for an exact duplicate.
- Use bounded `4xx` errors for permanent request problems and `503` for transient storage failure.
- Initially require `application/json` or `application/*+json`; confirm the actual iOS content type before production.
- Require and validate Unix-second `tst` for location, transition, and waypoint. Accept a status report without `tst`, preserve a null raw capture time, and use receipt time only as the explicitly labelled normalization-order fallback. This prevents a status report from refreshing location-capture freshness.
- Authentication owns subject/device identity. Check a supplied `tid` against registration; retain `topic` as restricted source evidence rather than claiming it is registered identity.

## Consequences

- This supersedes the design's provisional `202` response body.
- Non-`2xx` retry timing remains unverified; M8 must capture real-device behavior before activation.
- OwnTracks iOS 26.2.2 discards a report after a permanent `4xx`; an operator must repair the contract and explicitly create a fresh report rather than wait for retry.
- A timestamp-less status has no source event identifier. Exact identical snapshots deduplicate as retries and therefore do not advance receipt freshness; a changed status remains distinct.
- The M0 harness deliberately characterizes an array, alternate content type, empty body, duplicate, out-of-order delivery, and a `503` followed by `200` without claiming undocumented client backoff semantics.
