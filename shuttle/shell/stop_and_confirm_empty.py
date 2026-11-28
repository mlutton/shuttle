"""Step 9, stop everything and confirm the scope is empty, and read why it ended.

The scope is stopped by name whatever ended the wait; stopping what is already gone does
nothing. Empty is seen from the scope's own state, not assumed. The scope's reason for ending
refines the cause of the wait: the limit is a time limit only when the scope says it timed out.
"""

import contextlib
from collections.abc import Mapping

from shuttle.core import boundary, decisions, fixed
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


def _executor_status(state: RunState, returncode: int | None) -> None:
    """The executor's exit and the moment it ended, once the boundary is empty."""
    world, facts = state["world"], state["facts"]
    facts["exit_code"], facts["child_signal"] = decisions.exit_facts(
        returncode,
        world.signals.name_of(-returncode) if returncode is not None and returncode < 0 else None,
    )
    if facts.get("launch") in ("failed", "program_not_started"):
        facts["exit_code"] = facts["child_signal"] = (
            None  # no end was reported: no exit code or signal to claim
        )
    else:
        # What ended is the box's own tool, which reports a child killed by signal n as 128 + n,
        # as a script that exits with that number is reported: the signal is not read from it.
        facts["child_signal"] = fixed.CANNOT_TELL
    if facts.get("wait") == "memory_limit":
        # The scope ended the program, and whether bubblewrap saw the kill first (and reported it
        # as 128 + 9) or was ended with it (and reported nothing) is a race: the number, when
        # there is one, is not the program's own exit.
        facts["exit_code"] = None
    state["executor_duration"] = world.clock.now() - state["clock_start"]
    state["ended_at"] = world.clock.timestamp()


def step(state: RunState) -> None:
    world, facts = state["world"], state["facts"]
    properties = stop_boundary(world, state["boundary_name"])
    empty = boundary.scope_is_empty(properties)
    facts["stop"] = "confirmed" if empty else "not_confirmed"
    if not empty:
        state["problems"]["stop_not_confirmed"] = (
            "the boundary was stopped by name but not seen empty; the place is not to be trusted"
        )
    capped = state.get("memory_limit_bytes") is not None
    facts["wait"] = boundary.cause_of_end(facts.get("wait"), boundary.why_ended(properties, capped))
    report = world.processes.read_report(state["boundary_process"])
    returncode = world.processes.wait(state["boundary_process"], boundary.GRACE_SECONDS)
    if boundary.launch_failed(facts["wait"], report):
        facts["launch"] = "failed"
        state["problems"]["launch"] = (
            "the boundary ended without ever starting the executor; the executor did not run"
        )
    elif boundary.program_not_started(facts["wait"], report, returncode):
        facts["launch"] = "program_not_started"
        state["problems"]["launch"] = boundary.program_not_started_line(state.get("program"))
    state["stand_ins"]["stop_confirmation"] = {
        "everything_stopped": empty,
        "stop_reason": "",
        "stop_asker": "",
    }
    _executor_status(state, returncode)
