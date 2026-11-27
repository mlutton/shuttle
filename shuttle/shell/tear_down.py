"""Step 14, tear down: the run area is removed whole, whatever the ending.

It runs whenever the set-up ran, even for a run that was refused after it or that ended any way at
all. A tree removed leaves nothing behind and never follows a link (a path shared in place keeps
its original). A failure is reported in the receipt and
changes no ending. `remove` is also the run's last resort, called when the step did not run.
"""

from shuttle.core.shapes import RunState, StepResult


def remove(state: RunState) -> StepResult:
    """Remove the run area if there is one and it has not been removed; say how it went."""
    area = state.pop("run_area", None)
    if area is None:
        return {"failure": ""}
    try:
        state["world"].files.remove_tree(area)
    except FileNotFoundError:
        return {"failure": ""}  # already gone: nothing is left
    except OSError as error:
        return {"failure": f"the run area could not be removed ({type(error).__name__})"}
    return {"failure": ""}


def step(state: RunState) -> None:
    state["stand_ins"]["teardown"] = remove(state)
