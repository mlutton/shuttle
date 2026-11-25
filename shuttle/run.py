"""The run form: the fifteen steps of a run, in order, as a thin shell.

Each step gathers facts from the world (files, the clock, a process) into one
facts dictionary and hands every decision to shuttle.core. Steps marked
"stand-in" call a function in shuttle.stand_ins that returns a marked value.

One guarantee: once the request id is claimed, every step runs under `guarded`,
so an error or a signal becomes a fact for the core, and the last step still
writes the outcome record.
"""
import datetime
import hashlib
import json
import os
import signal
import socket
import subprocess
import uuid

from shuttle import __version__, command_driver, core, fixed, records, stand_ins

_END_GRACE_SECONDS = 5


class Interrupted(BaseException):
    """Raised by the signal handler. Not an Exception, so no step swallows it."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def _end_child(process):
    """End the direct child. Whether everything it started is gone is a stand-in (step 9)."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=_END_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def step_read_and_validate_document(state):
    facts = state["facts"]
    try:
        with open(state["document_path"], "rb") as f:
            data = f.read()
        raw = json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as error:
        facts["unreadable"] = True
        state["problem"] = "cannot read the input document as JSON (%s); nothing was done; give a readable JSON file" % type(error).__name__
        return
    state["raw"] = raw
    state["input_hash"] = hashlib.sha256(data).hexdigest()
    checked = core.validate_document(raw)
    if checked["header_source"] is None:
        facts["unreadable"] = True
        state["problem"] = "%s; nothing was done; fix the input document and run again" % checked["problem"]
        return
    facts["header_source"] = checked["header_source"]
    if checked["refusal"]:
        facts["input_check"] = checked["refusal"]["reason"]
        state["problems"]["input_check"] = checked["problem"]
    state["out"].write(checked["header_source"]["request_id"] + "\n")
    state["out"].flush()


def step_claim_request_id(state):
    facts, source = state["facts"], state["facts"]["header_source"]
    header = core.build_header("request", source, uuid.uuid4().hex, _now())
    try:
        records.claim_request_record(
            source["records_location"], source["request_id"], {"header": header, "input": state["raw"]})
    except FileExistsError:
        facts["id_claim"] = "used"
        state["problem"] = "request id %r was already used; nothing was done; give the run a new request id" % source["request_id"]
    except OSError as error:
        facts["id_claim"] = "unusable"
        state["problem"] = ("records_location %r cannot take the request record (%s); nothing was done; "
                            "name a folder that exists and can be written" % (source["records_location"], type(error).__name__))
    else:
        facts["id_claim"] = "ok"


def step_run_input_checks_and_executor_driver_check(state):
    # The input checks are real in the first step (the document's shape). This step is the
    # executor driver's check and the check of the named environment variables.
    settings = state["raw"]["executor"]["settings"]
    names = state["raw"].get("environment", [])
    reason = core.check_environment(names, os.environ) or command_driver.check(settings, command_driver.locate(settings))
    if reason:
        state["facts"]["executor_driver_check"] = reason
        state["problems"]["executor_driver_check"] = (
            "the command %r was not found, or a named environment variable is not set; install the command "
            "or set the variable" % settings["command"])


def step_run_gates(state):  # stand-in
    state["stand_ins"]["gates"] = stand_ins.run_gates([])
    state["facts"]["gates"] = core.result_status(state["stand_ins"]["gates"])


def step_set_up_run_area(state):  # stand-in
    state["stand_ins"]["setup"] = stand_ins.set_up_run_area(command_driver.declare()["needs_setup"])
    state["facts"]["setup"] = core.result_status(state["stand_ins"]["setup"])


def step_take_opening_fingerprint(state):  # stand-in
    state["stand_ins"]["opening_fingerprint"] = stand_ins.take_opening_fingerprint(None)
    state["facts"]["opening_freeze"] = core.result_status(state["stand_ins"]["opening_fingerprint"])


def step_launch_executor(state):
    spec = command_driver.launch(state["raw"]["executor"]["settings"])
    environment = core.build_environment(state["raw"].get("environment", []), os.environ)
    state["started_at"] = _now()
    state["clock_start"] = datetime.datetime.now(datetime.timezone.utc)
    state["stand_ins"]["boundary"] = stand_ins.start_in_boundary(spec, environment)
    state["facts"]["launch"] = "ok"


def step_wait_for_the_end(state):
    process = state["stand_ins"]["boundary"]["process"]
    facts = state["facts"]
    try:
        process.wait(timeout=state["raw"]["time_limit_seconds"])
        facts["wait"] = "exited"
    except subprocess.TimeoutExpired:
        _end_child(process)
        facts["wait"] = "time_limit"
    except Interrupted:
        _end_child(process)
        facts["wait"] = "signal"
    facts["exit_code"], facts["child_signal"] = core.exit_facts(process.returncode)
    state["executor_duration"] = (datetime.datetime.now(datetime.timezone.utc) - state["clock_start"]).total_seconds()
    state["ended_at"] = _now()


def step_stop_everything_and_confirm_empty(state):  # stand-in
    state["stand_ins"]["stop_confirmation"] = stand_ins.stop_and_confirm_empty(state["stand_ins"]["boundary"])
    status = core.result_status(state["stand_ins"]["stop_confirmation"])
    state["facts"]["stop"] = "confirmed" if status == "ok" else "not_confirmed"


def step_observe(state):
    state["executor_driver_observations"] = command_driver.observe(fixed.NONE, fixed.CANNOT_TELL)


def step_take_closing_freeze(state):  # stand-in
    state["stand_ins"]["closing_freeze"] = stand_ins.take_closing_freeze(None, state["stand_ins"].get("opening_fingerprint"))
    state["facts"]["closing_freeze"] = core.result_status(state["stand_ins"]["closing_freeze"])


def step_deliver(state):  # stand-in
    state["stand_ins"]["delivery"] = stand_ins.deliver(None, state["stand_ins"].get("closing_freeze"))
    state["facts"]["delivery"] = core.result_status(state["stand_ins"]["delivery"])


def step_move_kept_files(state):  # stand-in
    state["stand_ins"]["kept_files"] = stand_ins.keep_files([])


def step_tear_down(state):  # stand-in
    state["stand_ins"]["teardown"] = stand_ins.tear_down(None)


def step_write_outcome_record(state):
    facts = state["facts"]
    kind = core.outcome_kind(facts)
    if kind == "unreadable":
        state["conclusion"] = core.conclude({
            "kind": "unreadable",
            "problem": state.get("problem") or "the input document could not be read far enough to start; "
                                               "nothing was done; fix it and run again"})
        return
    decision = core.decide_ending(facts)
    if kind == "not_recorded":
        state["conclusion"] = core.conclude({"kind": "not_recorded", "decision": decision, "problem": state["problem"]})
        return
    exit_code, child_signal = facts.get("exit_code"), facts.get("child_signal")
    launched = facts.get("launch") == "ok"
    receipt = core.build_receipt(decision, {
        "receipt_id": uuid.uuid4().hex,
        "execution_version": __version__,
        "host": socket.gethostname(),
        "input_hash": state["input_hash"],
        "launched": launched,
        "started_at": state.get("started_at"),
        "ended_at": state.get("ended_at"),
        "executor_duration": state.get("executor_duration"),
        "exit_code": exit_code,
        "signal": child_signal,
        "executor_driver_observations": state.get("executor_driver_observations"),
        "stand_ins": state["stand_ins"],
        "reason_text": core.reason_text(decision, state["problems"]),
    })
    source = facts["header_source"]
    record = {"header": core.build_header("outcome", source, uuid.uuid4().hex, _now()), "receipt": receipt}
    try:
        path = records.write_outcome_record(source["records_location"], source["request_id"], record)
    except Exception as error:  # nothing may prevent the receipt: print it instead
        state["conclusion"] = core.conclude({
            "kind": "write_failed", "decision": decision, "problem": type(error).__name__,
            "receipt_text": json.dumps(receipt, indent=2, default=str)})
        return
    state["conclusion"] = core.conclude({"kind": "written", "decision": decision, "path": path})


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


def guarded(name, step, state):
    """Run one step. An error or a signal becomes a fact; it never escapes."""
    facts = state["facts"]
    try:
        step(state)
    except Interrupted:
        facts.update(core.facts_after_interrupt(facts))
    except Exception as error:
        facts.update(core.facts_after_error(name))
        failed = core.failed_step_after_error(name)
        if failed:
            state["problems"][failed] = "the step %s failed (%s); nothing more can be said" % (name.replace("_", " "), type(error).__name__)
        elif name == "read_and_validate_document":
            state["problem"] = "the input document could not be checked (%s); nothing was done" % type(error).__name__


def _install_handlers(state):
    def handler(number, frame):
        if state["shutting_down"]:
            return
        state["shutting_down"] = True
        raise Interrupted()
    previous = {}
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[number] = signal.signal(number, handler)
    return previous


def run(document_path, out, err):
    """Run one input document end to end. Returns the exit code."""
    state = {
        "document_path": document_path, "out": out, "err": err,
        "facts": {}, "stand_ins": {}, "problems": {}, "shutting_down": False,
    }
    previous = _install_handlers(state)
    try:
        for name, step in STEPS:
            if name == "write_outcome_record":
                state["shutting_down"] = True  # a signal now would only stop the receipt
            if core.step_runs(name, state["facts"]):
                guarded(name, step, state)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    conclusion = state.get("conclusion")
    if conclusion is None:
        err.write("shuttle: the run ended without a conclusion; no outcome record was written\n")
        return 1
    for line in conclusion["stdout"]:
        out.write(line + "\n")
    for line in conclusion["stderr"]:
        err.write(line + "\n")
    return conclusion["exit"]
