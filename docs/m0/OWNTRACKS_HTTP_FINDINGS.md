# M0 OwnTracks HTTP Findings

**Date:** 2026-09-10
**Evidence class:** official documentation plus synthetic local emulation

## Authoritative Sources

- [OwnTracks HTTP mode](https://owntracks.org/booklet/tech/http/)
- [OwnTracks JSON reference](https://owntracks.org/booklet/tech/json/)
- [OwnTracks waypoint behavior](https://owntracks.org/booklet/features/waypoints/)
- [OwnTracks Recorder HTTP implementation](https://github.com/owntracks/recorder#http-mode)

## Verified Documentation Facts

- HTTP mode sends normal OwnTracks JSON publishes with `POST` to one configured endpoint.
- HTTP Basic is directly supported and TLS is strongly recommended.
- Any `2xx` response marks a payload posted. An unreachable endpoint causes local queuing for later delivery. Non-`2xx` retry timing is not specified.
- A `200` response commonly contains `[]`; returned objects are for device-facing commands, cards, locations, or transitions.
- A zero-length publish can occur and is best ignored.
- `_type` identifies the payload type. The supported PRD types exist on iOS: `location`, `transition`, `waypoint`, and `status`.
- Location `tst` is a Unix timestamp in seconds. `lat` and `lon` are required for locations; `tid` is required in HTTP mode; `topic` is present only in HTTP payloads on supported app versions.
- Real-device verification later established that OwnTracks iOS 26.2.2 debug status has an `iOS` object and HTTP-added `topic`, but no `tst` or `tid`. Timestamp requirements are therefore type-specific.
- Transition events are `enter` or `leave`. Waypoints use `rid` as a stable region identifier and can produce transitions.
- The documentation describes individual JSON publishes, not an array batch request.

## Synthetic Exchange

Run:

```shell
make demo
```

The loopback-only harness sends eleven requests and stores only allowlisted summaries. The verified scenario includes all four supported types, an exact duplicate, event-time inversion, a JSON array, alternate and absent content types, an empty body, Basic authentication, identity fields, and a scripted `503` followed by a successful replay.

Expected aggregate evidence:

```json
{
  "duplicate_deliveries": 4,
  "out_of_order_observed": true,
  "payload_kinds": {"batch": 1, "empty": 1, "object": 9},
  "request_count": 11,
  "retry_sequence": [503, 200]
}
```

No raw body, coordinate, identity value, URL query, or credential is retained or printed by the harness.

## Decisions and Remaining Verification

ADR 0004 selects Basic over TLS. ADR 0005 selects a single-object body, `200 []` success, empty-body ignore, and `503` for transient failures.

The original synthetic status fixture included an invented `tst`; it characterized transport but did not prove the real iOS status contract. Actual iOS headers, exact retry schedule after non-`2xx`, offline queue ordering, and other version-specific optional fields were deliberately deferred to real-device commissioning. The fixture now mirrors the observed timestamp-less status shape.
