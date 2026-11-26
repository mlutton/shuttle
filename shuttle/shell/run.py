"""The run form: the fifteen steps of a run, in order, as a thin shell.

Each step gathers facts from the world (files, the clock, a process) into one
facts dictionary and hands every decision to shuttle.core.decisions. The world is
reached only through the operations `run` is handed (shuttle.core.shapes.Operations):
this module imports nothing that touches it. Steps marked "stand-in" call a function in
shuttle.shell.stand_ins that returns a marked value.

One guarantee: a claimed run always ends with an outcome record, and a run that claimed nothing
ends with a one-line refusal. `_the_run` is the one outermost guard that owes it: installing the
signal handlers, every step, the final clean-up and the final print are inside it, and the
conclusion is decided there. Each step runs under `guarded` only to name the step that failed:
an error becomes a fact for the decisions. A signal only sets a fact (the handlers never raise),
and the wait polls for it. The ending is decided by a total function, the receipt falls back to a
minimal one, and a record that cannot be written is printed instead. A print that fails changes
neither the ending nor the exit code, which says only whether the record was written.
"""

import contextlib
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, TextIO

from shuttle import __version__
from shuttle.core import boundary, decisions, refusals
from shuttle.core.drivers import command
from shuttle.core.shapes import (
    Conclusion,
    Decision,
    HeaderSource,
    Operations,
    Receipt,
    RunState,
)
from shuttle.shell import (
    gates,
    input_checks,
    launch_executor,
    move_kept_files,
    records,
    stand_ins,
    stop_and_confirm_empty,
    wait_for_the_end,
)


def step_read_and_validate_document(state: RunState) -> None:
    """The first step of a run: read and validate the document, refuse one that holds a
    credential-like environment value before anything is claimed or written, print the id."""
    read_and_validate_document(state)
    raw = state.get("raw")
    refusal = refusals.check_credential_values(
        raw.get("environment") if isinstance(raw, dict) else None
    )
    if refusal and not state["facts"].get("unreadable"):
        state["facts"]["unreadable"] = True
        state["problem"] = refusal["problem"]
        return
    print_request_id(state)


def read_and_validate_document(state: RunState) -> None:
    """Read and validate the document; print nothing. The check form uses this one."""
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
    if isinstance(raw, dict) and "request_id" not in raw:
        raw = refusals.fill_request_id(raw, state["world"].identity.new_id())
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


def print_request_id(state: RunState) -> None:
    """The request id, first on standard output, once the document was read far enough to have one."""
    source = state["facts"].get("header_source")
    if source is not None:
        state["out"].write(source["request_id"] + "\n")
        state["out"].flush()


def header_source_of(state: RunState) -> HeaderSource:
    """The header source the steps after reading the document may rely on."""
    source = state["facts"].get("header_source")
    if source is None:
        raise RuntimeError("no header source: the document was not read")
    return source


def _note_on_standard_error(state: RunState) -> Callable[[str], None]:
    def note(line: str) -> None:
        state["err"].write(line + "\n")

    return note


def step_claim_request_id(state: RunState) -> None:
    facts, source, world = state["facts"], header_source_of(state), state["world"]
    header = decisions.build_header(
        "request", source, world.identity.new_id(), world.clock.timestamp()
    )
    try:
        records.claim_request_record(
            state["world"],
            source["records_location"],
            source["request_id"],
            {"header": header, "input": state["input_text"]},
            _note_on_standard_error(state),
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
    """The input checks that need the world, then the executor driver's check. Each is recorded
    under its own fact, so a run that fails both says the input check first."""
    world, facts = state["world"], state["facts"]
    refusal = refusals.first_refusal(input_checks.run_input_checks(world, state["raw"]))
    if refusal:
        facts["input_check"] = refusal["reason"]
        state["problems"]["input_check"] = refusal["problem"]
    reason, text = driver_check(world, state["raw"])
    if reason:
        facts["executor_driver_check"] = reason
        state["problems"]["executor_driver_check"] = text or ""


def driver_check(world: Operations, raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """The executor driver's check, and the check of the environment variables the document names."""
    settings = raw["executor"]["settings"]
    names = raw.get("environment", [])
    return decisions.executor_driver_check(
        settings,
        names,
        launch_executor.caller_environment(world, names),
        world.processes.find_program(settings["command"]),
    )


def step_run_gates(state: RunState) -> None:
    request_id = header_source_of(state)["request_id"]
    refusal, result = gates.run_gates(state["world"], request_id, state["raw"].get("gates", []))
    state["stand_ins"]["gates"] = result
    state["facts"]["gates"] = "ok"
    if refusal:
        state["facts"]["gates"] = "no" if refusal["reason"] == "gate_said_no" else "failed"
        state["problems"]["gates"] = refusal["problem"]


def step_set_up_run_area(state: RunState) -> None:  # stand-in
    state["stand_ins"]["setup"] = stand_ins.set_up_run_area(command.declare()["needs_setup"])
    state["facts"]["setup"] = decisions.result_status(state["stand_ins"]["setup"])


def step_take_opening_fingerprint(state: RunState) -> None:  # stand-in
    state["stand_ins"]["opening_fingerprint"] = stand_ins.take_opening_fingerprint(None)
    state["facts"]["opening_freeze"] = decisions.result_status(
        state["stand_ins"]["opening_fingerprint"]
    )


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
            "reference_hashes": decisions.verified_reference_hashes(
                state.get("raw"), facts.get("input_check")
            ),
        },
    )


def _minimal_receipt_line(error: BaseException) -> str:
    """The one line on standard error when the full receipt could not be built."""
    if isinstance(error, decisions.ReceiptNotBuilt):
        why = "fields refused: " + "; ".join(error.problems)
    else:
        why = type(error).__name__
    return " ".join(
        f"shuttle: the full receipt could not be built ({why}); the minimal receipt, with "
        "'cannot tell' for every field but the ending, was written instead".split()
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
    except BaseException as error:
        receipt = decisions.minimal_receipt(decision)
        state["err"].write(_minimal_receipt_line(error) + "\n")
    source = header_source_of(state)
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
            _note_on_standard_error(state),
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
    ("launch_executor", launch_executor.step),
    ("wait_for_the_end", wait_for_the_end.step),
    ("stop_everything_and_confirm_empty", stop_and_confirm_empty.step),
    ("observe", step_observe),
    ("take_closing_freeze", step_take_closing_freeze),
    ("deliver", step_deliver),
    ("move_kept_files", move_kept_files.step),
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
    """Signals only record which one came first. They never raise.

    Returns the undo, which the run itself never calls (only a test that installs them in its own
    process does): the handlers are never given back: the run is the command's whole life, and a signal that
    arrives after the conclusion (during the final flush, the exit or the interpreter's shutdown)
    must be caught, not end the process by that signal with the record already written.
    """

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
    return _the_run(steps, state)


def _the_run(steps: Sequence[tuple[str, Callable[[RunState], None]]], state: RunState) -> int:
    """The outermost guard of the run: whatever happens inside it, it owes a conclusion.

    Installing the handlers, every step, the final clean-up (ending the child, concluding) and the
    final print are inside it, and the handlers stay installed to the end of the process. The conclusion is the
    outcome record, or before a claim the one-line refusal. The per-step guards (`guarded`) are
    inside it only to name the step that failed. Returns the exit code.
    """
    try:
        _install_handlers(state)
        for name, step in steps:
            state["facts"].update(decisions.facts_after_signal(state["facts"], state["signal"]))
            if decisions.step_runs(name, state["facts"]):
                guarded(name, step, state)
    except BaseException as error:  # outside every step: nothing here may prevent the conclusion
        if "header_source" not in state["facts"]:
            state["problem"] = (
                f"the run could not be set up ({type(error).__name__}); nothing was done"
            )
    _clean_up(state)
    return _print_the_conclusion(state)


def _clean_up(state: RunState) -> None:
    """Whatever went wrong, nothing is left running, and there is a conclusion."""
    name = state.get("boundary_name")
    if name and "stop" not in state["facts"]:  # the stop step did not run, or did not finish
        try:
            empty = boundary.is_empty(stop_and_confirm_empty.stop_boundary(state["world"], name))
            state["facts"]["stop"] = "confirmed" if empty else "not_confirmed"
        except BaseException as error:  # the last look at the boundary failed
            state["facts"]["stop"] = "not_confirmed"
            state["problems"].setdefault(
                "stop_not_confirmed",
                f"the last check on the boundary failed ({type(error).__name__}); "
                "it cannot be said to have emptied",
            )
    if "conclusion" not in state:  # the last step did not run, or did not finish
        state["conclusion"] = conclude_run(state)


def _print_the_conclusion(state: RunState) -> int:
    """Print the conclusion. The exit code says whether the record was written, never whether the print worked."""
    conclusion = state["conclusion"]
    try:
        for line in conclusion["stdout"]:
            state["out"].write(line + "\n")
        state["out"].flush()
    except (OSError, ValueError) as error:  # the reader went away: the record stands
        with contextlib.suppress(Exception):
            state["err"].write(
                f"shuttle: the result could not be printed ({type(error).__name__}); "
                "the exit code still says whether the outcome record was written\n"
            )
    with contextlib.suppress(OSError, ValueError):
        for line in conclusion["stderr"]:
            state["err"].write(line + "\n")
    exit_code: int = conclusion["exit"]
    return exit_code
