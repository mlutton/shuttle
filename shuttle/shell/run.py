"""The run form: the fifteen steps of a run, in order, as a thin shell.

Each step gathers facts from the world (files, the clock, a process) into one
facts dictionary and hands every decision to shuttle.core.decisions. The world is
reached only through the operations `run` is handed (shuttle.core.shapes.Operations):
this module imports nothing that touches it. Steps marked "stand-in" call a function in
shuttle.shell.stand_ins that returns a marked value.

One guarantee: once the request id is claimed, every step runs under `guarded`
and the conclusion runs in a `finally`. An error becomes a fact for the decisions.
A signal only sets a fact (the handlers never raise), and the wait polls for it.
The ending is decided by a total function, the receipt falls back to a minimal
one, and a record that cannot be written is printed instead.
"""

import contextlib
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import TextIO

from shuttle import __version__
from shuttle.core import decisions, fixed
from shuttle.core.drivers import command
from shuttle.core.shapes import (
    Conclusion,
    Decision,
    HeaderSource,
    LaunchSpec,
    Operations,
    Process,
    Receipt,
    RunState,
    StepResult,
)
from shuttle.shell import records, stand_ins

# The deadline (the time limit) and this grace are stand-ins until the boundary owns the time limit.
END_GRACE_SECONDS = 3  # as of 2026-11-25: seconds between asking a child to end and killing it; a fixed policy, not read from the world
_POLL_SECONDS = 0.05


def _exited_within(world: Operations, process: Process, seconds: float) -> bool:
    deadline = world.clock.now() + seconds
    while world.processes.poll(process) is None:
        if world.clock.now() >= deadline:
            return False
        world.clock.wait(_POLL_SECONDS)
    return True


def end_child(world: Operations, process: Process) -> str:
    """End the direct child, for every cause: ask, wait a short grace (seconds), then kill.

    Returns "ended" or "not_confirmed". Whether everything the child started is gone
    is a stand-in (step 9); only the direct child is ended here.
    """
    if world.processes.poll(process) is None:
        with contextlib.suppress(OSError):
            world.processes.ask_to_end(process)
        if not _exited_within(world, process, END_GRACE_SECONDS):
            with contextlib.suppress(OSError):
                world.processes.kill(process)
            if not _exited_within(world, process, END_GRACE_SECONDS):
                return "not_confirmed"
    return "ended"


def wait_for_the_cause(
    world: Operations,
    process: Process,
    limit_seconds: float,
    get_signal: Callable[[], str | None],
) -> str:
    """Poll until the child exits, a signal is seen, or the limit passes. Returns the first cause seen."""
    deadline = world.clock.now() + limit_seconds
    while True:
        cause = decisions.wait_cause(
            world.processes.poll(process) is not None,
            world.clock.now() >= deadline,
            get_signal(),
        )
        if cause:
            return cause
        world.clock.wait(_POLL_SECONDS)


def _caller_environment(world: Operations, names: Sequence[str]) -> dict[str, str]:
    """The variables the run may look at: PATH and the named ones, those that are set."""
    found: dict[str, str] = {}
    for name in ("PATH", *names):
        value = world.environment.read_variable(name)
        if value is not None:
            found[name] = value
    return found


def start_in_boundary(
    world: Operations, launch_spec: LaunchSpec, environment: Mapping[str, str]
) -> StepResult:
    """Boundary: a plain child process, no containment yet. Raises when it cannot start.

    A stand-in until the boundary is built.
    """
    process = world.processes.start(launch_spec["argv"], environment)
    return {fixed.STAND_IN_KEY: "boundary", "process": process}


def step_read_and_validate_document(state: RunState) -> None:
    facts = state["facts"]
    try:
        data = state["world"].files.read(state["document_path"])
        text = data.decode("utf-8")
        raw = json.loads(text)
    except (OSError, ValueError) as error:
        facts["unreadable"] = True
        state["problem"] = (
            f"cannot read the input document as JSON ({type(error).__name__}); nothing was done; give a readable JSON file"
        )
        return
    state["raw"] = raw
    state["input_text"] = text
    state["input_hash"] = hashlib.sha256(data).hexdigest()
    checked = decisions.validate_document(raw)
    if checked["header_source"] is None:
        facts["unreadable"] = True
        state["problem"] = "{}; nothing was done; fix the input document and run again".format(
            checked["problem"]
        )
        return
    facts["header_source"] = checked["header_source"]
    if checked["refusal"]:
        facts["input_check"] = checked["refusal"]["reason"]
        state["problems"]["input_check"] = checked["problem"] or ""
    state["out"].write(checked["header_source"]["request_id"] + "\n")
    state["out"].flush()


def _header_source(state: RunState) -> HeaderSource:
    """The header source the steps after reading the document may rely on."""
    source = state["facts"].get("header_source")
    if source is None:
        raise RuntimeError("no header source: the document was not read")
    return source


def step_claim_request_id(state: RunState) -> None:
    facts, source, world = state["facts"], _header_source(state), state["world"]
    header = decisions.build_header(
        "request", source, world.identity.new_id(), world.clock.timestamp()
    )
    try:
        records.claim_request_record(
            state["world"],
            source["records_location"],
            source["request_id"],
            {"header": header, "input": state["input_text"]},
        )
    except records.RecordNotBuilt as error:
        facts["id_claim"] = "unusable"  # nothing is claimed; no record is written either way
        state["problem"] = decisions.claim_problem(
            "not_built", source["request_id"], source["records_location"], str(error)
        )
    except FileExistsError as error:
        facts["id_claim"] = "used"
        state["problem"] = decisions.claim_problem(
            "used", source["request_id"], source["records_location"], type(error).__name__
        )
    except OSError as error:
        facts["id_claim"] = "unusable"
        state["problem"] = decisions.claim_problem(
            "unusable", source["request_id"], source["records_location"], type(error).__name__
        )
    else:
        facts["id_claim"] = "ok"


def step_run_input_checks_and_executor_driver_check(state: RunState) -> None:
    # The input checks are real in the first step (the document's shape). This step is the
    # executor driver's check and the check of the named environment variables.
    world = state["world"]
    settings = state["raw"]["executor"]["settings"]
    names = state["raw"].get("environment", [])
    reason, text = decisions.executor_driver_check(
        settings["command"],
        names,
        _caller_environment(world, names),
        world.processes.find_program(settings["command"]),
    )
    if reason:
        state["facts"]["executor_driver_check"] = reason
        state["problems"]["executor_driver_check"] = text or ""


def step_run_gates(state: RunState) -> None:  # stand-in
    state["stand_ins"]["gates"] = stand_ins.run_gates([])
    state["facts"]["gates"] = decisions.result_status(state["stand_ins"]["gates"])


def step_set_up_run_area(state: RunState) -> None:  # stand-in
    state["stand_ins"]["setup"] = stand_ins.set_up_run_area(command.declare()["needs_setup"])
    state["facts"]["setup"] = decisions.result_status(state["stand_ins"]["setup"])


def step_take_opening_fingerprint(state: RunState) -> None:  # stand-in
    state["stand_ins"]["opening_fingerprint"] = stand_ins.take_opening_fingerprint(None)
    state["facts"]["opening_freeze"] = decisions.result_status(
        state["stand_ins"]["opening_fingerprint"]
    )


def step_launch_executor(state: RunState) -> None:
    world = state["world"]
    spec = command.launch(state["raw"]["executor"]["settings"])
    names = state["raw"].get("environment", [])
    environment = decisions.build_environment(names, _caller_environment(world, names))
    state["started_at"] = world.clock.timestamp()
    state["clock_start"] = world.clock.now()
    state["stand_ins"]["boundary"] = start_in_boundary(world, spec, environment)
    state["facts"]["launch"] = "ok"


def step_wait_for_the_end(state: RunState) -> None:
    world = state["world"]
    process = state["stand_ins"]["boundary"]["process"]
    facts = state["facts"]
    try:
        cause = wait_for_the_cause(
            world, process, float(state["raw"]["time_limit_seconds"]), lambda: state["signal"]
        )
        facts["wait"] = cause
        if cause != "exited" and end_child(world, process) == "not_confirmed":
            facts["stop"] = "not_confirmed"
    finally:
        if world.processes.poll(process) is None:  # the wait itself broke: still end the child
            end_child(world, process)
    returncode = world.processes.poll(process)
    facts["exit_code"], facts["child_signal"] = decisions.exit_facts(
        returncode,
        world.signals.name_of(-returncode) if returncode is not None and returncode < 0 else None,
    )
    state["executor_duration"] = world.clock.now() - state["clock_start"]
    state["ended_at"] = world.clock.timestamp()


def step_stop_everything_and_confirm_empty(state: RunState) -> None:  # stand-in
    state["stand_ins"]["stop_confirmation"] = stand_ins.stop_and_confirm_empty(
        state["stand_ins"]["boundary"]
    )
    status = decisions.result_status(state["stand_ins"]["stop_confirmation"])
    if (
        state["facts"].get("stop") != "not_confirmed"
    ):  # the wait may already have failed to end the child
        state["facts"]["stop"] = "confirmed" if status == "ok" else "not_confirmed"


def step_observe(state: RunState) -> None:
    state["executor_driver_observations"] = command.observe()


def step_take_closing_freeze(state: RunState) -> None:  # stand-in
    state["stand_ins"]["closing_freeze"] = stand_ins.take_closing_freeze(
        None, state["stand_ins"].get("opening_fingerprint")
    )
    state["facts"]["closing_freeze"] = decisions.result_status(state["stand_ins"]["closing_freeze"])


def step_deliver(state: RunState) -> None:  # stand-in
    state["stand_ins"]["delivery"] = stand_ins.deliver(
        None, state["stand_ins"].get("closing_freeze")
    )
    state["facts"]["delivery"] = decisions.result_status(state["stand_ins"]["delivery"])


def step_move_kept_files(state: RunState) -> None:  # stand-in
    state["stand_ins"]["kept_files"] = stand_ins.keep_files([])


def step_tear_down(state: RunState) -> None:  # stand-in
    state["stand_ins"]["teardown"] = stand_ins.tear_down(None)


def _full_receipt(state: RunState, decision: Decision) -> Receipt:
    facts, world = state["facts"], state["world"]
    return decisions.build_receipt(
        decision,
        {
            "receipt_id": world.identity.new_id(),
            "execution_version": __version__,
            "host": world.identity.host_name(),
            "input_hash": state.get("input_hash"),
            "launched": facts.get("launch") == "ok",
            "started_at": state.get("started_at"),
            "ended_at": state.get("ended_at"),
            "executor_duration": state.get("executor_duration"),
            "exit_code": facts.get("exit_code"),
            "signal": facts.get("child_signal"),
            "executor_driver_observations": state.get("executor_driver_observations"),
            "stand_ins": state["stand_ins"],
            "reason_text": decisions.reason_text(decision, state["problems"]),
        },
    )


def conclude_run(state: RunState) -> Conclusion:
    """The conclusion: decide, build the receipt, write the record. Each part has its own fallback."""
    facts = state["facts"]
    kind = decisions.outcome_kind(facts)
    if kind == "unreadable":
        return decisions.conclude({"kind": "unreadable", "problem": state.get("problem")})
    decision = decisions.decide_ending(facts)
    if kind == "not_recorded":
        return decisions.conclude(
            {"kind": "not_recorded", "decision": decision, "problem": state.get("problem")}
        )
    try:
        receipt = _full_receipt(state, decision)
    except BaseException:
        receipt = decisions.minimal_receipt(decision)
    source = _header_source(state)
    try:
        world = state["world"]
        header = decisions.build_header(
            "outcome", source, world.identity.new_id(), world.clock.timestamp()
        )
        path = records.write_outcome_record(
            world,
            source["records_location"],
            source["request_id"],
            {"header": header, "receipt": receipt},
        )
    except BaseException as error:  # nothing may prevent the receipt: print it instead
        return decisions.conclude(
            {
                "kind": "write_failed",
                "decision": decision,
                "problem": type(error).__name__,
                "receipt_text": json.dumps(receipt, indent=2, default=str),
            }
        )
    return decisions.conclude({"kind": "written", "decision": decision, "path": path})


def step_write_outcome_record(state: RunState) -> None:
    state["conclusion"] = conclude_run(state)


# The ordered steps of a run are the design. That `run_steps` takes the table as an argument is a test
# seam only for the placeholder steps, which touch nothing; as each becomes a real step that uses the
# operations, its failures are made through them and the argument goes.
STEPS = (
    ("read_and_validate_document", step_read_and_validate_document),
    ("claim_request_id", step_claim_request_id),
    ("run_input_checks_and_executor_driver_check", step_run_input_checks_and_executor_driver_check),
    ("run_gates", step_run_gates),
    ("set_up_run_area", step_set_up_run_area),
    ("take_opening_fingerprint", step_take_opening_fingerprint),
    ("launch_executor", step_launch_executor),
    ("wait_for_the_end", step_wait_for_the_end),
    ("stop_everything_and_confirm_empty", step_stop_everything_and_confirm_empty),
    ("observe", step_observe),
    ("take_closing_freeze", step_take_closing_freeze),
    ("deliver", step_deliver),
    ("move_kept_files", step_move_kept_files),
    ("tear_down", step_tear_down),
    ("write_outcome_record", step_write_outcome_record),
)


def guarded(name: str, step: Callable[[RunState], None], state: RunState) -> None:
    """Run one step. An error becomes a fact; it never escapes."""
    facts = state["facts"]
    try:
        step(state)
    except BaseException as error:
        facts.update(decisions.facts_after_error(name))
        failed = decisions.failed_step_after_error(name)
        if failed:
            state["problems"][failed] = "the step {} failed ({}); nothing more can be said".format(
                name.replace("_", " "),
                type(error).__name__,
            )
        elif name == "read_and_validate_document":
            state["problem"] = (
                f"the input document could not be checked ({type(error).__name__}); nothing was done"
            )


def _install_handlers(state: RunState) -> Callable[[], None]:
    """Signals only record which one came first. They never raise. Returns the undo."""

    def note(name: str) -> None:
        if state["signal"] is None:
            state["signal"] = name

    restore: Callable[[], None] = state["world"].signals.install(note)
    return restore


def run(document_path: str, out: TextIO, err: TextIO, world: Operations) -> int:
    """Run one input document end to end. Returns the exit code.

    world: everything the run does to the world goes through it; the command passes the real set.
    """
    return run_steps(STEPS, document_path, out, err, world)


def run_steps(
    steps: Sequence[tuple[str, Callable[[RunState], None]]],
    document_path: str,
    out: TextIO,
    err: TextIO,
    world: Operations,
) -> int:
    """`run` over any ordered table of steps; `run` passes the real one (STEPS).

    The table is plain data: the order of a run and the function each step is. It is an
    argument so a by-value test can put a step that fails where one of the placeholder steps
    (gates, set-up, fingerprints, stop confirmation, closing, delivery, tidying, tear-down)
    stands: they touch nothing, so no operation can be made to fail inside them.
    """
    state: RunState = {
        "document_path": document_path,
        "out": out,
        "err": err,
        "world": world,
        "facts": {},
        "stand_ins": {},
        "problems": {},
        "signal": None,
    }
    restore = _install_handlers(state)
    try:
        for name, step in steps:
            state["facts"].update(decisions.facts_after_signal(state["facts"], state["signal"]))
            if decisions.step_runs(name, state["facts"]):
                guarded(name, step, state)
    finally:
        boundary = state["stand_ins"].get("boundary")
        if boundary and boundary.get("process") is not None:
            end_child(world, boundary["process"])  # whatever went wrong, nothing is left running
        if "conclusion" not in state:  # the last step did not run, or did not finish
            state["conclusion"] = conclude_run(state)
        restore()
    for line in state["conclusion"]["stdout"]:
        out.write(line + "\n")
    for line in state["conclusion"]["stderr"]:
        err.write(line + "\n")
    exit_code: int = state["conclusion"]["exit"]
    return exit_code
