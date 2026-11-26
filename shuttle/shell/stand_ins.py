"""Stand-ins: steps of a run whose real work belongs to a later increment.

Each has the signature the real step will have and returns a marked value, so
a receipt field fed by it says "not built" instead of an invented value. (A real step will
say "looked, found nothing" by returning an empty value; a key it leaves out, or `None`, reads
as "cannot tell".)
"""

from shuttle.core import fixed
from shuttle.core.shapes import StepResult


def _stand_in(name: str) -> StepResult:
    return {fixed.STAND_IN_KEY: name}


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


def tear_down(run_area: object) -> StepResult:
    return _stand_in("teardown")
