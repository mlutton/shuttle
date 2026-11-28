"""Step 7, launch the executor: start it in the boundary, with the limit and its reach.

The boundary is a systemd user scope around bubblewrap (shuttle.core.boundary). The scope owns the
time limit; nothing here times the executor. The reach is built from resolved paths (the shell's
`the_reach` finds them), so the box binds what the checks looked at.
"""

from collections.abc import Sequence

from shuttle.core import boundary, decisions, fixed, notice, run_area
from shuttle.core.shapes import Operations, RunState
from shuttle.shell import kinds, statement_schema, the_driver, the_reach


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
        run_area.statement_path(state["run_area"]),
        statement_schema.read_schema(world),
        raw.get("references", []),
        the_driver.of(raw).STATEMENT,
    )
    name = decisions.join_path(state["run_area"], run_area.INSTRUCTION_NAME)
    world.files.write_new(name, text)
    return name


def step(state: RunState) -> None:
    world = state["world"]
    raw = state["raw"]
    names = raw.get("environment", [])
    spec = the_driver.of(raw).launch(
        raw["executor"]["settings"], the_driver.launch_context(world, raw, state["run_area"])
    )
    state["program"] = spec["argv"][0]
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
    name = boundary.scope_name(source["request_id"], state["run_part"])
    resolve = world.boundary.resolve
    _, changes = decisions.standard_settings(raw)
    seen = the_reach.shown(world, raw)
    if seen is None:
        raise RuntimeError("no place: the document was not checked")
    area = resolve(state["run_area"])
    reach: boundary.Reach = {
        **seen,
        "area": area,
        "home": run_area.home_path(area),
        "tmp": run_area.tmp_path(area),
        "place_writable": boundary.place_is_writable(changes),
        "records": resolve(source["records_location"]),
    }
    report = world.processes.open_report()
    argv = boundary.launch_argv(
        name, float(raw["time_limit_seconds"]), spec["argv"], names, reach, report
    )
    state["started_at"] = world.clock.timestamp()
    state["clock_start"] = world.clock.now()
    state["boundary_process"] = world.processes.start(
        argv, environment, report, instruction_file, spec.get("output_to")
    )
    state["boundary_name"] = name
    # Peak memory and processor time are not read from the boundary yet.
    state["stand_ins"]["boundary"] = {fixed.STAND_IN_KEY: "boundary measurements"}
    state["facts"]["launch"] = "ok"
