"""M3 boot sentinel for the durable worker boundary implemented in M4."""

from datetime import datetime, timezone
from threading import Event

from .config import Configuration
from .database import connect
from .clock import unix_milliseconds


def heartbeat(configuration: Configuration, now_ms: int | None = None) -> None:
    stamp = now_ms if now_ms is not None else unix_milliseconds(datetime.now(timezone.utc))
    connection = connect(configuration)
    try:
        connection.execute(
            "INSERT INTO service_heartbeats VALUES ('processor', ?, 'healthy') ON CONFLICT(service) DO UPDATE SET last_success_ms=excluded.last_success_ms, status=excluded.status",
            (stamp,),
        )
        connection.commit()
    finally:
        connection.close()


def serve(configuration: Configuration, stop: Event, interval_seconds: float = 30) -> None:
    while not stop.is_set():
        heartbeat(configuration)
        stop.wait(interval_seconds)
