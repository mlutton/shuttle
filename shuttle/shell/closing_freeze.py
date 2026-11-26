"""Step 11, take the closing freeze: one commit of the place's files, made by Shuttle.

The git work is one command run to its end in a scope of its own with its limit on the scope,
the way a gate is run (shuttle.shell.gates): nothing here times it. Afterwards the scope is
stopped by name and seen empty, and why it ended is read from it. The step runs only when the
executor's boundary was seen empty, so nothing is writing the place. A freeze that does not give
a whole answer is a failed closing freeze: no closing fingerprint, the opening one stands.
"""

from shuttle.core import boundary, place
from shuttle.core.shapes import RunState
from shuttle.shell import stop_and_confirm_empty


def step(state: RunState) -> None:
    world, raw = state["world"], state["raw"]
    source = state["facts"]["header_source"]
    if source is None:
        raise RuntimeError("no header source: the document was not read")
    opening = state["stand_ins"]["opening_fingerprint"]
    scope = boundary.freeze_scope_name(source["request_id"])
    started = world.clock.now()
    environment = place.git_environment(world.environment.read_variable("PATH"))
    for variable in boundary.BUS_VARIABLES:  # to reach the user's systemd
        value = world.environment.read_variable(variable)
        if value is not None:
            environment[variable] = value
    answer = None
    try:
        command = place.freeze_argv(
            scope,
            float(raw.get("freeze_limit_seconds") or raw["time_limit_seconds"]),
            world.boundary.resolve(raw["place"]),
            opening["fingerprint"],
            source["request_id"],
        )
        answer = world.git.freeze(command, environment)
    except (OSError, ValueError):
        answer = None
    finally:  # whatever happened, nothing of the freeze's is left running
        properties = stop_and_confirm_empty.stop_boundary(world, scope)
    why = boundary.why_ended(properties)
    result = place.closing_result(answer, why, world.clock.now() - started)
    state["stand_ins"]["closing_freeze"] = result
    state["facts"]["closing_freeze"] = "ok" if result["ok"] else "failed"
    if not result["ok"]:
        state["problems"]["closing_freeze"] = result["problem"]
