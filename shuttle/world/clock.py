"""Time: the real set."""

import datetime
import time

from shuttle.core.shapes import ClockOperations


def now() -> float:
    return time.monotonic()


def timestamp() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


CLOCK = ClockOperations(now=now, timestamp=timestamp)
