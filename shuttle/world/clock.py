"""Time: the real set."""

import datetime
import time

from shuttle.core.shapes import ClockOperations


def now() -> float:
    return time.monotonic()


def timestamp() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


def wait(seconds: float) -> None:
    time.sleep(seconds)


CLOCK = ClockOperations(now=now, timestamp=timestamp, wait=wait)
