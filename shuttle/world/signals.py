"""Signals: the real set."""

import signal
from collections.abc import Callable
from typing import Any

from shuttle.core.shapes import SignalOperations

HANDLED = (
    signal.SIGINT,
    signal.SIGTERM,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGUSR1,
    signal.SIGUSR2,
    signal.SIGALRM,
)


def install(on_signal: Callable[[str], None]) -> Callable[[], None]:
    """Call on_signal with the name of each signal in HANDLED (the ones that ask a run to stop); return the undo."""

    def handler(number: int, frame: object) -> None:
        on_signal(signal.Signals(number).name)

    previous: dict[int, Any] = {}

    def restore() -> None:
        for number, old in previous.items():
            signal.signal(number, old)

    try:
        for number in HANDLED:
            previous[number] = signal.signal(number, handler)
    except BaseException:  # leave nothing half installed
        restore()
        raise
    return restore


def name_of(number: int) -> str | None:
    try:
        return signal.Signals(number).name
    except ValueError:
        return None


SIGNALS = SignalOperations(install=install, name_of=name_of)
