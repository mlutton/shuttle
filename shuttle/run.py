"""The run form: the fifteen steps of a run, in order, as a thin shell.

Each step gathers facts from the world (files, the clock, a process) into one
facts dictionary and hands every decision to shuttle.core. Steps marked
"stand-in" call a function in shuttle.stand_ins that returns a marked value.

One guarantee: once the request id is claimed, every step runs under `guarded`
and the conclusion runs in a `finally`. An error becomes a fact for the core.
A signal only sets a fact (the handlers never raise), and the wait polls for it.
The ending is decided by a total function, the receipt falls back to a minimal
one, and a record that cannot be written is printed instead.
"""

import contextlib
import datetime
import hashlib
import json
import os
import signal
import socket
import subprocess
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from types import FrameType
from typing import Any, TextIO

from shuttle import __version__, command_driver, core, fixed, records, stand_ins
from shuttle.shapes import Conclusion, Decision, Facts, Receipt, State

END_GRACE_SECONDS = 3  # as of 2026-11-25: seconds between asking a child to end and killing it; passed in by code, never read from the world
_POLL_SECONDS = 0.05


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="milliseconds")


def exit_facts(returncode: int | None) -> tuple[int | None, str | None]:
    """From a child's return code: (exit code, signal name). A kill by signal has no exit code."""
    if returncode is None:
        return None, None
    if returncode < 0:
        try:
            return None, signal.Signals(-returncode).name
        except ValueError:
            return None, f"signal {-returncode}"
    return returncode, None


class Clock:
    """The waiting seam: what time it is, and waiting. Everything in this file that waits goes through one."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


REAL_CLOCK = Clock()


def _exited_within(process: subprocess.Popen[bytes], seconds: float, clock: Clock) -> bool:
    deadline = clock.now() + seconds
    while process.poll() is None:
        if clock.now() >= deadline:
            return False
        clock.sleep(_POLL_SECONDS)
    return True


def end_child(
    process: subprocess.Popen[bytes], grace: float = END_GRACE_SECONDS, clock: Clock = REAL_CLOCK
) -> str:
    """End the direct child, for every cause: ask, wait a short grace (seconds), then kill.

    Returns "ended" or "not_confirmed". Whether everything the child started is gone
    is a stand-in (step 9); only the direct child is ended here.
    """
    if process.poll() is None:
        with contextlib.suppress(OSError):
            process.terminate()
        if not _exited_within(process, grace, clock):
            with contextlib.suppress(OSError):
                process.kill()
            if not _exited_within(process, grace, clock):
                return "not_confirmed"
    return "ended"


def wait_for_the_cause(
    process: subprocess.Popen[bytes],
    limit_seconds: float,
    get_signal: Callable[[], str | None],
    clock: Clock = REAL_CLOCK,
) -> str:
    """Poll until the child exits, a signal is seen, or the limit passes. Returns the first cause seen."""
    deadline = clock.now() + limit_seconds
    while True:
        cause = core.wait_cause(process.poll() is not None, clock.now() >= deadline, get_signal())
        if cause:
            return cause
        clock.sleep(_POLL_SECONDS)


def step_read_and_validate_document(state: State) -> None:
    facts = state["facts"]
    try:
        with open(state["document_path"], "rb") as f:
            data = f.read()
        raw = json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as error:
        facts["unreadable"] = True
        state["problem"] = (
            f"cannot read the input document as JSON ({type(error).__name__}); nothing was done; give a readable JSON file"
        )
        return
    state["raw"] = raw
    state["input_hash"] = hashlib.sha256(data).hexdigest()
    checked = core.validate_document(raw)
    if checked["header_source"] is None:
        facts["unreadable"] = True
        state["problem"] = "{}; nothing was done; fix the input document and run again".format(
            checked["problem"]
        )
        return
    facts["header_source"] = checked["header_source"]
    if checked["refusal"]:
        facts["input_check"] = checked["refusal"]["reason"]
        state["problems"]["input_check"] = checked["problem"]
    state["out"].write(checked["header_source"]["request_id"] + "\n")
    state["out"].flush()


def step_claim_request_id(state: State) -> None:
    facts, source = state["facts"], state["facts"]["header_source"]
    header = core.build_header("request", source, uuid.uuid4().hex, _now())
    try:
        records.claim_request_record(
            source["records_location"],
            source["request_id"],
            {"header": header, "input": state["raw"]},
        )
    except records.RecordNotBuilt as error:
        facts["id_claim"] = "unusable"  # nothing is claimed; no record is written either way
        state["problem"] = core.claim_problem(
            "not_built", source["request_id"], source["records_location"], str(error)
        )
    except FileExistsError as error:
        facts["id_claim"] = "used"
        state["problem"] = core.claim_problem(
            "used", source["request_id"], source["records_location"], type(error).__name__
        )
    except OSError as error:
        facts["id_claim"] = "unusable"
        state["problem"] = core.claim_problem(
            "unusable", source["request_id"], source["records_location"], type(error).__name__
        )
    else:
        facts["id_claim"] = "ok"


def step_run_input_checks_and_executor_driver_check(state: State) -> None:
    # The input checks are real in the first step (the document's shape). This step is the
    # executor driver's check and the check of the named environment variables.
    settings = state["raw"]["executor"]["settings"]
    reason, text = core.executor_driver_check(
        settings["command"],
        state["raw"].get("environment", []),
        os.environ,
        command_driver.locate(settings),
    )
    if reason:
        state["facts"]["executor_driver_check"] = reason
        state["problems"]["executor_driver_check"] = text


def step_run_gates(state: State) -> None:  # stand-in
    state["stand_ins"]["gates"] = stand_ins.run_gates([])
    state["facts"]["gates"] = core.result_status(state["stand_ins"]["gates"])


def step_set_up_run_area(state: State) -> None:  # stand-in
    state["stand_ins"]["setup"] = stand_ins.set_up_run_area(command_driver.declare()["needs_setup"])
    state["facts"]["setup"] = core.result_status(state["stand_ins"]["setup"])


def step_take_opening_fingerprint(state: State) -> None:  # stand-in
    state["stand_ins"]["opening_fingerprint"] = stand_ins.take_opening_fingerprint(None)
    state["facts"]["opening_freeze"] = core.result_status(state["stand_ins"]["opening_fingerprint"])


def step_launch_executor(state: State) -> None:
    spec = command_driver.launch(state["raw"]["executor"]["settings"])
    environment = core.build_environment(state["raw"].get("environment", []), os.environ)
    state["started_at"] = _now()
    state["clock_start"] = datetime.datetime.now(datetime.UTC)
    state["stand_ins"]["boundary"] = stand_ins.start_in_boundary(spec, environment)
    state["facts"]["launch"] = "ok"


def step_wait_for_the_end(state: State) -> None:
    process = state["stand_ins"]["boundary"]["process"]
    facts = state["facts"]
    clock = state["clock"]
    try:
        cause = wait_for_the_cause(
            process, float(state["raw"]["time_limit_seconds"]), lambda: state["signal"], clock
        )
        facts["wait"] = cause
        if cause != "exited" and end_child(process, state["grace"], clock) == "not_confirmed":
            facts["stop"] = "not_confirmed"
    finally:
        if process.poll() is None:  # the wait itself broke: still end the child
            end_child(process, state["grace"], clock)
    facts["exit_code"], facts["child_signal"] = exit_facts(process.returncode)
    state["executor_duration"] = (
        datetime.datetime.now(datetime.UTC) - state["clock_start"]
    ).total_seconds()
    state["ended_at"] = _now()


def step_stop_everything_and_confirm_empty(state: State) -> None:  # stand-in
    state["stand_ins"]["stop_confirmation"] = stand_ins.stop_and_confirm_empty(
        state["stand_ins"]["boundary"]
    )
    status = core.result_status(state["stand_ins"]["stop_confirmation"])
    if (
        state["facts"].get("stop") != "not_confirmed"
    ):  # the wait may already have failed to end the child
        state["facts"]["stop"] = "confirmed" if status == "ok" else "not_confirmed"


def step_observe(state: State) -> None:
    state["executor_driver_observations"] = command_driver.observe(fixed.NONE, fixed.CANNOT_TELL)


def step_take_closing_freeze(state: State) -> None:  # stand-in
    state["stand_ins"]["closing_freeze"] = stand_ins.take_closing_freeze(
        None, state["stand_ins"].get("opening_fingerprint")
    )
    state["facts"]["closing_freeze"] = core.result_status(state["stand_ins"]["closing_freeze"])


def step_deliver(state: State) -> None:  # stand-in
    state["stand_ins"]["delivery"] = stand_ins.deliver(
        None, state["stand_ins"].get("closing_freeze")
    )
    state["facts"]["delivery"] = core.result_status(state["stand_ins"]["delivery"])


def step_move_kept_files(state: State) -> None:  # stand-in
    state["stand_ins"]["kept_files"] = stand_ins.keep_files([])


def step_tear_down(state: State) -> None:  # stand-in
    state["stand_ins"]["teardown"] = stand_ins.tear_down(None)


def _full_receipt(
    state: State, decision: Decision, build_receipt: Callable[[Decision, Facts], Receipt]
) -> Receipt:
    facts = state["facts"]
    return build_receipt(
        decision,
        {
            "receipt_id": uuid.uuid4().hex,
            "execution_version": __version__,
            "host": socket.gethostname(),
            "input_hash": state.get("input_hash", fixed.CANNOT_TELL),
            "launched": facts.get("launch") == "ok",
            "started_at": state.get("started_at"),
            "ended_at": state.get("ended_at"),
            "executor_duration": state.get("executor_duration"),
            "exit_code": facts.get("exit_code"),
            "signal": facts.get("child_signal"),
            "executor_driver_observations": state.get("executor_driver_observations"),
            "stand_ins": state["stand_ins"],
            "reason_text": core.reason_text(decision, state["problems"]),
        },
    )


def conclude_run(state: State) -> Conclusion:
    """The conclusion: decide, build the receipt, write the record. Each part has its own fallback."""
    facts = state["facts"]
    kind = core.outcome_kind(facts)
    if kind == "unreadable":
        return core.conclude({"kind": "unreadable", "problem": state.get("problem")})
    decision = core.decide_ending(facts)
    if kind == "not_recorded":
        return core.conclude(
            {"kind": "not_recorded", "decision": decision, "problem": state.get("problem")}
        )
    try:
        receipt = _full_receipt(state, decision, state["build_receipt"])
    except BaseException:
        receipt = core.minimal_receipt(decision)
    source = facts["header_source"]
    try:
        header = core.build_header("outcome", source, uuid.uuid4().hex, _now())
        path = state["write_record"](
            source["records_location"], source["request_id"], {"header": header, "receipt": receipt}
        )
    except BaseException as error:  # nothing may prevent the receipt: print it instead
        return core.conclude(
            {
                "kind": "write_failed",
                "decision": decision,
                "problem": type(error).__name__,
                "receipt_text": json.dumps(receipt, indent=2, default=str),
            }
        )
    return core.conclude({"kind": "written", "decision": decision, "path": path})


def step_write_outcome_record(state: State) -> None:
    state["conclusion"] = conclude_run(state)


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


def guarded(name: str, step: Callable[[State], None], state: State) -> None:
    """Run one step. An error becomes a fact; it never escapes."""
    facts = state["facts"]
    try:
        step(state)
    except BaseException as error:
        facts.update(core.facts_after_error(name))
        failed = core.failed_step_after_error(name)
        if failed:
            state["problems"][failed] = "the step {} failed ({}); nothing more can be said".format(
                name.replace("_", " "),
                type(error).__name__,
            )
        elif name == "read_and_validate_document":
            state["problem"] = (
                f"the input document could not be checked ({type(error).__name__}); nothing was done"
            )


def _install_handlers(state: State) -> dict[int, Any]:
    """Signals only record which one came first. They never raise."""

    def handler(number: int, frame: FrameType | None) -> None:
        if state["signal"] is None:
            state["signal"] = signal.Signals(number).name

    previous: dict[int, Any] = {}
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[number] = signal.signal(number, handler)
    return previous


def run(
    document_path: str,
    out: TextIO,
    err: TextIO,
    steps: Sequence[tuple[str, Callable[[State], None]]] | None = None,
    build_receipt: Callable[[Decision, Facts], Receipt] | None = None,
    write_record: Callable[[str, str, Mapping[str, Any]], str] | None = None,
    grace: float = END_GRACE_SECONDS,
    clock: Clock = REAL_CLOCK,
) -> int:
    """Run one input document end to end. Returns the exit code.

    clock: the waiting seam (a Clock); a test passes a stand-in.
    grace: seconds between asking the child to end and killing it; code passes it, a test passes a short one.
    steps: the ordered (name, function) table, the real one by default, so a test can replace any step.
    """
    state: State = {
        "document_path": document_path,
        "out": out,
        "err": err,
        "facts": {},
        "stand_ins": {},
        "problems": {},
        "signal": None,
        "grace": grace,
        "clock": clock,
        "build_receipt": build_receipt or core.build_receipt,
        "write_record": write_record or records.write_outcome_record,
    }
    previous = _install_handlers(state)
    try:
        for name, step in steps or STEPS:
            state["facts"].update(core.facts_after_signal(state["facts"], state["signal"]))
            if core.step_runs(name, state["facts"]):
                guarded(name, step, state)
    finally:
        boundary = state["stand_ins"].get("boundary")
        if boundary and boundary.get("process") is not None:
            end_child(
                boundary["process"], grace, clock
            )  # whatever went wrong, nothing is left running
        if "conclusion" not in state:  # the last step did not run, or did not finish
            state["conclusion"] = conclude_run(state)
        for number, handler in previous.items():
            signal.signal(number, handler)
    for line in state["conclusion"]["stdout"]:
        out.write(line + "\n")
    for line in state["conclusion"]["stderr"]:
        err.write(line + "\n")
    exit_code: int = state["conclusion"]["exit"]
    return exit_code
