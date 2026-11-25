"""The functional core: every decision, as a pure function over plain data.

Nothing here touches a file, the clock, the environment or a process.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from shuttle import fixed
from shuttle.shapes import (
    Conclusion,
    Decision,
    Document,
    DocumentCheck,
    Facts,
    HeaderSource,
    Receipt,
    StepResult,
)

# ---------------------------------------------------------------- the ending

_LAUNCH = ("ok", "failed", "stopped_before")
_WAIT = ("exited", "time_limit", "stop_record", "signal", "error")
_CNS = "could_not_start"
_EF = "execution_failed"


def _decision(ending: str, reason: str = fixed.NONE, failed_step: str = fixed.NONE) -> Decision:
    return {"ending": ending, "reason": reason, "failed_step": failed_step}


def _before_launch_error(step: str) -> Decision:
    """Execution itself broke before the executor started, in this step."""
    return _decision(_CNS, "execution_error", step)


def _after_launch_error() -> Decision:
    """Execution itself broke after the executor started, in a step that is not known."""
    return _decision(_EF, "execution_error", fixed.CANNOT_TELL)


def decide_ending(facts: Facts) -> Decision:
    """Decide the ending from facts. Total: it never raises.

    For every combination of fact values, including facts that are missing or
    "cannot tell", it returns an (ending, reason, failed step) that the fixed
    list allows. A fact it cannot make sense of is "execution_error".

    The facts, by step of a run (a step that did not run has no fact):
      id_claim: "ok", "used" or "unusable".
      input_check, executor_driver_check: None, or the reason code of the refusal.
      gates: "ok", "no" or "failed". setup, opening_freeze: "ok" or "failed".
      launch: "ok", "failed" or "stopped_before".
      wait: "exited", "time_limit", "stop_record", "signal" or "error".
      stop: "confirmed" or "not_confirmed". closing_freeze, delivery: "ok" or "failed".

    The executor's exit code and signal, and anything that happens after delivery
    (observing, kept files, teardown, the record write), are not read.
    """
    try:
        decision = _decide(facts)
    except Exception:
        return _after_launch_error()
    if check_decision(decision):
        return _after_launch_error()
    return decision


def _decide(f: Facts) -> Decision:
    before = _decide_before_launch(f)
    if before is not None:
        return before
    launch = f.get("launch")
    if launch == "failed":
        return _decision(_CNS, "launch_failed", "launch")
    if launch == "stopped_before":
        return _decision(_CNS, "stopped")
    if launch != "ok":
        return _before_launch_error("launch")
    return _decide_after_launch(f)


def _decide_before_launch(f: Facts) -> Decision | None:
    """The decision when a step before the launch refused or failed, else None."""
    claim = f.get("id_claim", "ok")
    if claim == "used":
        return _decision(_CNS, "request_id_used", "id_claim")
    if claim == "unusable":
        return _decision(_CNS, "records_location_unusable", "id_claim")
    if claim != "ok":
        return _before_launch_error("id_claim")
    for step in ("input_check", "executor_driver_check"):
        reason = f.get(step)
        if reason is None:
            continue
        if (
            isinstance(reason, str)
            and reason in fixed.REASONS_BY_ENDING[_CNS]
            and step in fixed.STEPS_FOR_REASON[reason]
        ):
            return _decision(_CNS, reason, step)
        return _before_launch_error(step)
    for step, bad in (
        ("gates", {"no": "gate_said_no", "failed": "gate_failed"}),
        ("setup", {"failed": "setup_failed"}),
        ("opening_freeze", {"failed": "freeze_failed"}),
    ):
        value = f.get(step)
        if value is None or value == "ok":
            continue
        if value in bad:
            return _decision(_CNS, bad[value], step)
        return _before_launch_error(step)
    return None


def _decide_after_launch(f: Facts) -> Decision:
    wait = f.get("wait")
    if wait not in _WAIT:
        return _after_launch_error()
    if wait == "error" or f.get("stop") == "not_confirmed":
        return _decision(_EF, "stop_not_confirmed", "stop_not_confirmed")
    if f.get("stop") != "confirmed":
        return _after_launch_error()
    for step, failed_reason in (
        ("closing_freeze", "closing_freeze_failed"),
        ("delivery", "delivery_failed"),
    ):
        if f.get(step) == "failed":
            return _decision(_EF, failed_reason, step)
        if f.get(step) != "ok":
            return _after_launch_error()
    if wait == "time_limit":
        return _decision("time_limit", "time_limit")
    if wait == "stop_record":
        return _decision("stopped_from_outside", "stop_record")
    if wait == "signal":
        return _decision("stopped_from_outside", "signal")
    return _decision("ended_by_itself")


def check_decision(decision: Mapping[str, Any]) -> list[str]:
    """Problems with a decision, judged against the fixed list. Empty when fine.

    For a reader of records and for the tests; the writer never blocks on it.
    """
    ending = decision.get("ending")
    reason = decision.get("reason")
    step = decision.get("failed_step")
    if ending not in fixed.ENDINGS:
        return [f"ending {ending!r} is not on the list"]
    reasons = fixed.REASONS_BY_ENDING[ending]
    if reason == fixed.NONE:
        problems = [f"ending {ending} needs a reason"] if reasons else []
        if step != fixed.NONE:
            problems.append(f"failed step {step!r} needs a reason")
        return problems
    if reason not in reasons:
        return [f"reason {reason!r} does not belong to ending {ending}"]
    if step not in fixed.STEPS_FOR_REASON[reason]:
        return [f"failed step {step!r} does not go with reason {reason}"]
    if step not in fixed.STEPS_BY_ENDING.get(ending, ()) and step not in (
        fixed.NONE,
        fixed.CANNOT_TELL,
    ):
        return [f"failed step {step!r} does not belong to ending {ending}"]
    if step == fixed.CANNOT_TELL and ending == _CNS:
        return [f"ending {ending} always names its step"]
    return []


def ending_conflicts(known: Mapping[str, Any], receipt: Receipt) -> list[str]:
    """Problems when a receipt's ending differs from the ending already known."""
    shown = receipt.get("the_ending", {})
    return [
        f"{key} is {shown.get(key)!r} in the receipt but {known[key]!r} was known"
        for key in ("ending", "reason", "failed_step")
        if shown.get(key) != known[key]
    ]


def reason_text(decision: Decision, problems: Mapping[str, str]) -> str:
    """The one line beside the reason: the problem recorded for its step, or none, or cannot tell."""
    if decision["reason"] == fixed.NONE:
        return fixed.NONE
    return problems.get(decision["failed_step"]) or fixed.CANNOT_TELL


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
_STEP_FAILURES: dict[str, tuple[str | None, Facts]] = {
    "read_and_validate_document": (None, {"unreadable": True}),
    "claim_request_id": ("id_claim", {"id_claim": "unusable"}),
    "run_input_checks_and_executor_driver_check": (
        "executor_driver_check",
        {"executor_driver_check": "execution_error"},
    ),
    "run_gates": ("gates", {"gates": "failed"}),
    "set_up_run_area": ("setup", {"setup": "failed"}),
    "take_opening_fingerprint": ("opening_freeze", {"opening_freeze": "failed"}),
    "launch_executor": ("launch", {"launch": "failed"}),
    "wait_for_the_end": ("stop_not_confirmed", {"wait": "error"}),
    "stop_everything_and_confirm_empty": ("stop_not_confirmed", {"stop": "not_confirmed"}),
    "take_closing_freeze": ("closing_freeze", {"closing_freeze": "failed"}),
    "deliver": ("delivery", {"delivery": "failed"}),
}


def facts_after_error(step: str) -> Facts:
    """The facts a step leaves when it raises an error. Observing, kept files and teardown leave none."""
    return dict(_STEP_FAILURES.get(step, (None, {}))[1])


def failed_step_after_error(step: str) -> str | None:
    """The failed step an error in this step stands for, or None."""
    return _STEP_FAILURES.get(step, (None, {}))[0]


def facts_after_signal(facts: Facts, signal_name: str | None) -> Facts:
    """A signal that arrived before the executor started is a stop before launch.

    After launch it adds no fact: the wait sees the signal itself.
    """
    if signal_name and facts.get("launch") != "ok":
        return {"launch": "stopped_before"}
    return {}


def wait_cause(child_exited: bool, deadline_passed: bool, signal_name: str | None) -> str | None:
    """What ends the wait, or None to keep waiting. The first cause seen wins."""
    if child_exited:
        return "exited"
    if signal_name:
        return "signal"
    if deadline_passed:
        return "time_limit"
    return None


def _failed_before_launch(f: Facts) -> bool:
    return bool(
        f.get("input_check")
        or f.get("executor_driver_check")
        or f.get("gates") in ("no", "failed")
        or f.get("setup") == "failed"
        or f.get("opening_freeze") == "failed"
        or f.get("launch") in ("failed", "stopped_before")
    )


def step_runs(step: str, facts: Facts) -> bool:
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


def outcome_kind(facts: Facts) -> str:
    """What the last step must do: "unreadable", "not_recorded" or "record"."""
    if facts.get("unreadable") or facts.get("header_source") is None:
        return "unreadable"
    if facts.get("id_claim") in ("used", "unusable"):
        return "not_recorded"
    return "record"


def result_status(result: object) -> str:
    """A step's result as a fact: a stand-in never fails; a real step reports ok=False when it does."""
    return (
        "failed"
        if isinstance(result, dict) and result.get("ok") is False and not is_stand_in(result)
        else "ok"
    )


def conclude(outcome: Mapping[str, Any]) -> Conclusion:
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
            "stderr": [
                "shuttle: the outcome record was not written ({}); the receipt is printed below "
                "and the ending stands".format(outcome["problem"])
            ],
            "exit": 1,
        }
    if kind == "not_recorded":
        problem = (
            outcome.get("problem")
            or "the request id could not be claimed; nothing was done; check the records_location"
        )
        return {
            "stdout": [outcome["decision"]["ending"]],
            "stderr": [f"shuttle: {problem}"],
            "exit": 1,
        }
    problem = (
        outcome.get("problem")
        or "the input document could not be read far enough to start; nothing was done; fix it and run again"
    )
    return {"stdout": ["none"], "stderr": [f"shuttle: {problem}"], "exit": 1}


# ------------------------------------------------------------------ the document

_DOCUMENT_FIELDS = (
    "format_version",
    "request_id",
    "records_location",
    "thread",
    "round",
    "kind",
    "parent_session",
    "asked_by",
    "time_limit_seconds",
    "environment",
    "executor",
)
_EXECUTOR_FIELDS = ("name", "settings")
_COMMAND_SETTINGS = ("command", "arguments")
_ID_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
_NAME_CHARACTERS = _ID_CHARACTERS


def _valid_request_id(value: object) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 64 and all(c in _ID_CHARACTERS for c in value)
    )


def _plain_int(value: object) -> bool:
    return type(value) is int


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


_LONGEST_TIME_LIMIT_SECONDS = 10**9


def _usable_time_limit(value: object) -> bool:
    """A finite number above zero that the clock can use."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        seconds = float(value)
    except OverflowError:
        return False
    return math.isfinite(seconds) and 0 < seconds <= _LONGEST_TIME_LIMIT_SECONDS


def _refusal(reason: str, problem: str, header_source: HeaderSource) -> DocumentCheck:
    return {
        "header_source": header_source,
        "refusal": {"reason": reason, "step": "input_check"},
        "problem": problem,
    }


def _no_header(problem: str) -> DocumentCheck:
    return {"header_source": None, "refusal": None, "problem": problem}


def _header_problem(raw: object) -> str | None:
    """The problem that stops a header being formed from the document, or None."""
    if not isinstance(raw, dict):
        return "the document is not a JSON object"
    if not _valid_request_id(raw.get("request_id")):
        return "request_id is missing or is not 1 to 64 letters, digits, '-' or '_'"
    for field in ("records_location", "thread", "kind"):
        if not _text(raw.get(field)):
            return f"{field} is missing or is not text"
    if not _plain_int(raw.get("round")):
        return "round is missing or is not an integer"
    for field in ("parent_session", "asked_by"):
        if field in raw and not _text(raw[field]):
            return f"{field} is not text"
    return None


def _header_source(raw: Document) -> HeaderSource:
    executor = raw.get("executor")
    name = fixed.CANNOT_TELL
    if isinstance(executor, dict) and _text(executor.get("name")):
        name = executor["name"]
    return {
        "request_id": raw["request_id"],
        "records_location": raw["records_location"],
        "thread": raw["thread"],
        "round": raw["round"],
        "kind": raw["kind"],
        "parent_session": raw.get("parent_session", fixed.NONE),
        "asked_by": raw.get("asked_by", fixed.NONE),
        "executor_name": name,
    }


def _unknown_names(found: Iterable[str], allowed: Iterable[str]) -> str:
    return ", ".join(sorted(set(found) - set(allowed)))


def _executor_refusal(executor: object) -> tuple[str, str] | None:
    """(reason, problem) when the executor part of the document is refused, else None."""
    if not isinstance(executor, dict):
        return "missing_setting", "executor is missing"
    unknown = _unknown_names(executor, _EXECUTOR_FIELDS)
    if unknown:
        return "unknown_field", f"unknown field in executor: {unknown}"
    if executor.get("name") != "command":
        return "unknown_executor", "executor name must be 'command' (the command driver)"
    settings = executor.get("settings")
    if not isinstance(settings, dict):
        return "missing_setting", "executor settings are missing"
    unknown = _unknown_names(settings, _COMMAND_SETTINGS)
    if unknown:
        return "unknown_setting", f"unknown setting: {unknown}"
    command, arguments = settings.get("command"), settings.get("arguments")
    if not _text(command):
        return "missing_setting", "setting 'command' is missing"
    if not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
        return "missing_setting", "setting 'arguments' is missing or not a list of text"
    return None


def _document_refusal(raw: Document) -> tuple[str, str] | None:
    """(reason, problem) when a document whose header can be formed is refused, else None."""
    if not _plain_int(raw.get("format_version")) or raw["format_version"] != fixed.FORMAT_VERSION:
        return (
            "unknown_format_version",
            f"format_version must be the integer {fixed.FORMAT_VERSION}",
        )
    unknown = _unknown_names(raw, _DOCUMENT_FIELDS)
    if unknown:
        return "unknown_field", f"unknown field: {unknown}"
    refusal = _executor_refusal(raw.get("executor"))
    if refusal:
        return refusal
    if not _usable_time_limit(raw.get("time_limit_seconds")):
        return (
            "no_time_limit",
            "time_limit_seconds is required and must be a number above zero and at most "
            f"{_LONGEST_TIME_LIMIT_SECONDS}",
        )
    names = raw.get("environment", [])
    if not isinstance(names, list) or not all(
        _text(n) and all(c in _NAME_CHARACTERS for c in n) for n in names
    ):
        return "missing_setting", "environment must be a list of variable names"
    return None


def validate_document(raw: object) -> DocumentCheck:
    """Check an input document read from JSON.

    Returns {"header_source", "refusal", "problem"}. header_source is None when
    the document cannot be read far enough to form a header; refusal is then
    None too, because nothing can be recorded. Otherwise refusal is None for a
    good document or {"reason", "step"} for a refusal that gets recorded.
    """
    problem = _header_problem(raw)
    if problem or not isinstance(raw, dict):
        return _no_header(problem or "the document is not a JSON object")
    header_source = _header_source(raw)
    refusal = _document_refusal(raw)
    if refusal:
        return _refusal(refusal[0], refusal[1], header_source)
    return {"header_source": header_source, "refusal": None, "problem": None}


def parse_command_line(argv: Sequence[str]) -> dict[str, str]:
    """Turn the arguments after the program name into a form, or a one-line refusal."""
    if argv and argv[0] in ("check", "stop", "status"):
        return {
            "refusal": f"shuttle: the {argv[0]} form is not built yet; only 'run <input document>' exists"
        }
    if len(argv) == 2 and argv[0] == "run":
        return {"form": "run", "document_path": argv[1]}
    return {"refusal": "shuttle: usage: python3 -m shuttle run <input document>"}


def executor_driver_check(
    command: str,
    environment_names: Iterable[str],
    caller_environment: Mapping[str, str],
    tool_found: bool,
) -> tuple[str | None, str | None]:
    """The command driver's check and the check of the named variables: (reason, one line) or (None, None)."""
    missing = [n for n in environment_names if n not in caller_environment]
    if missing:
        return (
            "missing_setting",
            "environment variable(s) {} named in the document are not set; set them or remove the names".format(
                ", ".join(missing)
            ),
        )
    if not tool_found:
        return (
            "tool_not_installed",
            f"the command {command!r} was not found; install it or name one that exists",
        )
    return None, None


def claim_problem(kind: str, request_id: str, records_location: str, error_name: str) -> str:
    """The one line for a request id that could not be claimed."""
    if kind == "used":
        return (
            f"request id {request_id!r} was already used; nothing was done; give the run a new request id"
        )
    if kind == "not_built":
        return (
            f"the request record could not be built from the document ({error_name}); nothing was done and "
            f"request id {request_id!r} is NOT spent; fix the document and run again"
        )
    return (
        f"records_location {records_location!r} cannot take the request record ({error_name}); nothing was done and the request id is NOT spent; "
        "name a folder that exists and can be written"
    )


def check_environment(names: Iterable[str], caller_environment: Mapping[str, str]) -> str | None:
    """The reason code that refuses the named variables, or None."""
    if any(name not in caller_environment for name in names):
        return "missing_setting"
    return None


def build_environment(
    names: Iterable[str], caller_environment: Mapping[str, str]
) -> dict[str, str]:
    """The executor's environment: PATH and the named variables, nothing else."""
    built = {"PATH": caller_environment.get("PATH", "/usr/bin:/bin")}
    for name in names:
        built[name] = caller_environment[name]
    return built


# --------------------------------------------------------------------- the records


def build_header(
    record_type: str, header_source: HeaderSource, record_id: str, time: str
) -> dict[str, Any]:
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


def is_stand_in(value: object) -> bool:
    return isinstance(value, dict) and fixed.STAND_IN_KEY in value


def _from_step(result: StepResult | None, key: str) -> Any:
    """A receipt value from a step's result.

    A step that was not reached gives none. A stand-in gives "cannot tell".
    A real step gives the value under key.
    """
    if result is None:
        return fixed.NONE
    if is_stand_in(result):
        return fixed.CANNOT_TELL
    return result.get(key, fixed.CANNOT_TELL)


def _plain(value: Any) -> Any:
    return fixed.NONE if value is None else value


def _changed_nothing(steps: Mapping[str, StepResult]) -> Any:
    before, after = steps.get("opening_fingerprint"), steps.get("closing_freeze")
    if before is None or after is None:
        return fixed.NONE
    if is_stand_in(before) or is_stand_in(after):
        return fixed.CANNOT_TELL
    return before.get("fingerprint") == after.get("fingerprint")


def build_receipt(decision: Mapping[str, Any], facts: Facts) -> Receipt:
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

    receipt = {
        group: {name: fixed.NONE for name in names} for group, names in fixed.RECEIPT_GROUPS.items()
    }
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
        processor_time=_from_step(steps.get("boundary"), "processor_time")
        if launched
        else unlooked,
        session_file_kept_at=_from_step(steps.get("kept_files"), "session_file"),
        teardown_failure=_from_step(steps.get("teardown"), "failure"),
        stop_reason=_from_step(steps.get("stop_confirmation"), "stop_reason"),
        stop_asker=_from_step(steps.get("stop_confirmation"), "stop_asker"),
    )
    if observed is not None:
        receipt["what_the_executor_driver_observed"].update(observed)
    elif launched:
        receipt["what_the_executor_driver_observed"].update(
            {
                name: fixed.CANNOT_TELL
                for name in fixed.RECEIPT_GROUPS["what_the_executor_driver_observed"]
            }
        )
    receipt["what_the_executor_said"].update(
        {
            name: _from_step(steps.get("kept_files"), name) if launched else unlooked
            for name in fixed.RECEIPT_GROUPS["what_the_executor_said"]
        }
    )
    return receipt


def minimal_receipt(decision: Mapping[str, Any]) -> Receipt:
    """The receipt when building the full one failed: the decision, and "cannot tell" for everything else."""
    receipt = {
        group: {name: fixed.CANNOT_TELL for name in names}
        for group, names in fixed.RECEIPT_GROUPS.items()
    }
    receipt["the_ending"].update(decision)
    return receipt


def check_receipt(receipt: Receipt) -> list[str]:
    """Problems with a receipt, judged against the fixed list. Empty when fine."""
    problems = []
    if set(receipt) != set(fixed.RECEIPT_GROUPS):
        return [f"the receipt's groups are {sorted(receipt)}"]
    for group, names in fixed.RECEIPT_GROUPS.items():
        held = receipt[group]
        for name in sorted(set(names) - set(held)):
            problems.append(f"{group}: field {name} is missing")
        for name in sorted(set(held) - set(names)):
            problems.append(f"{group}: field {name} is not on the list")
        for name in names:
            if name in held and (held[name] is None or held[name] in ("", [], {})):
                problems.append(
                    f"{group}: field {name} holds nothing; it must be a value, 'none' or 'cannot tell'"
                )
    ending = receipt["the_ending"]
    if all(k in ending for k in ("ending", "reason", "failed_step")):
        problems += check_decision({k: ending[k] for k in ("ending", "reason", "failed_step")})
    return problems
