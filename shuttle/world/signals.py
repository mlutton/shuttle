"""Signals: the real set."""

import signal
from collections.abc import Callable
from typing import Any

from shuttle.core.shapes import SignalOperations

HANDLED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def install(on_signal: Callable[[str], None]) -> Callable[[], None]:
    """Call on_signal with the name of each of SIGINT, SIGTERM and SIGHUP; return the undo."""

    def handler(number: int, frame: object) -> None:
        on_signal(signal.Signals(number).name)

    previous: dict[int, Any] = {number: signal.signal(number, handler) for number in HANDLED}

    def restore() -> None:
        for number, old in previous.items():
            signal.signal(number, old)

    return restore


def name_of(number: int) -> str | None:
    try:
        return signal.Signals(number).name
    except ValueError:
        return None


SIGNALS = SignalOperations(install=install, name_of=name_of)
