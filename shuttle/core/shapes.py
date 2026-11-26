"""The shapes of the plain data that passes between the core and the shell, and of the operations.

Types only; nothing here runs. Every shape the code knows is a typed record, so a missing or
misnamed field fails the strict type check. Two shapes stay loosely typed because they arrive from
outside and are checked by value: `Document` (the input document as read from JSON, shape unknown
until the validation code has looked at it) and what `records.read_record` reads back from disk.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, NamedTuple, TextIO, TypedDict

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

# Arrives from outside: checked by value (decisions.validate_document), never trusted by type.
Document = dict[str, Any]


class Decision(TypedDict):
    ending: str
    reason: str
    failed_step: str


class Refusal(TypedDict):
    reason: str
    step: str


class HeaderSource(TypedDict):
    """What a header is formed from: the document's identifying parts."""

    request_id: str
    records_location: str
    thread: str
    round: int
    kind: str
    parent_session: str
    asked_by: str
    executor_name: str


class DocumentCheck(TypedDict):
    header_source: HeaderSource | None
    refusal: Refusal | None
    problem: str | None


class RecordHeader(TypedDict):
    record_id: str
    record_type: str
    time: str
    request_id: str
    thread: str
    round: int
    parent_session: str
    asked_by: str
    kind: str
    executor_name: str
    format_version: int


# Functional form: the key is called "input", a name the core may not mention in code.
RequestRecord = TypedDict(  # noqa: UP013 (the class form would name a field `input`)
    "RequestRecord", {"header": RecordHeader, "input": Document}
)


class Conclusion(TypedDict):
    stdout: list[str]
    stderr: list[str]
    exit: int


class Outcome(TypedDict, total=False):
    """How the last step went, as `decisions.conclude` reads it."""

    kind: str
    decision: Decision
    path: str
    receipt_text: str
    problem: str | None


class CommandSettings(TypedDict):
    """The command driver's settings, once the document is checked."""

    command: str
    arguments: list[str]


class LaunchSpec(TypedDict):
    argv: list[str]


class StepResult(TypedDict, total=False):
    """What a step returns. A stand-in is marked with `stand_in`; a real step reports `ok`."""

    stand_in: str
    process: Any  # the handle the process operations made; nothing else looks inside
    ok: bool


class Facts(TypedDict, total=False):
    """What the steps of a run left for the decisions. A step that did not run has no fact."""

    unreadable: bool
    header_source: HeaderSource | None
    id_claim: str
    input_check: str
    executor_driver_check: str
    gates: str
    setup: str
    opening_freeze: str
    launch: str
    wait: str
    stop: str
    closing_freeze: str
    delivery: str
    exit_code: int | None
    child_signal: str | None


# ------------------------------------------------------------------ the receipt


class Pair(TypedDict):
    """One receipt field: how the value is known (a state in `fixed.STATES`), and the value."""

    state: str
    value: JsonValue  # None unless the state is "value"


class EndingGroup(TypedDict):
    ending: Pair
    reason: Pair
    failed_step: Pair
    reason_text: Pair
    receipt_id: Pair
    everything_stopped: Pair


class ExecutionGroup(TypedDict):
    execution_version: Pair
    host: Pair
    started_at: Pair
    ended_at: Pair
    observed_runtime: Pair
    duration_gates_seconds: Pair
    duration_opening_freeze_seconds: Pair
    duration_executor_seconds: Pair
    duration_closing_freeze_seconds: Pair
    duration_delivery_seconds: Pair
    input_hash: Pair
    reference_hashes: Pair
    fingerprint_before: Pair
    fingerprint_after: Pair
    changed_nothing: Pair
    files_added: Pair
    files_changed: Pair
    files_deleted: Pair
    files_list_kept_file: Pair
    delivered: Pair
    delivery_branch: Pair
    delivery_branch_reason: Pair
    exit_code: Pair
    signal: Pair
    peak_memory_bytes: Pair
    processor_time_seconds: Pair
    session_file_kept_at: Pair
    teardown_failure: Pair
    stop_reason: Pair
    stop_asker: Pair


class ExecutorDriverGroup(TypedDict):
    executor_driver_name: Pair
    executor_driver_version: Pair
    tool_version: Pair
    model: Pair
    effort: Pair
    tokens_in: Pair
    tokens_out: Pair
    tokens_cached: Pair
    activity: Pair
    session_id: Pair
    refused_actions: Pair
    quota_level: Pair
    vendor_limit_reached: Pair
    vendor_limit_reset: Pair
    tool_made_own_commits: Pair
    load_lists_differ: Pair
    load_lists_kept_file: Pair
    changed_self_loaded_file: Pair
    waiting_question: Pair


class ExecutorGroup(TypedDict):
    statement_state: Pair
    statement_hash: Pair
    statement_location: Pair
    claim: Pair


class Receipt(TypedDict):
    ending: EndingGroup
    execution: ExecutionGroup
    executor_driver: ExecutorDriverGroup
    executor: ExecutorGroup


class ReceiptFacts(TypedDict):
    """What `decisions.build_receipt` is handed besides the decision."""

    receipt_id: str
    execution_version: str
    host: str
    input_hash: str | None
    launched: bool
    started_at: str | None
    ended_at: str | None
    executor_duration: float | None
    exit_code: int | None
    signal: str | None
    # None when observing failed or never happened
    executor_driver_observations: ExecutorDriverGroup | None
    stand_ins: dict[str, StepResult]  # step name to result; a step not reached is absent
    reason_text: str | None


class OutcomeRecord(TypedDict):
    header: RecordHeader
    receipt: Receipt


class RunState(TypedDict, total=False):
    """The shell's state of one run, built up step by step."""

    document_path: str
    out: TextIO
    err: TextIO
    world: "Operations"
    facts: Facts
    stand_ins: dict[str, StepResult]
    problems: dict[str, str]
    problem: str
    signal: str | None
    raw: Document
    input_hash: str
    started_at: str
    ended_at: str
    clock_start: float
    executor_duration: float
    executor_driver_observations: ExecutorDriverGroup
    conclusion: Conclusion


# ------------------------------------------------------------------ the operations
#
# Everything Shuttle does to the world goes through these. The shell is handed one
# `Operations` and calls its fields; the real set lives in shuttle/world/, and a test passes
# a stand-in. Each group is an immutable record (a named tuple: it is imported on every start of
# the command, and a dataclass costs about 9 ms of that) whose fields are plain functions,
# grouped by what they touch. A field that can fail raises what the real call raises (the notes
# say which).

Process = Any  # a handle the process operations made and understand; nothing else looks inside


class FileOperations(NamedTuple):
    """Files, by name. Text is UTF-8."""

    read: Callable[[str], bytes]  # raises OSError (FileNotFoundError, IsADirectoryError, ...)
    exists: Callable[[str], bool]  # a name is there, even if it leads nowhere
    write_new: Callable[[str, str], None]  # create, write, flush to disk; FileExistsError if there
    link: Callable[[str, str], None]  # (existing name, new name); FileExistsError if new is there
    remove: Callable[[str], None]  # FileNotFoundError when there is no such name


class ProcessOperations(NamedTuple):
    """Child processes. The handle is whatever `start` returns."""

    find_program: Callable[[str], bool]  # whether a command can be found and run
    start: Callable[
        [Sequence[str], Mapping[str, str]], Process
    ]  # argv, environment; OSError, ValueError
    poll: Callable[[Process], int | None]  # None while running; negative: ended by that signal
    ask_to_end: Callable[
        [Process], None
    ]  # the polite request (SIGTERM); OSError if it cannot be sent
    kill: Callable[[Process], None]  # the one that cannot be ignored; OSError if it cannot be sent


class ClockOperations(NamedTuple):
    """Time: a steady count of seconds, a stamp for records, and waiting."""

    now: Callable[[], float]  # seconds on a clock that only goes forward
    timestamp: Callable[[], str]  # UTC, ISO 8601, milliseconds, for records
    wait: Callable[[float], None]  # let that many seconds pass


class SignalOperations(NamedTuple):
    """The signals that ask the run itself to stop."""

    install: Callable[
        [Callable[[str], None]], Callable[[], None]
    ]  # handler gets the signal's name; returns the undo
    name_of: Callable[[int], str | None]  # a signal number's name, None if there is no such signal


class EnvironmentOperations(NamedTuple):
    read_variable: Callable[[str], str | None]  # None when the variable is not set


class IdentityOperations(NamedTuple):
    host_name: Callable[[], str]
    new_id: Callable[[], str]  # a fresh id: 32 lower-case hex digits, never the same twice
    process_number: Callable[[], int]  # this process's number, as the system gives it


class Operations(NamedTuple):
    """The world, as one set of operations."""

    files: FileOperations
    processes: ProcessOperations
    clock: ClockOperations
    signals: SignalOperations
    environment: EnvironmentOperations
    identity: IdentityOperations
