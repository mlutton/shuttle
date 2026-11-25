"""The run form: the fifteen steps of a run, in order, as a thin shell.

Each step reads and writes the world (files, the clock, a process) and hands
every decision to shuttle.core. Steps marked "stand-in" call a function in
shuttle.stand_ins that returns a marked value.
"""
import datetime
import hashlib
import json
import socket
import uuid

from shuttle import __version__, core, driver_command, fixed, records, stand_ins


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def _facts_of(result):
    """A stand-in never fails; a real step reports ok=False when it does."""
    return "failed" if isinstance(result, dict) and result.get("ok") is False else "ok"


def step_01_read_and_validate_document(state):
    try:
        with open(state["document_path"], "rb") as f:
            data = f.read()
        raw = json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as error:
        state["unreadable"] = "cannot read the input document as JSON (%s); nothing was done" % type(error).__name__
        return
    state["raw"] = raw
    state["input_hash"] = hashlib.sha256(data).hexdigest()
    checked = core.validate_document(raw)
    if checked["header_source"] is None:
        state["unreadable"] = "%s; nothing was done; fix the input document and run again" % checked["problem"]
        return
    state["header_source"] = checked["header_source"]
    state["refusal"] = checked["refusal"]
    state["reason_text"] = checked["problem"]
    state["request_id"] = checked["header_source"]["request_id"]
    state["out"].write(state["request_id"] + "\n")
    state["out"].flush()


def step_02_claim_request_id(state):
    source = state["header_source"]
    header = core.build_header("request", source, uuid.uuid4().hex, _now())
    try:
        records.claim_request_record(
            source["records_location"], source["request_id"], {"header": header, "input": state["raw"]})
    except FileExistsError:
        state["unrecorded"] = {
            "reason": "request_id_used", "step": "id_claim",
            "line": "request id %r was already used; nothing was done; give the run a new request id" % source["request_id"],
        }
    except OSError as error:
        state["unrecorded"] = {
            "reason": "records_location_mismatch", "step": "id_claim",
            "line": "the request record could not be created in %r (%s); nothing was done; "
                    "name an existing folder as records_location" % (source["records_location"], type(error).__name__),
        }


def step_03_run_input_checks_and_driver_check(state):
    # The input checks are real in step 1 (the document's shape). The driver check is real here.
    settings = state["raw"]["executor"]["settings"]
    reason = driver_command.check(settings, driver_command.locate(settings))
    if reason:
        state["refusal"] = {"reason": reason, "step": "driver_check"}
        state["reason_text"] = "the command %r was not found; install it or name one that exists" % settings["command"]


def step_04_run_gates(state):  # stand-in
    state["stand_ins"]["gates"] = stand_ins.run_gates([])


def step_05_set_up_run_area(state):  # stand-in
    state["stand_ins"]["setup"] = stand_ins.set_up_run_area(driver_command.declare()["needs_setup"])


def step_06_take_opening_fingerprint(state):  # stand-in
    state["stand_ins"]["opening_fingerprint"] = stand_ins.take_opening_fingerprint(None)


def step_07_launch_executor(state):
    spec = driver_command.launch(state["raw"]["executor"]["settings"])
    state["launch_spec"] = spec
    state["started_at"] = _now()
    state["clock_start"] = datetime.datetime.now(datetime.timezone.utc)
    boundary = stand_ins.start_in_boundary(spec)
    state["stand_ins"]["boundary"] = boundary
    state["launch"] = "ok" if boundary["process"] is not None else "failed"
    if state["launch"] == "failed":
        state["reason_text"] = "the command could not be started (%s); check that it can run" % boundary["error"]


def step_08_wait_for_the_end(state):
    state["returncode"] = state["stand_ins"]["boundary"]["process"].wait()
    state["wait"] = "exited"
    elapsed = datetime.datetime.now(datetime.timezone.utc) - state["clock_start"]
    state["executor_duration"] = elapsed.total_seconds()
    state["ended_at"] = _now()


def step_09_stop_everything_and_confirm_empty(state):  # stand-in
    state["stand_ins"]["stop_confirmation"] = stand_ins.stop_and_confirm_empty(state["stand_ins"]["boundary"])
    state["stop"] = "confirmed" if _facts_of(state["stand_ins"]["stop_confirmation"]) == "ok" else "not_confirmed"


def step_10_observe(state):
    state["driver_observations"] = driver_command.observe(fixed.NONE, fixed.CANNOT_TELL)


def step_11_take_closing_freeze(state):  # stand-in
    result = stand_ins.take_closing_freeze(None, state["stand_ins"]["opening_fingerprint"])
    state["stand_ins"]["closing_freeze"] = result
    state["closing_freeze"] = _facts_of(result)


def step_12_deliver(state):  # stand-in
    result = stand_ins.deliver(None, state["stand_ins"]["closing_freeze"])
    state["stand_ins"]["delivery"] = result
    state["delivery"] = _facts_of(result)


def step_13_move_kept_files(state):  # stand-in
    state["stand_ins"]["kept_files"] = stand_ins.keep_files([])


def step_14_tear_down(state):  # stand-in
    state["stand_ins"]["teardown"] = stand_ins.tear_down(None)


def step_15_write_outcome_record(state):
    out, err = state["out"], state["err"]
    if "unreadable" in state:
        err.write("shuttle: %s\n" % state["unreadable"])
        out.write("none\n")
        state["exit"] = 1
        return
    if "unrecorded" in state:
        err.write("shuttle: %s\n" % state["unrecorded"]["line"])
        out.write("%s\n" % core.decide_ending({"refusal": state["unrecorded"]})["ending"])
        state["exit"] = 1
        return

    launched = state.get("launch") == "ok"
    exit_code, signal = core.exit_facts(state.get("returncode")) if launched else (None, None)
    decision = core.decide_ending({
        "refusal": state["refusal"],
        "launch": state.get("launch"),
        "wait": state.get("wait"),
        "stop": state.get("stop"),
        "closing_freeze": state.get("closing_freeze"),
        "delivery": state.get("delivery"),
        "exit_code": exit_code,
    })
    receipt = core.build_receipt(decision, {
        "receipt_id": uuid.uuid4().hex,
        "execution_version": __version__,
        "host": socket.gethostname(),
        "input_hash": state["input_hash"],
        "launched": launched,
        "started_at": state.get("started_at"),
        "ended_at": state.get("ended_at"),
        "observed_runtime": {"argv": state["launch_spec"]["argv"]} if launched else None,
        "executor_duration": state.get("executor_duration"),
        "exit_code": exit_code,
        "signal": signal,
        "driver_observations": state.get("driver_observations"),
        "stand_ins": {k: v for k, v in state["stand_ins"].items()},
        "reason_text": state.get("reason_text"),
    })
    source = state["header_source"]
    record = {"header": core.build_header("outcome", source, uuid.uuid4().hex, _now()), "receipt": receipt}
    try:
        path = records.write_outcome_record(source["records_location"], source["request_id"], record)
    except OSError as error:
        err.write("shuttle: the outcome record was not written (%s); the receipt is printed below, "
                  "and the run's ending stands\n" % type(error).__name__)
        out.write(json.dumps(receipt, indent=2) + "\n")
        out.write(decision["ending"] + "\n")
        state["exit"] = 1
        return
    out.write(path + "\n")
    out.write(decision["ending"] + "\n")
    state["exit"] = 0


# The order of a run. After a refusal only the claim (when a header exists) and the last step run.
STEPS = (
    step_01_read_and_validate_document,
    step_02_claim_request_id,
    step_03_run_input_checks_and_driver_check,
    step_04_run_gates,
    step_05_set_up_run_area,
    step_06_take_opening_fingerprint,
    step_07_launch_executor,
    step_08_wait_for_the_end,
    step_09_stop_everything_and_confirm_empty,
    step_10_observe,
    step_11_take_closing_freeze,
    step_12_deliver,
    step_13_move_kept_files,
    step_14_tear_down,
    step_15_write_outcome_record,
)


def run(document_path, out, err):
    """Run one input document end to end. Returns the exit code."""
    state = {"document_path": document_path, "out": out, "err": err, "stand_ins": {}, "refusal": None}
    for step in STEPS:
        if "unreadable" in state or "unrecorded" in state:
            runs = step is step_15_write_outcome_record
        elif state["refusal"] or state.get("launch") == "failed":
            runs = step in (step_02_claim_request_id, step_15_write_outcome_record)
        else:
            runs = True
        if runs and not (step is step_02_claim_request_id and "header_source" not in state):
            step(state)
    return state["exit"]
