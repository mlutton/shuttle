"""Step 14, tear down: the run area is removed whole, whatever the ending.

It runs whenever the set-up ran, even for a run that was refused after it or that ended any way at
all. A tree removed leaves nothing behind and never follows a link (a path shared in place keeps
its original). A failure is reported in the receipt and
changes no ending. The area's lock goes after the area, so no moment exists when the area is
there and its lock is free; a lock that cannot be removed is harmless, a later run's sweep removes
it. An area that could not be removed keeps its lock until the process ends. `remove` is also the run's last resort, called when the step did not run.
"""

import contextlib

from shuttle.core import run_area
from shuttle.core.shapes import RunState, StepResult


def remove(state: RunState) -> StepResult:
    """Remove the run area if there is one and it has not been removed; say how it went."""
    area = state.pop("run_area", None)
    if area is None:
        return {"failure": ""}
    files = state["world"].files
    try:
        files.remove_tree(area)
    except FileNotFoundError:
        pass  # already gone: nothing is left
    except OSError as error:
        return {"failure": f"the run area could not be removed ({type(error).__name__})"}
    with contextlib.suppress(OSError):
        files.release_lock(run_area.lock_path(area), True)
    return {"failure": ""}


def step(state: RunState) -> None:
    state["stand_ins"]["teardown"] = remove(state)
