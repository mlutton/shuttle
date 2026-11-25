"""Stand-ins: steps of a run whose real work belongs to a later increment.

Each has the signature the real step will have and returns a marked value, so
a receipt field fed by it says "cannot tell" instead of an invented value.
"""

import subprocess

from shuttle import fixed


def _stand_in(name, **extra):
    result = {fixed.STAND_IN_KEY: name}
    result.update(extra)
    return result


def start_in_boundary(launch_spec, environment):
    """Boundary: a plain child process, no containment yet. Raises when it cannot start."""
    process = subprocess.Popen(
        launch_spec["argv"],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return _stand_in("boundary", process=process)


def run_gates(gates):
    return _stand_in("gates")


def set_up_run_area(declared_setup):
    return _stand_in("setup")


def take_opening_fingerprint(place):
    return _stand_in("opening_fingerprint")


def stop_and_confirm_empty(boundary):
    return _stand_in("stop_confirmation")


def take_closing_freeze(place, opening_fingerprint):
    return _stand_in("closing_freeze")


def deliver(destination, closing_freeze):
    return _stand_in("delivery")


def keep_files(kept):
    return _stand_in("kept_files")


def tear_down(run_area):
    return _stand_in("teardown")
