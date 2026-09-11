"""Injectable UTC clock boundary."""

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def unix_milliseconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return int(value.timestamp() * 1000)
