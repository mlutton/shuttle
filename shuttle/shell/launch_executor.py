"""Step 7, launch the executor: start it in the boundary, with the limit and the records protected.

The boundary is a systemd user scope around bubblewrap (shuttle.core.boundary). The scope owns the
time limit; nothing here times the executor.
"""

from collections.abc import Sequence

from shuttle.core import boundary, decisions, fixed
from shuttle.core.drivers import command
from shuttle.core.shapes import Operations, RunState


def caller_environment(world: Operations, names: Sequence[str]) -> dict[str, str]:
    """The variables the run may look at: PATH and the named ones, those that are set."""
    found: dict[str, str] = {}
    for name in ("PATH", *names):
        value = world.environment.read_variable(name)
        if value is not None:
            found[name] = value
    return found


def step(state: RunState) -> None:
    world = state["world"]
    raw = state["raw"]
    names = raw.get("environment", [])
    spec = command.launch(raw["executor"]["settings"])
    environment = decisions.build_environment(names, caller_environment(world, names))
    # The executor's own environment is cleared of these again inside the boundary.
    for variable in boundary.BUS_VARIABLES:
        value = world.environment.read_variable(variable)
        if value is not None:
            environment.setdefault(variable, value)
    source = state["facts"]["header_source"]
    if source is None:
        raise RuntimeError("no header source: the document was not read")
    name = boundary.scope_name(source["request_id"])
    protected = [world.boundary.resolve(source["records_location"])]
    report = world.processes.open_report()
    argv = boundary.launch_argv(
        name, float(raw["time_limit_seconds"]), spec["argv"], names, protected, report
    )
    state["started_at"] = world.clock.timestamp()
    state["clock_start"] = world.clock.now()
    state["boundary_process"] = world.processes.start(argv, environment, report)
    state["boundary_name"] = name
    # Peak memory and processor time are not read from the boundary yet.
    state["stand_ins"]["boundary"] = {fixed.STAND_IN_KEY: "boundary measurements"}
    state["facts"]["launch"] = "ok"
