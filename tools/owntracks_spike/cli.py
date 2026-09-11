"""Command-line entry point for the synthetic OwnTracks protocol spike."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from .harness import CaptureRecord, post, running_capture


DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "testdata" / "synthetic" / "owntracks"


def load_fixture(directory: Path, name: str) -> Any:
    """Load one explicitly synthetic JSON fixture."""

    with (directory / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def _summarize(records: Sequence[CaptureRecord], statuses: Sequence[int]) -> dict[str, Any]:
    event_times = [record.payload.device_time for record in records if record.payload.device_time]
    digests = [record.payload.digest for record in records]
    return {
        "authorization_schemes": sorted({record.authorization_scheme for record in records}),
        "content_types": sorted({record.content_type for record in records}),
        "duplicate_deliveries": len(digests) - len(set(digests)),
        "identity_fields_observed": sorted(
            {field for record in records for field in record.payload.identity_fields}
        ),
        "out_of_order_observed": any(later < earlier for earlier, later in zip(event_times, event_times[1:])),
        "payload_kinds": dict(sorted(Counter(record.payload.kind for record in records).items())),
        "request_count": len(records),
        "retry_sequence": list(statuses[-2:]),
        "source_types": dict(sorted(Counter(record.payload.source_type for record in records).items())),
        "status_counts": dict(sorted(Counter(str(status) for status in statuses).items())),
    }


def run_demo(fixture_directory: Path = DEFAULT_FIXTURES) -> dict[str, Any]:
    """Exercise all M0 wire-shape scenarios against an ephemeral endpoint."""

    current = load_fixture(fixture_directory, "location-current.json")
    earlier = load_fixture(fixture_directory, "location-earlier.json")
    transition = load_fixture(fixture_directory, "transition.json")
    waypoint = load_fixture(fixture_directory, "waypoint.json")
    status = load_fixture(fixture_directory, "status.json")
    batch = load_fixture(fixture_directory, "batch.json")
    response_plan = [200] * 9 + [503, 200]
    auth = ("synthetic-user", "synthetic-password")

    with running_capture(response_plan) as (url, state):
        results = [
            post(url, current, basic_auth=auth),
            post(url, current, basic_auth=auth),
            post(url, earlier, basic_auth=auth),
            post(url, transition, basic_auth=auth),
            post(url, waypoint, basic_auth=auth),
            post(url, status, basic_auth=auth),
            post(url, batch, basic_auth=auth),
            post(url, status, basic_auth=auth, content_type="text/plain"),
            post(url, None, basic_auth=auth, content_type=None),
            post(url, current, basic_auth=auth),
            post(url, current, basic_auth=auth),
        ]
        records = state.snapshot()

    return _summarize(records, [result.status for result in results])


def main(argv: Sequence[str] | None = None) -> int:
    """Run the M0 demo and emit only allowlisted aggregate evidence."""

    parser = argparse.ArgumentParser(description="Run the synthetic OwnTracks HTTP protocol spike")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    args = parser.parse_args(argv)
    print(json.dumps(run_demo(args.fixtures), indent=2, sort_keys=True))
    return 0
