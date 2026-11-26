"""Stand-ins: steps of a run whose real work belongs to a later increment.

Each has the signature the real step will have and returns a marked value, so
a receipt field fed by it says "cannot tell" instead of an invented value.
"""

from typing import Any

from shuttle.core import fixed
from shuttle.core.shapes import StepResult


def _stand_in(name: str, **extra: Any) -> StepResult:
    result = {fixed.STAND_IN_KEY: name}
    result.update(extra)
    return result


def run_gates(gates: object) -> StepResult:
    return _stand_in("gates")


def set_up_run_area(declared_setup: object) -> StepResult:
    return _stand_in("setup")


def take_opening_fingerprint(place: object) -> StepResult:
    return _stand_in("opening_fingerprint")


def stop_and_confirm_empty(boundary: object) -> StepResult:
    return _stand_in("stop_confirmation")


def take_closing_freeze(place: object, opening_fingerprint: object) -> StepResult:
    return _stand_in("closing_freeze")


def deliver(destination: object, closing_freeze: object) -> StepResult:
    return _stand_in("delivery")


def keep_files(kept: object) -> StepResult:
    return _stand_in("kept_files")


def tear_down(run_area: object) -> StepResult:
    return _stand_in("teardown")
