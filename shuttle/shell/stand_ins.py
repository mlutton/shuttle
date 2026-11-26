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


def stop_and_confirm_empty(boundary: object) -> StepResult:
    return _stand_in("stop_confirmation")


def deliver(destination: object, closing_freeze: object) -> StepResult:
    return _stand_in("delivery")


def keep_files(kept: object) -> StepResult:
    return _stand_in("kept_files")


def tear_down(run_area: object) -> StepResult:
    return _stand_in("teardown")
