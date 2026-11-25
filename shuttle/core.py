"""The functional core: every decision, as a pure function over plain data."""

from shuttle import fixed


def decide_ending(facts):
    """Decide the ending from facts. Only these facts count.

    refusal: None or {"reason", "step"} from a check before launch.
    launch: "ok", "failed" or "stopped_before".
    wait: "exited", "time_limit", "stop_record" or "signal".
    stop: "confirmed" or "not_confirmed".
    closing_freeze, delivery: "ok" or "failed".

    The executor's exit code and anything that happens after delivery
    (observation, kept files, teardown, the record write) are not read.
    """
    if facts.get("refusal"):
        return _decision("could_not_start", facts["refusal"]["reason"], facts["refusal"]["step"])
    if facts["launch"] == "failed":
        return _decision("could_not_start", "launch_failed", "launch")
    if facts["launch"] == "stopped_before":
        return _decision("could_not_start", "stopped")
    if facts["stop"] == "not_confirmed":
        return _decision("execution_failed", "stop_not_confirmed", "stop_not_confirmed")
    if facts["closing_freeze"] == "failed":
        return _decision("execution_failed", "closing_freeze_failed", "closing_freeze")
    if facts["delivery"] == "failed":
        return _decision("execution_failed", "delivery_failed", "delivery")
    if facts["wait"] == "time_limit":
        return _decision("time_limit", "time_limit")
    if facts["wait"] == "stop_record":
        return _decision("stopped_from_outside", "stop_record")
    if facts["wait"] == "signal":
        return _decision("stopped_from_outside", "signal")
    return _decision("ended_by_itself")


def _decision(ending, reason=fixed.NONE, failed_step=fixed.NONE):
    return {"ending": ending, "reason": reason, "failed_step": failed_step}


def check_decision(decision):
    """Problems with a decision, judged against the fixed list. Empty when fine."""
    problems = []
    ending = decision.get("ending")
    reason = decision.get("reason")
    step = decision.get("failed_step")
    if ending not in fixed.ENDINGS:
        return ["ending %r is not on the list" % (ending,)]
    if reason == fixed.NONE:
        if fixed.REASONS_BY_ENDING[ending]:
            problems.append("ending %s needs a reason" % ending)
    elif reason not in fixed.REASONS_BY_ENDING[ending]:
        problems.append("reason %r does not belong to ending %s" % (reason, ending))
    if step not in (fixed.NONE, fixed.CANNOT_TELL) and step not in fixed.STEPS_BY_ENDING.get(ending, ()):
        problems.append("failed step %r does not belong to ending %s" % (step, ending))
    return problems


def ending_conflicts(known, receipt):
    """Problems when a receipt's ending differs from the ending already known."""
    shown = receipt.get("the_ending", {})
    return [
        "%s is %r in the receipt but %r was known" % (key, shown.get(key), known[key])
        for key in ("ending", "reason", "failed_step")
        if shown.get(key) != known[key]
    ]


_DOCUMENT_FIELDS = ("format_version", "request_id", "records_location", "executor")
_EXECUTOR_FIELDS = ("driver", "settings")
_COMMAND_SETTINGS = ("command", "arguments")
_ID_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


def _valid_request_id(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and all(c in _ID_CHARACTERS for c in value)
    )


def _input_check_refusal(reason, problem, header_source):
    return {
        "header_source": header_source,
        "refusal": {"reason": reason, "step": "input_check"},
        "problem": problem,
    }


def validate_document(raw):
    """Check an input document read from JSON.

    Returns {"header_source", "refusal", "problem"}. header_source is None when
    the document cannot be read far enough to form a header; refusal is then
    None too, because nothing can be recorded. Otherwise refusal is None for a
    good document or {"reason", "step"} for a refusal that gets recorded.
    """
    if not isinstance(raw, dict):
        return {"header_source": None, "refusal": None, "problem": "the document is not a JSON object"}
    if not _valid_request_id(raw.get("request_id")):
        return {"header_source": None, "refusal": None,
                "problem": "request_id is missing or is not 1 to 64 letters, digits, '-' or '_'"}
    if not isinstance(raw.get("records_location"), str) or not raw["records_location"]:
        return {"header_source": None, "refusal": None, "problem": "records_location is missing or not text"}

    executor = raw.get("executor")
    header_source = {
        "request_id": raw["request_id"],
        "records_location": raw["records_location"],
        "executor_name": executor.get("driver") if isinstance(executor, dict) and isinstance(executor.get("driver"), str) else fixed.CANNOT_TELL,
    }

    if raw.get("format_version") != fixed.FORMAT_VERSION:
        return _input_check_refusal(
            "unknown_format_version",
            "format_version must be %d" % fixed.FORMAT_VERSION, header_source)
    unknown = sorted(set(raw) - set(_DOCUMENT_FIELDS))
    if unknown:
        return _input_check_refusal("unknown_field", "unknown field: %s" % ", ".join(unknown), header_source)
    if not isinstance(executor, dict):
        return _input_check_refusal("missing_setting", "executor is missing", header_source)
    unknown = sorted(set(executor) - set(_EXECUTOR_FIELDS))
    if unknown:
        return _input_check_refusal("unknown_field", "unknown field in executor: %s" % ", ".join(unknown), header_source)
    if executor.get("driver") != "command":
        return _input_check_refusal("unknown_executor", "executor driver must be 'command'", header_source)
    settings = executor.get("settings")
    if not isinstance(settings, dict):
        return _input_check_refusal("missing_setting", "executor settings are missing", header_source)
    unknown = sorted(set(settings) - set(_COMMAND_SETTINGS))
    if unknown:
        return _input_check_refusal("unknown_setting", "unknown setting: %s" % ", ".join(unknown), header_source)
    command, arguments = settings.get("command"), settings.get("arguments")
    if not isinstance(command, str) or not command:
        return _input_check_refusal("missing_setting", "setting 'command' is missing", header_source)
    if not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
        return _input_check_refusal("missing_setting", "setting 'arguments' is missing or not a list of text", header_source)
    return {"header_source": header_source, "refusal": None, "problem": None}


def parse_command_line(argv):
    """Turn the arguments after the program name into a form, or a one-line refusal."""
    if argv and argv[0] in ("check", "stop", "status"):
        return {"refusal": "shuttle: the %s form is not built yet; only 'run <input document>' exists" % argv[0]}
    if len(argv) == 2 and argv[0] == "run":
        return {"form": "run", "document_path": argv[1]}
    return {"refusal": "shuttle: usage: python3 -m shuttle run <input document>"}


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
    """A value read from facts: absent means none."""
    return fixed.NONE if value is None else value


def build_header(record_type, header_source, record_id, time):
    return {
        "record_id": record_id,
        "record_type": record_type,
        "time": time,
        "request_id": header_source["request_id"],
        "executor_name": header_source["executor_name"],
        "format_version": fixed.FORMAT_VERSION,
    }


def build_receipt(decision, facts):
    """Build the receipt from the decision and the facts gathered. Every field is present.

    facts: receipt_id, execution_version, host, input_hash, launched, started_at,
    ended_at, observed_runtime, executor_duration, exit_code, signal,
    driver_observations (dict or None), stand_ins (step name to result; a step not
    reached is absent), reason_text.
    """
    steps = facts["stand_ins"]
    launched = facts["launched"]
    reason_text = facts.get("reason_text")
    if reason_text is None:
        reason_text = fixed.NONE if decision["reason"] == fixed.NONE else fixed.CANNOT_TELL
    observed = facts.get("driver_observations")
    unlooked = fixed.NONE

    receipt = {group: {name: fixed.NONE for name in names} for group, names in fixed.RECEIPT_GROUPS.items()}

    receipt["the_ending"].update(
        decision,
        reason_text=reason_text,
        receipt_id=facts["receipt_id"],
        everything_stopped=_from_step(steps.get("stop_confirmation"), "everything_stopped"),
        execution_version=facts["execution_version"],
        host=facts["host"],
    )
    receipt["what_execution_saw"].update(
        started_at=_plain(facts["started_at"]),
        ended_at=_plain(facts["ended_at"]),
        observed_runtime=_plain(facts["observed_runtime"]),
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
        receipt["what_the_driver_observed"].update(observed)
    receipt["what_the_executor_said"].update({
        name: _from_step(steps.get("kept_files"), name) if launched else unlooked
        for name in fixed.RECEIPT_GROUPS["what_the_executor_said"]
    })
    return receipt


def _changed_nothing(steps):
    before, after = steps.get("opening_fingerprint"), steps.get("closing_freeze")
    if before is None or after is None:
        return fixed.NONE
    if is_stand_in(before) or is_stand_in(after):
        return fixed.CANNOT_TELL
    return before.get("fingerprint") == after.get("fingerprint")


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


def exit_facts(returncode):
    """From a child's return code: (exit code, signal name). A kill by signal has no exit code."""
    import signal as signal_module
    if returncode is None:
        return None, None
    if returncode < 0:
        try:
            return None, signal_module.Signals(-returncode).name
        except ValueError:
            return None, "signal %d" % -returncode
    return returncode, None
