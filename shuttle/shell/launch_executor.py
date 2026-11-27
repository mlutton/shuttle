"""Step 7, launch the executor: start it in the boundary, with the limit and the records protected.

The boundary is a systemd user scope around bubblewrap (shuttle.core.boundary). The scope owns the
time limit; nothing here times the executor.
"""

from collections.abc import Sequence

from shuttle.core import boundary, decisions, fixed, notice, run_area
from shuttle.core.drivers import command
from shuttle.core.shapes import Operations, RunState
from shuttle.shell import kinds, statement_schema


def caller_environment(world: Operations, names: Sequence[str]) -> dict[str, str]:
    """The variables the run may look at: PATH and the named ones, those that are set."""
    found: dict[str, str] = {}
    for name in ("PATH", *names):
        value = world.environment.read_variable(name)
        if value is not None:
            found[name] = value
    return found


def put_instruction(state: RunState) -> str:
    """The instruction the executor is given (the caller's and the notice) put in a file in the
    run area, for its standard input. Never on the command line. Returns the file's name."""
    world, raw = state["world"], state["raw"]
    expects = kinds.read_kinds(world)[raw["kind"]]
    text = notice.with_notice(
        raw.get("instruction"),
        expects,
        raw.get("statement_location"),
        statement_schema.read_schema(world),
        raw.get("references", []),
    )
    name = decisions.join_path(state["run_area"], run_area.INSTRUCTION_NAME)
    world.files.write_new(name, text)
    return name


def step(state: RunState) -> None:
    world = state["world"]
    raw = state["raw"]
    names = raw.get("environment", [])
    spec = command.launch(raw["executor"]["settings"])
    environment = decisions.build_environment(names, caller_environment(world, names))
    environment.update(state.get("setup_variables", {}))
    instruction_file = put_instruction(state)
    # The executor's own environment is cleared of these again inside the boundary.
    for variable in boundary.BUS_VARIABLES:
        value = world.environment.read_variable(variable)
        if value is not None:
            environment.setdefault(variable, value)
    source = state["facts"]["header_source"]
    if source is None:
        raise RuntimeError("no header source: the document was not read")
    name = boundary.scope_name(source["request_id"])
    # The records (and the files kept beside them) and every reference are read-only to the executor.
    protected = [
        world.boundary.resolve(path)
        for path in [source["records_location"], *(r["path"] for r in raw.get("references", []))]
    ]
    report = world.processes.open_report()
    argv = boundary.launch_argv(
        name,
        float(raw["time_limit_seconds"]),
        spec["argv"],
        names,
        protected,
        report,
        world.boundary.resolve(raw["place"]),
    )
    state["started_at"] = world.clock.timestamp()
    state["clock_start"] = world.clock.now()
    state["boundary_process"] = world.processes.start(
        argv, environment, report, instruction_file
    )
    state["boundary_name"] = name
    # Peak memory and processor time are not read from the boundary yet.
    state["stand_ins"]["boundary"] = {fixed.STAND_IN_KEY: "boundary measurements"}
    state["facts"]["launch"] = "ok"
