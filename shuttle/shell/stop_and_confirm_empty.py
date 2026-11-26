"""Step 9, stop everything and confirm the boundary is empty, and read why it ended.

The boundary is stopped by name whatever ended the wait; stopping what is already gone does
nothing. Empty is seen from the scope's own state, not assumed. The scope's reason for ending
refines the cause of the wait: the limit is a time limit only when the scope says it timed out.
"""

import contextlib
from collections.abc import Mapping

from shuttle.core import boundary, decisions
from shuttle.core.shapes import Operations, RunState


def stop_boundary(world: Operations, name: str) -> Mapping[str, str] | None:
    """Stop the scope by name and read its state; None when it cannot be read."""
    unit = boundary.unit_of(name)
    with contextlib.suppress(OSError):
        world.boundary.stop(unit)
    try:
        properties = world.boundary.show(unit, boundary.PROPERTIES)
    except OSError:
        return None
    if properties.get("ActiveState") == "failed":
        with contextlib.suppress(OSError):
            world.boundary.forget(unit)
    return properties


def _executor_status(state: RunState) -> None:
    """The executor's exit and the moment it ended, once the boundary is empty."""
    world, facts = state["world"], state["facts"]
    process = state["boundary_process"]
    returncode = world.processes.wait(process, boundary.GRACE_SECONDS)
    facts["exit_code"], facts["child_signal"] = decisions.exit_facts(
        returncode,
        world.signals.name_of(-returncode) if returncode is not None and returncode < 0 else None,
    )
    state["executor_duration"] = world.clock.now() - state["clock_start"]
    state["ended_at"] = world.clock.timestamp()


def step(state: RunState) -> None:
    world, facts = state["world"], state["facts"]
    properties = stop_boundary(world, state["boundary_name"])
    empty = boundary.is_empty(properties)
    facts["stop"] = "confirmed" if empty else "not_confirmed"
    if not empty:
        state["problems"]["stop_not_confirmed"] = (
            "the boundary was stopped by name but not seen empty; the place is not to be trusted"
        )
    facts["wait"] = boundary.cause_of_end(facts.get("wait"), boundary.why_ended(properties))
    state["stand_ins"]["stop_confirmation"] = {
        "everything_stopped": empty,
        "stop_reason": "",
        "stop_asker": "",
    }
    _executor_status(state)
