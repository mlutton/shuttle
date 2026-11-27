"""The functional core: every decision, as a pure function over plain data.

Nothing here touches a file, the clock, the environment or a process.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from shuttle.core import boundary, fixed, pairs, refusals
from shuttle.core.drivers import table
from shuttle.core.shapes import (
    Conclusion,
    Decision,
    Document,
    DocumentCheck,
    DriverFacts,
    EndingGroup,
    ExecutionGroup,
    ExecutorDriverGroup,
    ExecutorGroup,
    Facts,
    HeaderSource,
    Outcome,
    Pair,
    Receipt,
    ReceiptFacts,
    RecordHeader,
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


def _decide_before_launch(f: Mapping[str, object]) -> Decision | None:
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
        if isinstance(value, str) and value in bad:
            return _decision(_CNS, bad[value], step)
        return _before_launch_error(step)
    return None


def _decide_after_launch(f: Mapping[str, object]) -> Decision:
    wait = f.get("wait")
    if wait == "error" or f.get("stop") == "not_confirmed":
        return _decision(_EF, "stop_not_confirmed", "stop_not_confirmed")
    if wait not in _WAIT:
        return _after_launch_error()
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


def check_decision(decision: Mapping[str, object]) -> list[str]:
    """Problems with a decision, judged against the fixed list. Empty when fine.

    For a reader of records and for the tests; the writer never blocks on it.
    """
    ending = decision.get("ending")
    reason = decision.get("reason")
    step = decision.get("failed_step")
    if not isinstance(ending, str) or ending not in fixed.ENDINGS:
        return [f"ending {ending!r} is not on the list"]
    reasons = fixed.REASONS_BY_ENDING[ending]
    if reason == fixed.NONE:
        problems = [f"ending {ending} needs a reason"] if reasons else []
        if step != fixed.NONE:
            problems.append(f"failed step {step!r} needs a reason")
        return problems
    if not isinstance(reason, str) or reason not in reasons:
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


def ending_conflicts(known: Mapping[str, object], receipt: Mapping[str, object]) -> list[str]:
    """Problems when a receipt's ending differs from the ending already known."""
    shown = receipt.get("ending", {})
    if not isinstance(shown, Mapping):
        shown = {}
    return [
        f"{key} is {pairs.text_of(shown.get(key))!r} in the receipt but {known[key]!r} was known"
        for key in ("ending", "reason", "failed_step")
        if pairs.text_of(shown.get(key)) != known[key]
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
    return _STEP_FAILURES.get(step, (None, {}))[1].copy()


def failed_step_after_error(step: str) -> str | None:
    """The failed step an error in this step stands for, or None."""
    return _STEP_FAILURES.get(step, (None, {}))[0]


def exit_facts(returncode: int | None, signal_name: str | None) -> tuple[int | None, str | None]:
    """From a child's return code and the name of the signal numbered by its negation, if there
    is one: (exit code, signal name). A kill by signal has no exit code; a signal with no name
    is called "signal N"."""
    if returncode is None:
        return None, None
    if returncode < 0:
        return None, signal_name or f"signal {-returncode}"
    return returncode, None


def facts_after_signal(facts: Facts, signal_name: str | None) -> Facts:
    """A signal that arrived before the executor started is a stop before launch.

    After launch it adds no fact: the wait sees the signal itself.
    """
    if signal_name and facts.get("launch") != "ok":
        return {"launch": "stopped_before"}
    return {}


def _failed_before_launch(f: Mapping[str, object]) -> bool:
    return bool(
        f.get("input_check")
        or f.get("executor_driver_check")
        or f.get("gates") in ("no", "failed")
        or f.get("setup") == "failed"
        or f.get("opening_freeze") == "failed"
        or f.get("launch") in ("failed", "stopped_before")
    )


def step_runs(step: str, facts: Mapping[str, object]) -> bool:
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
    if step == "tear_down":  # the run area is removed whatever the ending, once set-up was tried
        return facts.get("header_source") is not None and "setup" in facts
    if facts.get("header_source") is None or _failed_before_launch(facts):
        return False
    # Nothing is frozen or delivered unless the stop is confirmed: until then something may still
    # be writing the place.
    stop_confirmed = facts.get("stop") == "confirmed" and facts.get("wait") != "error"
    if step == "take_closing_freeze":
        return stop_confirmed
    if step == "deliver":
        return stop_confirmed and facts.get("closing_freeze") != "failed"
    return True


def outcome_kind(facts: Mapping[str, object]) -> str:
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


def conclude(outcome: Outcome) -> Conclusion:
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
    "instruction",
    "instruction_hash",
    "references",
    "gates",
    "statement_location",
    "reach",
    "place",
    "freeze_limit_seconds",
    "network",
    "changes_to_place",
)
_REFERENCE_FIELDS = ("name", "path", "hash", "size", "hash_source")
_GATE_FIELDS = ("name", "command", "arguments", "limit_seconds")
_EXECUTOR_FIELDS = ("name", "settings")
_ID_CHARACTERS = fixed.ID_CHARACTERS
_NAME_CHARACTERS = fixed.ID_CHARACTERS


def _valid_request_id(value: object) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 64 and all(c in _ID_CHARACTERS for c in value)
    )


def _plain_int(value: object) -> bool:
    return type(value) is int


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _usable_time_limit(value: object) -> bool:
    """A number the boundary's own timer can take (shuttle.core.boundary)."""
    return boundary.usable_time_limit(value)


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
    driver = table.DRIVERS.get(str(executor.get("name")))
    if driver is None:
        return "unknown_executor", f"executor name must be one of: {', '.join(table.DRIVERS)}"
    settings = executor.get("settings")
    if not isinstance(settings, dict):
        return "missing_setting", "executor settings are missing"
    return driver.settings_refusal(settings)


def _document_refusal(raw: Document) -> tuple[str, str] | None:
    """(reason, problem) when a document whose header can be formed is refused, else None."""
    if not _plain_int(raw.get("format_version")) or raw["format_version"] != fixed.INPUT_VERSION:
        return (
            "unknown_format_version",
            f"format_version must be the integer {fixed.INPUT_VERSION}",
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
            "time_limit_seconds is required and must be a number from "
            f"{boundary.SHORTEST_LIMIT_SECONDS:g} to {boundary.LONGEST_LIMIT_SECONDS} seconds",
        )
    env = refusals.check_environment_entries(raw.get("environment", []))
    if env:
        return env["reason"], env["problem"]
    return _parts_refusal(raw)


def _list_of_objects(value: object, what: str) -> tuple[str, str] | None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return "missing_setting", f"{what} must be a list of objects"
    return None


def _reference_refusal(reference: Document) -> tuple[str, str] | None:
    unknown = _unknown_names(reference, _REFERENCE_FIELDS)
    if unknown:
        return "unknown_field", f"unknown field in a reference: {unknown}"
    texts = all(_text(reference.get(f)) for f in ("name", "path", "hash", "hash_source"))
    if not texts or not _plain_int(reference.get("size")) or reference["size"] < 0:
        return "missing_setting", "a reference needs name, path, hash, size and hash_source"
    return None


def _gate_refusal(gate: Document) -> tuple[str, str] | None:
    unknown = _unknown_names(gate, _GATE_FIELDS)
    if unknown:
        return "unknown_field", f"unknown field in a gate: {unknown}"
    arguments = gate.get("arguments")
    if (
        not _text(gate.get("name"))
        or not _text(gate.get("command"))
        or not isinstance(arguments, list)
        or not all(isinstance(a, str) for a in arguments)
        or not _usable_time_limit(gate.get("limit_seconds"))
    ):
        return "missing_setting", "a gate needs name, command, arguments and limit_seconds above 0"
    return None


def _standard_settings_refusal(raw: Document) -> tuple[str, str] | None:
    for field, words in (("network", ("on", "off")), ("changes_to_place", ("allowed", "not"))):
        if field in raw and raw[field] not in words:
            return "unknown_setting", f"{field} must be one of: {', '.join(words)}"
    return None


def _parts_refusal(raw: Document) -> tuple[str, str] | None:
    """The shape of the parts the refusal checks judge; what they hold is judged by those checks."""
    for field in ("instruction", "instruction_hash", "statement_location", "place"):
        if field in raw and not isinstance(raw[field], str):
            return "missing_setting", f"{field} is not text"
    refusal = _standard_settings_refusal(raw)
    if refusal:
        return refusal
    if "freeze_limit_seconds" in raw and not _usable_time_limit(raw["freeze_limit_seconds"]):
        return (
            "missing_setting",
            "freeze_limit_seconds must be a number from "
            f"{boundary.SHORTEST_LIMIT_SECONDS:g} to {boundary.LONGEST_LIMIT_SECONDS} seconds",
        )
    for field, refuse in (("references", _reference_refusal), ("gates", _gate_refusal)):
        if field not in raw:
            continue
        refusal = _list_of_objects(raw[field], field)
        if refusal:
            return refusal
        for item in raw[field]:
            refusal = refuse(item)
            if refusal:
                return refusal
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
    if len(argv) == 2 and argv[0] in ("run", "check"):
        return {"form": argv[0], "document_path": argv[1]}
    if argv and argv[0] in ("stop", "status"):
        return {
            "refusal": f"shuttle: the {argv[0]} form is not built yet; only 'run' and 'check' exist"
        }
    return {"refusal": "shuttle: usage: python3 -m shuttle run|check <input document>"}


def standard_settings(raw: Mapping[str, Any]) -> tuple[bool | None, bool | None]:
    """The document's two standard settings as (network on, changes to the place allowed); None
    for one the document did not give."""
    network, changes = raw.get("network"), raw.get("changes_to_place")
    return (
        None if network is None else network == "on",
        None if changes is None else changes == "allowed",
    )


def copy_reply_to_statement(
    arrives: str, location: str | None, location_taken: bool, reply_given: bool
) -> bool:
    """Whether the tool's final message is to be copied to the statement location: only for a
    tool whose statement is its final message, when it gave one, the kind has a location, and
    nothing is there yet (a file the executor left itself is never replaced)."""
    return arrives == "reply" and reply_given and location is not None and not location_taken


def executor_driver_check(
    executor: Mapping[str, Any],
    environment_names: Iterable[str],
    caller_environment: Mapping[str, str],
    facts: DriverFacts,
) -> tuple[str | None, str | None]:
    """The named variables' check, then the driver's own: (reason, one line) or (None, None)."""
    missing = [n for n in environment_names if n not in caller_environment]
    if missing:
        return (
            "missing_setting",
            "environment variable(s) {} named in the document are not set; set them or remove the names".format(
                ", ".join(missing)
            ),
        )
    refusal = table.DRIVERS[executor["name"]].check(executor["settings"], facts)
    return refusal if refusal else (None, None)


def claim_problem(kind: str, request_id: str, records_location: str, error_name: str) -> str:
    """The one line for a request id that could not be claimed."""
    if kind == "used":
        return f"request id {request_id!r} was already used; nothing was done; give the run a new request id"
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


def record_name(request_id: str, kind: str) -> str:
    """The name of a request id's record of one kind (a kind on `fixed.RECORD_KINDS`).

    The one place record names are made.
    """
    if kind not in fixed.RECORD_KINDS:
        raise ValueError(f"{kind!r} is not a kind of record")
    return f"{request_id}.{kind}.json"


def temporary_name(name: str, process_number: int) -> str:
    """The name a record has while it is being written: its own, then `.tmp-`, then the process number."""
    return f"{name}.tmp-{process_number}"


def join_path(folder: str, name: str) -> str:
    """A name inside a folder, written the way os.path.join writes it on a POSIX system."""
    if not folder or folder.endswith("/"):
        return folder + name
    return f"{folder}/{name}"


def build_header(
    record_type: str, header_source: HeaderSource, record_id: str, time: str
) -> RecordHeader:
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
        "record_version": fixed.RECORD_VERSION,
    }


def is_stand_in(value: object) -> bool:
    return isinstance(value, dict) and fixed.STAND_IN_KEY in value


def _from_step(result: StepResult | None, key: str) -> Pair:
    """A receipt field from a step's result.

    A step that was not reached gives none. A stand-in gives "not built".
    A real step gives what it returned under key: a value, "none" when that is empty,
    "cannot tell" when it returned nothing for the key or something JSON cannot hold.
    """
    if result is None:
        return pairs.none()
    if is_stand_in(result):
        return pairs.not_built()
    values: Mapping[str, object] = result
    if values.get(key) is None:
        return pairs.cannot_tell()
    return pairs.observed(values[key])


def _files_list(result: StepResult | None) -> Pair:
    """The list of files kept. No step builds it yet, so a step that did not give one has not
    built it ("not built"); "cannot tell" is for a step that tried to build it and could not."""
    if result is not None and not is_stand_in(result) and "files_list" not in result:
        return pairs.not_built()
    return _from_step(result, "files_list")


def _changed_nothing(steps: Mapping[str, StepResult]) -> Pair:
    before, after = steps.get("opening_fingerprint"), steps.get("closing_freeze")
    if before is None or after is None:
        return pairs.none()
    if is_stand_in(before) or is_stand_in(after):
        return pairs.not_built()
    if before.get("ok") is False or after.get("ok") is False:
        return pairs.cannot_tell()  # a freeze that failed has no fingerprint to compare
    return pairs.value(before.get("fingerprint") == after.get("fingerprint"))


def _driver_group_of(value: Pair) -> ExecutorDriverGroup:
    return {
        "executor_driver_name": value,
        "executor_driver_version": value,
        "tool_version": value,
        "model": value,
        "effort": value,
        "tokens_in": value,
        "tokens_out": value,
        "tokens_cached": value,
        "activity": value,
        "session_id": value,
        "refused_actions": value,
        "quota_level": value,
        "vendor_limit_reached": value,
        "vendor_limit_reset": value,
        "tool_made_own_commits": value,
        "load_lists_differ": value,
        "load_lists_kept_file": value,
        "changed_self_loaded_file": value,
        "waiting_question": value,
    }


def _executor_group_all(value: Pair) -> ExecutorGroup:
    return {
        "statement_state": value,
        "statement_hash": value,
        "statement_location": value,
        "claim": value,
    }


def _execution_group_of(value: Pair) -> ExecutionGroup:
    return {
        "execution_version": value,
        "host": value,
        "started_at": value,
        "ended_at": value,
        "observed_runtime": value,
        "duration_gates_seconds": value,
        "duration_opening_freeze_seconds": value,
        "duration_executor_seconds": value,
        "duration_closing_freeze_seconds": value,
        "duration_delivery_seconds": value,
        "input_hash": value,
        "reference_hashes": value,
        "fingerprint_before": value,
        "fingerprint_after": value,
        "changed_nothing": value,
        "files_added": value,
        "files_changed": value,
        "files_deleted": value,
        "files_list_kept_file": value,
        "delivered": value,
        "delivery_branch": value,
        "delivery_branch_reason": value,
        "exit_code": value,
        "signal": value,
        "peak_memory_bytes": value,
        "processor_time_seconds": value,
        "session_file_kept_at": value,
        "teardown_failure": value,
        "stop_reason": value,
        "stop_asker": value,
    }


def _executor_group_of(steps: Mapping[str, StepResult], launched: bool) -> ExecutorGroup:
    kept = steps.get("kept_files")
    if not launched:
        return _executor_group_all(pairs.none())
    return {
        "statement_state": _from_step(kept, "statement_state"),
        "statement_hash": _from_step(kept, "statement_hash"),
        "statement_location": _from_step(kept, "statement_location"),
        "claim": _from_step(kept, "claim"),
    }


class ReceiptNotBuilt(ValueError):
    """A receipt was assembled with a field that is not a state and value pair, or a missing one.

    `problems` names each field refused, as "<group>: field <name>: <why>".
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def build_receipt(decision: Mapping[str, object], facts: ReceiptFacts) -> Receipt:
    """Build the receipt from the decision and the facts gathered. Every field is a pair.

    Raises ReceiptNotBuilt when any field is not a pair of a state and a value (a bare string
    where a pair belongs, from a step or a driver), or a field is missing.

    facts: receipt_id, execution_version, host, input_hash, launched, started_at,
    ended_at, executor_duration, exit_code, signal, executor_driver_observations (None
    when the observation failed or never happened), stand_ins (step name to
    result; a step not reached is absent), reason_text.
    """
    receipt = _assemble(decision, facts)
    problems = check_receipt(receipt)
    if problems:
        raise ReceiptNotBuilt(problems)
    return receipt


def _assemble(decision: Mapping[str, object], facts: ReceiptFacts) -> Receipt:
    steps = facts["stand_ins"]
    launched = facts["launched"]
    reason = facts.get("reason_text")
    if reason is None:
        reason = fixed.NONE if decision["reason"] == fixed.NONE else fixed.CANNOT_TELL
    observed = facts.get("executor_driver_observations")
    boundary = steps.get("boundary")
    # A step the run never reached looked at nothing: "none".
    unlooked = pairs.none()

    ending: EndingGroup = {
        "ending": pairs.of_text(_text_of(decision, "ending")),
        "reason": pairs.of_text(_text_of(decision, "reason")),
        "failed_step": pairs.of_text(_text_of(decision, "failed_step")),
        "reason_text": pairs.of_text(reason),
        "receipt_id": pairs.observed(facts["receipt_id"]),
        "everything_stopped": _from_step(steps.get("stop_confirmation"), "everything_stopped"),
    }
    saw: ExecutionGroup = {
        "execution_version": pairs.observed(facts["execution_version"]),
        "host": pairs.observed(facts["host"]),
        "started_at": pairs.observed(facts["started_at"]),
        "ended_at": pairs.observed(facts["ended_at"]),
        # The runtime is observed through the boundary, which is a stand-in.
        "observed_runtime": pairs.not_built() if launched else unlooked,
        "duration_gates_seconds": _from_step(steps.get("gates"), "duration_seconds"),
        "duration_opening_freeze_seconds": _from_step(
            steps.get("opening_fingerprint"), "duration_seconds"
        ),
        "duration_executor_seconds": pairs.observed(facts["executor_duration"]),
        "duration_closing_freeze_seconds": _from_step(
            steps.get("closing_freeze"), "duration_seconds"
        ),
        "duration_delivery_seconds": _from_step(steps.get("delivery"), "duration_seconds"),
        "input_hash": pairs.cannot_tell()
        if facts["input_hash"] is None
        else pairs.observed(facts["input_hash"]),
        "reference_hashes": pairs.observed(facts.get("reference_hashes", {})),
        "fingerprint_before": _from_step(steps.get("opening_fingerprint"), "fingerprint"),
        "fingerprint_after": _from_step(steps.get("closing_freeze"), "fingerprint"),
        "changed_nothing": _changed_nothing(steps),
        "files_added": _from_step(steps.get("closing_freeze"), "files_added"),
        "files_changed": _from_step(steps.get("closing_freeze"), "files_changed"),
        "files_deleted": _from_step(steps.get("closing_freeze"), "files_deleted"),
        "files_list_kept_file": _files_list(steps.get("kept_files")),
        "delivered": _from_step(steps.get("delivery"), "delivered"),
        "delivery_branch": _from_step(steps.get("delivery"), "branch"),
        "delivery_branch_reason": _from_step(steps.get("delivery"), "branch_reason"),
        "exit_code": pairs.observed(facts["exit_code"]),
        "signal": pairs.cannot_tell()
        if facts["signal"] == fixed.CANNOT_TELL
        else pairs.observed(facts["signal"]),
        "peak_memory_bytes": _from_step(boundary, "peak_memory_bytes") if launched else unlooked,
        "processor_time_seconds": _from_step(boundary, "processor_time_seconds")
        if launched
        else unlooked,
        "session_file_kept_at": _from_step(steps.get("kept_files"), "session_file"),
        "teardown_failure": _from_step(steps.get("teardown"), "failure"),
        "stop_reason": _from_step(steps.get("stop_confirmation"), "stop_reason"),
        "stop_asker": _from_step(steps.get("stop_confirmation"), "stop_asker"),
    }
    driver = (
        observed
        if observed is not None
        else _driver_group_of(pairs.cannot_tell() if launched else unlooked)
    )
    return {
        "ending": ending,
        "execution": saw,
        "executor_driver": driver,
        "executor": _executor_group_of(steps, launched),
    }


def verified_reference_hashes(raw: object, input_check: str | None) -> dict[str, str]:
    """The hash of each reference by name, when the input checks passed and so found each file
    to hold the hash the document gave; empty when a check refused the run, or there are none."""
    if input_check or not isinstance(raw, dict):
        return {}
    return {reference["name"]: reference["hash"] for reference in raw.get("references", [])}


def _text_of(decision: Mapping[str, object], key: str) -> str:
    value = decision[key]
    return value if isinstance(value, str) else fixed.CANNOT_TELL


def minimal_receipt(decision: Mapping[str, object]) -> Receipt:
    """The receipt when building the full one failed: the decision, and "cannot tell" for everything else."""
    unknown = pairs.cannot_tell()
    ending: EndingGroup = {
        "ending": pairs.of_text(_text_of(decision, "ending")),
        "reason": pairs.of_text(_text_of(decision, "reason")),
        "failed_step": pairs.of_text(_text_of(decision, "failed_step")),
        "reason_text": unknown,
        "receipt_id": unknown,
        "everything_stopped": unknown,
    }
    return {
        "ending": ending,
        "execution": _execution_group_of(unknown),
        "executor_driver": _driver_group_of(unknown),
        "executor": _executor_group_all(unknown),
    }


# The ending group's own "nothing" and "cannot tell" are states, never the word held as a value.
_FIELDS_THAT_SAY_IT_BY_STATE = ("ending", "reason", "failed_step", "reason_text")


def _state_words_held_as_values(ending: Mapping[str, object]) -> list[str]:
    problems = []
    for name in _FIELDS_THAT_SAY_IT_BY_STATE:
        held = ending.get(name)
        if (
            isinstance(held, dict)
            and held.get("state") == fixed.VALUE
            and held.get("value") in (fixed.NONE, fixed.CANNOT_TELL, fixed.NOT_BUILT)
        ):
            problems.append(
                f"ending: field {name} holds the word {held['value']!r} as a value; "
                "that is said by the state"
            )
    return problems


def check_receipt(receipt: Mapping[str, object]) -> list[str]:
    """Problems with a receipt as read back (or built), judged against the fixed list. Empty when fine."""
    problems = []
    if set(receipt) != set(fixed.RECEIPT_GROUPS):
        return [f"the receipt's groups are {sorted(receipt)}"]
    for group, names in fixed.RECEIPT_GROUPS.items():
        held = receipt[group]
        if not isinstance(held, Mapping):
            problems.append(f"{group}: is not a group of fields")
            continue
        for name in sorted(set(names) - set(held)):
            problems.append(f"{group}: field {name} is missing")
        for name in sorted(set(held) - set(names)):
            problems.append(f"{group}: field {name} is not on the list")
        for name in names:
            problem = pairs.problem_with(held[name]) if name in held else None
            if problem:
                problems.append(f"{group}: field {name}: {problem}")
    ending = receipt["ending"]
    if isinstance(ending, Mapping):
        problems += _state_words_held_as_values(ending)
    if isinstance(ending, Mapping) and all(
        k in ending for k in ("ending", "reason", "failed_step")
    ):
        problems += check_decision(
            {k: pairs.text_of(ending[k]) for k in ("ending", "reason", "failed_step")}
        )
    return problems
