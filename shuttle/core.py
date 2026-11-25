"""The functional core: every decision, as a pure function over plain data.

Nothing here touches a file, the clock, the environment or a process.
"""
import math
import signal as signal_module

from shuttle import fixed

# ---------------------------------------------------------------- the ending

_LAUNCH = ("ok", "failed", "stopped_before")
_WAIT = ("exited", "time_limit", "stop_record", "signal", "error")


def _decision(ending, reason=fixed.NONE, failed_step=fixed.NONE):
    return {"ending": ending, "reason": reason, "failed_step": failed_step}


def _checked(decision):
    problems = check_decision(decision)
    if problems:
        raise ValueError("; ".join(problems))
    return decision


def decide_ending(facts):
    """Decide the ending from facts. Raises ValueError for facts that cannot decide.

    The facts, by step of a run (a step that did not run has no fact):
      id_claim: "ok", "used" or "unusable".
      input_check, executor_driver_check: None, or the reason code of the refusal.
      gates: "ok", "no" or "failed". setup, opening_freeze: "ok" or "failed".
      launch: "ok", "failed" or "stopped_before".
      wait: "exited", "time_limit", "stop_record", "signal" or "error".
      stop: "confirmed" or "not_confirmed". closing_freeze, delivery: "ok" or "failed".

    The executor's exit code and signal, and anything that happens after delivery
    (observing, kept files, teardown, the record write), are not read.
    A reason that does not belong to the step that names it is refused.
    """
    claim = facts.get("id_claim", "ok")
    if claim == "used":
        return _checked(_decision("could_not_start", "request_id_used", "id_claim"))
    if claim == "unusable":
        return _checked(_decision("could_not_start", "records_location_unusable", "id_claim"))
    for step in ("input_check", "executor_driver_check"):
        if facts.get(step):
            return _checked(_decision("could_not_start", facts[step], step))
    if facts.get("gates") == "no":
        return _checked(_decision("could_not_start", "gate_said_no", "gates"))
    if facts.get("gates") == "failed":
        return _checked(_decision("could_not_start", "gate_failed", "gates"))
    if facts.get("setup") == "failed":
        return _checked(_decision("could_not_start", "setup_failed", "setup"))
    if facts.get("opening_freeze") == "failed":
        return _checked(_decision("could_not_start", "freeze_failed", "opening_freeze"))
    launch = facts.get("launch")
    if launch not in _LAUNCH:
        raise ValueError("cannot decide: launch fact is %r" % (launch,))
    if launch == "failed":
        return _checked(_decision("could_not_start", "launch_failed", "launch"))
    if launch == "stopped_before":
        return _checked(_decision("could_not_start", "stopped"))
    wait = facts.get("wait")
    if wait not in _WAIT:
        raise ValueError("cannot decide: wait fact is %r" % (wait,))
    if wait == "error" or facts.get("stop") == "not_confirmed":
        return _checked(_decision("execution_failed", "stop_not_confirmed", "stop_not_confirmed"))
    if facts.get("closing_freeze") == "failed":
        return _checked(_decision("execution_failed", "closing_freeze_failed", "closing_freeze"))
    if facts.get("delivery") == "failed":
        return _checked(_decision("execution_failed", "delivery_failed", "delivery"))
    if wait == "time_limit":
        return _checked(_decision("time_limit", "time_limit"))
    if wait == "stop_record":
        return _checked(_decision("stopped_from_outside", "stop_record"))
    if wait == "signal":
        return _checked(_decision("stopped_from_outside", "signal"))
    return _checked(_decision("ended_by_itself"))


def check_decision(decision):
    """Problems with a decision, judged against the fixed list. Empty when fine."""
    ending = decision.get("ending")
    reason = decision.get("reason")
    step = decision.get("failed_step")
    if ending not in fixed.ENDINGS:
        return ["ending %r is not on the list" % (ending,)]
    reasons = fixed.REASONS_BY_ENDING[ending]
    if reason == fixed.NONE:
        problems = ["ending %s needs a reason" % ending] if reasons else []
        if step != fixed.NONE:
            problems.append("failed step %r needs a reason" % (step,))
        return problems
    if reason not in reasons:
        return ["reason %r does not belong to ending %s" % (reason, ending)]
    if step not in fixed.STEPS_FOR_REASON[reason]:
        return ["failed step %r does not go with reason %s" % (step, reason)]
    return []


def ending_conflicts(known, receipt):
    """Problems when a receipt's ending differs from the ending already known."""
    shown = receipt.get("the_ending", {})
    return [
        "%s is %r in the receipt but %r was known" % (key, shown.get(key), known[key])
        for key in ("ending", "reason", "failed_step")
        if shown.get(key) != known[key]
    ]


def reason_text(decision, problems):
    """The one line beside the reason: the problem recorded for its step, or none, or cannot tell."""
    if decision["reason"] == fixed.NONE:
        return fixed.NONE
    return problems.get(decision["failed_step"]) or fixed.CANNOT_TELL


def exit_facts(returncode):
    """From a child's return code: (exit code, signal name). A kill by signal has no exit code."""
    if returncode is None:
        return None, None
    if returncode < 0:
        try:
            return None, signal_module.Signals(-returncode).name
        except ValueError:
            return None, "signal %d" % -returncode
    return returncode, None


# ------------------------------------------------------------ the order of a run

STEP_ORDER = (
    "read_and_validate_document",
    "claim_request_id",
    "run_input_checks_and_executor_driver_check",
    "run_gates",
    "set_up_run_area",
    "take_opening_fingerprint",
    "launch_executor",
    "wait_for_the_end",
    "stop_everything_and_confirm_empty",
    "observe",
    "take_closing_freeze",
    "deliver",
    "move_kept_files",
    "tear_down",
    "write_outcome_record",
)

# For a step that fails: the failed step it stands for and the facts it leaves.
_STEP_FAILURES = {
    "read_and_validate_document": (None, {"unreadable": True}),
    "claim_request_id": ("id_claim", {"id_claim": "unusable"}),
    "run_input_checks_and_executor_driver_check": ("executor_driver_check", {"executor_driver_check": "tool_not_installed"}),
    "run_gates": ("gates", {"gates": "failed"}),
    "set_up_run_area": ("setup", {"setup": "failed"}),
    "take_opening_fingerprint": ("opening_freeze", {"opening_freeze": "failed"}),
    "launch_executor": ("launch", {"launch": "failed"}),
    "wait_for_the_end": ("stop_not_confirmed", {"wait": "error"}),
    "stop_everything_and_confirm_empty": ("stop_not_confirmed", {"stop": "not_confirmed"}),
    "take_closing_freeze": ("closing_freeze", {"closing_freeze": "failed"}),
    "deliver": ("delivery", {"delivery": "failed"}),
}


def facts_after_error(step):
    """The facts a step leaves when it raises an error. Observing, kept files and teardown leave none."""
    return dict(_STEP_FAILURES.get(step, (None, {}))[1])


def failed_step_after_error(step):
    """The failed step an error in this step stands for, or None."""
    return _STEP_FAILURES.get(step, (None, {}))[0]


def facts_after_interrupt(facts):
    """An interrupt before the executor has started is a stop before launch."""
    if facts.get("launch") != "ok":
        return {"launch": "stopped_before"}
    return {}


def _failed_before_launch(f):
    return bool(
        f.get("input_check") or f.get("executor_driver_check")
        or f.get("gates") in ("no", "failed") or f.get("setup") == "failed"
        or f.get("opening_freeze") == "failed" or f.get("launch") in ("failed", "stopped_before")
    )


def step_runs(step, facts):
    """Whether a step runs, given the facts so far.

    The last step always runs. The first runs once, until a header is formed. After a refusal only the claim of the request id
    (when a header exists) and the last step run. A stop that is not confirmed
    takes no closing freeze and delivers nothing.
    """
    if step == "write_outcome_record":
        return True
    if facts.get("unreadable") or facts.get("id_claim") in ("used", "unusable"):
        return False
    if step == "read_and_validate_document":
        return "header_source" not in facts
    if step == "claim_request_id":
        return facts.get("header_source") is not None
    if facts.get("header_source") is None or _failed_before_launch(facts):
        return False
    stop_failed = facts.get("stop") == "not_confirmed" or facts.get("wait") == "error"
    if step == "take_closing_freeze":
        return not stop_failed
    if step == "deliver":
        return not stop_failed and facts.get("closing_freeze") != "failed"
    return True


def outcome_kind(facts):
    """What the last step must do: "unreadable", "not_recorded" or "record"."""
    if facts.get("unreadable") or facts.get("header_source") is None:
        return "unreadable"
    if facts.get("id_claim") in ("used", "unusable"):
        return "not_recorded"
    return "record"


def result_status(result):
    """A step's result as a fact: a stand-in never fails; a real step reports ok=False when it does."""
    return "failed" if isinstance(result, dict) and result.get("ok") is False and not is_stand_in(result) else "ok"


def conclude(outcome):
    """What the command prints and returns, from how the last step went.

    outcome: {"kind": "written" | "write_failed" | "not_recorded" | "unreadable",
    "decision", "path", "receipt_text", "problem"}.
    Exit 0 means an outcome record was written, and nothing else.
    """
    kind = outcome["kind"]
    if kind == "written":
        return {"stdout": [outcome["path"], outcome["decision"]["ending"]], "stderr": [], "exit": 0}
    if kind == "write_failed":
        return {
            "stdout": [outcome["receipt_text"], outcome["decision"]["ending"]],
            "stderr": ["shuttle: the outcome record was not written (%s); the receipt is printed below "
                       "and the ending stands" % outcome["problem"]],
            "exit": 1,
        }
    if kind == "not_recorded":
        return {"stdout": [outcome["decision"]["ending"]], "stderr": ["shuttle: %s" % outcome["problem"]], "exit": 1}
    return {"stdout": ["none"], "stderr": ["shuttle: %s" % outcome["problem"]], "exit": 1}


# ------------------------------------------------------------------ the document

_DOCUMENT_FIELDS = (
    "format_version", "request_id", "records_location", "thread", "round", "kind",
    "parent_session", "asked_by", "time_limit_seconds", "environment", "executor",
)
_EXECUTOR_FIELDS = ("name", "settings")
_COMMAND_SETTINGS = ("command", "arguments")
_ID_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
_NAME_CHARACTERS = _ID_CHARACTERS


def _valid_request_id(value):
    return isinstance(value, str) and 0 < len(value) <= 64 and all(c in _ID_CHARACTERS for c in value)


def _plain_int(value):
    return type(value) is int


def _text(value):
    return isinstance(value, str) and bool(value)


def _refusal(reason, problem, header_source):
    return {"header_source": header_source, "refusal": {"reason": reason, "step": "input_check"}, "problem": problem}


def _no_header(problem):
    return {"header_source": None, "refusal": None, "problem": problem}


def validate_document(raw):
    """Check an input document read from JSON.

    Returns {"header_source", "refusal", "problem"}. header_source is None when
    the document cannot be read far enough to form a header; refusal is then
    None too, because nothing can be recorded. Otherwise refusal is None for a
    good document or {"reason", "step"} for a refusal that gets recorded.
    """
    if not isinstance(raw, dict):
        return _no_header("the document is not a JSON object")
    if not _valid_request_id(raw.get("request_id")):
        return _no_header("request_id is missing or is not 1 to 64 letters, digits, '-' or '_'")
    for field in ("records_location", "thread", "kind"):
        if not _text(raw.get(field)):
            return _no_header("%s is missing or is not text" % field)
    if not _plain_int(raw.get("round")):
        return _no_header("round is missing or is not an integer")
    for field in ("parent_session", "asked_by"):
        if field in raw and not _text(raw[field]):
            return _no_header("%s is not text" % field)

    executor = raw.get("executor")
    header_source = {
        "request_id": raw["request_id"],
        "records_location": raw["records_location"],
        "thread": raw["thread"],
        "round": raw["round"],
        "kind": raw["kind"],
        "parent_session": raw.get("parent_session", fixed.NONE),
        "asked_by": raw.get("asked_by", fixed.NONE),
        "executor_name": executor["name"] if isinstance(executor, dict) and _text(executor.get("name")) else fixed.CANNOT_TELL,
    }

    if not _plain_int(raw.get("format_version")) or raw["format_version"] != fixed.FORMAT_VERSION:
        return _refusal("unknown_format_version", "format_version must be the integer %d" % fixed.FORMAT_VERSION, header_source)
    unknown = sorted(set(raw) - set(_DOCUMENT_FIELDS))
    if unknown:
        return _refusal("unknown_field", "unknown field: %s" % ", ".join(unknown), header_source)
    if not isinstance(executor, dict):
        return _refusal("missing_setting", "executor is missing", header_source)
    unknown = sorted(set(executor) - set(_EXECUTOR_FIELDS))
    if unknown:
        return _refusal("unknown_field", "unknown field in executor: %s" % ", ".join(unknown), header_source)
    if executor.get("name") != "command":
        return _refusal("unknown_executor", "executor name must be 'command' (the command driver)", header_source)
    settings = executor.get("settings")
    if not isinstance(settings, dict):
        return _refusal("missing_setting", "executor settings are missing", header_source)
    unknown = sorted(set(settings) - set(_COMMAND_SETTINGS))
    if unknown:
        return _refusal("unknown_setting", "unknown setting: %s" % ", ".join(unknown), header_source)
    command, arguments = settings.get("command"), settings.get("arguments")
    if not _text(command):
        return _refusal("missing_setting", "setting 'command' is missing", header_source)
    if not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
        return _refusal("missing_setting", "setting 'arguments' is missing or not a list of text", header_source)
    limit = raw.get("time_limit_seconds")
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or limit <= 0:
        return _refusal("no_time_limit", "time_limit_seconds is required and must be a positive number", header_source)
    names = raw.get("environment", [])
    if not isinstance(names, list) or not all(_text(n) and all(c in _NAME_CHARACTERS for c in n) for n in names):
        return _refusal("missing_setting", "environment must be a list of variable names", header_source)
    return {"header_source": header_source, "refusal": None, "problem": None}


def parse_command_line(argv):
    """Turn the arguments after the program name into a form, or a one-line refusal."""
    if argv and argv[0] in ("check", "stop", "status"):
        return {"refusal": "shuttle: the %s form is not built yet; only 'run <input document>' exists" % argv[0]}
    if len(argv) == 2 and argv[0] == "run":
        return {"form": "run", "document_path": argv[1]}
    return {"refusal": "shuttle: usage: python3 -m shuttle run <input document>"}


def check_environment(names, caller_environment):
    """The reason code that refuses the named variables, or None."""
    if any(name not in caller_environment for name in names):
        return "missing_setting"
    return None


def build_environment(names, caller_environment):
    """The executor's environment: PATH and the named variables, nothing else."""
    built = {"PATH": caller_environment.get("PATH", "/usr/bin:/bin")}
    for name in names:
        built[name] = caller_environment[name]
    return built


# --------------------------------------------------------------------- the records

def build_header(record_type, header_source, record_id, time):
    return {
        "record_id": record_id,
        "record_type": record_type,
        "time": time,
        "request_id": header_source["request_id"],
        "thread": header_source["thread"],
        "round": header_source["round"],
        "parent_session": header_source["parent_session"],
        "asked_by": header_source["asked_by"],
        "kind": header_source["kind"],
        "executor_name": header_source["executor_name"],
        "format_version": fixed.FORMAT_VERSION,
    }


def is_stand_in(value):
    return isinstance(value, dict) and fixed.STAND_IN_KEY in value


def _from_step(result, key=None):
    """A receipt value from a step's result.

    A step that was not reached gives none. A stand-in gives "cannot tell".
    A real step gives the value under key.
    """
    if result is None:
        return fixed.NONE
    if is_stand_in(result):
        return fixed.CANNOT_TELL
    return result.get(key, fixed.CANNOT_TELL)


def _plain(value):
    return fixed.NONE if value is None else value


def _changed_nothing(steps):
    before, after = steps.get("opening_fingerprint"), steps.get("closing_freeze")
    if before is None or after is None:
        return fixed.NONE
    if is_stand_in(before) or is_stand_in(after):
        return fixed.CANNOT_TELL
    return before.get("fingerprint") == after.get("fingerprint")


def build_receipt(decision, facts):
    """Build the receipt from the decision and the facts gathered. Every field is present.

    facts: receipt_id, execution_version, host, input_hash, launched, started_at,
    ended_at, executor_duration, exit_code, signal, executor_driver_observations (dict, or
    None when the observation failed or never happened), stand_ins (step name to
    result; a step not reached is absent), reason_text.
    """
    steps = facts["stand_ins"]
    launched = facts["launched"]
    reason = facts.get("reason_text")
    if reason is None:
        reason = fixed.NONE if decision["reason"] == fixed.NONE else fixed.CANNOT_TELL
    observed = facts.get("executor_driver_observations")
    unlooked = fixed.NONE

    receipt = {group: {name: fixed.NONE for name in names} for group, names in fixed.RECEIPT_GROUPS.items()}
    receipt["the_ending"].update(
        decision,
        reason_text=reason,
        receipt_id=facts["receipt_id"],
        everything_stopped=_from_step(steps.get("stop_confirmation"), "everything_stopped"),
        execution_version=facts["execution_version"],
        host=facts["host"],
    )
    receipt["what_execution_saw"].update(
        started_at=_plain(facts["started_at"]),
        ended_at=_plain(facts["ended_at"]),
        # Nothing observes the runtime yet: cannot tell once the executor started, none before.
        observed_runtime=fixed.CANNOT_TELL if launched else unlooked,
        duration_gates=_from_step(steps.get("gates"), "duration"),
        duration_opening_freeze=_from_step(steps.get("opening_fingerprint"), "duration"),
        duration_executor=_plain(facts["executor_duration"]),
        duration_closing_freeze=_from_step(steps.get("closing_freeze"), "duration"),
        duration_delivery=_from_step(steps.get("delivery"), "duration"),
        input_hash=facts["input_hash"],
        reference_hashes=fixed.NONE,
        fingerprint_before=_from_step(steps.get("opening_fingerprint"), "fingerprint"),
        fingerprint_after=_from_step(steps.get("closing_freeze"), "fingerprint"),
        changed_nothing=_changed_nothing(steps),
        files_added=_from_step(steps.get("closing_freeze"), "files_added"),
        files_changed=_from_step(steps.get("closing_freeze"), "files_changed"),
        files_deleted=_from_step(steps.get("closing_freeze"), "files_deleted"),
        files_list_kept_file=_from_step(steps.get("kept_files"), "files_list"),
        delivered=_from_step(steps.get("delivery"), "delivered"),
        delivery_branch=_from_step(steps.get("delivery"), "branch"),
        delivery_branch_reason=_from_step(steps.get("delivery"), "branch_reason"),
        exit_code=_plain(facts["exit_code"]),
        signal=_plain(facts["signal"]),
        peak_memory=_from_step(steps.get("boundary"), "peak_memory") if launched else unlooked,
        processor_time=_from_step(steps.get("boundary"), "processor_time") if launched else unlooked,
        session_file_kept_at=_from_step(steps.get("kept_files"), "session_file"),
        teardown_failure=_from_step(steps.get("teardown"), "failure"),
        stop_reason=_from_step(steps.get("stop_confirmation"), "stop_reason"),
        stop_asker=_from_step(steps.get("stop_confirmation"), "stop_asker"),
    )
    if observed is not None:
        receipt["what_the_executor_driver_observed"].update(observed)
    elif launched:
        receipt["what_the_executor_driver_observed"].update(
            {name: fixed.CANNOT_TELL for name in fixed.RECEIPT_GROUPS["what_the_executor_driver_observed"]})
    receipt["what_the_executor_said"].update({
        name: _from_step(steps.get("kept_files"), name) if launched else unlooked
        for name in fixed.RECEIPT_GROUPS["what_the_executor_said"]
    })
    return receipt


def check_receipt(receipt):
    """Problems with a receipt, judged against the fixed list. Empty when fine."""
    problems = []
    if set(receipt) != set(fixed.RECEIPT_GROUPS):
        return ["the receipt's groups are %s" % sorted(receipt)]
    for group, names in fixed.RECEIPT_GROUPS.items():
        held = receipt[group]
        for name in sorted(set(names) - set(held)):
            problems.append("%s: field %s is missing" % (group, name))
        for name in sorted(set(held) - set(names)):
            problems.append("%s: field %s is not on the list" % (group, name))
        for name in names:
            if name in held and (held[name] is None or held[name] in ("", [], {})):
                problems.append("%s: field %s holds nothing; it must be a value, 'none' or 'cannot tell'" % (group, name))
    ending = receipt["the_ending"]
    if all(k in ending for k in ("ending", "reason", "failed_step")):
        problems += check_decision({k: ending[k] for k in ("ending", "reason", "failed_step")})
    return problems
