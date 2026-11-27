"""The shapes of the plain data that passes between the core and the shell, and of the operations.

Types only; nothing here runs. Every shape the code knows is a typed record, so a missing or
misnamed field fails the strict type check. Two shapes stay loosely typed because they arrive from
outside and are checked by value: `Document` (the input document as read from JSON, shape unknown
until the validation code has looked at it) and what `records.read_record` reads back from disk.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any, Literal, NamedTuple, NotRequired, Protocol, TextIO, TypedDict

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
    record_version: int


# Functional form: the key is called "input", a name the core may not mention in code.
# The input is the exact text the caller gave, so its hash can be checked from the record alone.
RequestRecord = TypedDict(  # noqa: UP013 (the class form would name a field `input`)
    "RequestRecord", {"header": RecordHeader, "input": str}
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


# An executor driver's own settings, as the document gave them; each driver's check says what
# it holds (the table of drivers is shuttle.core.drivers.table).
Settings = dict[str, Any]


class LaunchSpec(TypedDict):
    argv: list[str]
    output_to: NotRequired[str]  # a file made new for the child's standard output, in the run area


class DriverFacts(TypedDict):
    """What the shell found out for a driver's check; the driver's check reads these with the settings."""

    tool_found: bool
    login_found: bool  # whether the name `login_path` gave is there; the login is never opened
    network: bool | None  # the document's standard settings; None when it gave none
    changes_allowed: bool | None


class LaunchContext(TypedDict):
    """What a driver's launch command is built from besides its settings."""

    place: str
    run_area: str
    network: bool
    changes_allowed: bool


class OutputFiles(TypedDict, total=False):
    """Where a driver's tool leaves what the shell hands back to `observe`, whole paths."""

    events: str
    last_message: str


# One line of a saved file, as `FileOperations.read_lines` gives it: the bytes, and whether the
# line was longer than the limit and so cut.
Line = tuple[bytes, bool]


class SavedOutput(TypedDict):
    """What the tool left, each a single pass over its lines, or None when it is not available."""

    events: Iterable[Line] | None
    last_message: Iterable[Line] | None
    session_record: Iterable[Line] | None


class Observed(TypedDict):
    group: "ExecutorDriverGroup"
    # The tool left a final message file with at least one line, blank ones included.
    reply_given: bool


# How a driver's tool hands over its statement: it writes a file at the statement path in the run area, or its
# final message is the statement.
StatementArrival = Literal["file", "reply"]
SetupAction = Literal["copy", "share", "leave_out", "write", "writable", "variable"]
SetupStepKind = Literal["folder", "copy", "share", "write", "writable"]


class SetupRequest(TypedDict, total=False):
    """One thing a driver asks of the run area (shuttle.core.run_area). `action` says which; the
    other fields are those that action reads: `name` (the path made, or acted on, inside the
    area), `source` (the absolute path a copy or share comes from), `text` (a written file's),
    and for a variable, `variable` with either `value` or `in_run_area` (the name whose path is
    the value). A copy may be `optional`."""

    action: SetupAction
    name: str
    source: str
    text: str
    variable: str
    value: str
    in_run_area: str
    optional: bool  # a copy only: left out, not an error, when its source is not there


class SetupStep(TypedDict, total=False):
    """What the shell does for one request, with every path whole."""

    do: SetupStepKind
    source: str
    target: str
    leave_out: list[str]  # for a copy: names relative to the source
    optional: bool  # for a copy: present (true) only when the request said so
    text: str


class SetupPlan(TypedDict):
    steps: list[SetupStep]
    variables: dict[str, str]  # passed to the executor, by name
    problem: str | None  # why the requests were refused, or None


class StepResult(TypedDict, total=False):
    """What a step returns. A stand-in is marked with `stand_in`; a real step reports `ok`."""

    stand_in: str
    process: Any  # the handle the process operations made; nothing else looks inside
    ok: bool
    fingerprint: str  # a freeze: the commit that stands for the place's files
    files_added: int
    files_changed: int
    files_deleted: int
    problem: str  # a real step that failed says what was not done and why
    everything_stopped: bool
    stop_reason: str
    stop_asker: str
    duration_seconds: float  # a real step that took time says how much
    # what the step that moves kept files found; a key left out reads "cannot tell", "" reads "none"
    statement_state: str
    statement_hash: str
    statement_location: str
    claim: str
    session_file: str
    failure: str  # a tear-down that failed says how; "" reads "none"


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
    # name to hash of each reference execution checked before the start; empty when it did not
    reference_hashes: NotRequired[dict[str, str]]


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
    input_text: str
    input_hash: str
    started_at: str
    ended_at: str
    clock_start: float
    run_part: str
    boundary_name: str
    boundary_process: Any
    run_area: str  # the run's own folder, once made
    setup_variables: dict[str, str]  # what the driver's setup passes to the executor
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


class NotARegularFile(OSError):
    """The name holds a link, a named pipe, a device, a socket or anything else that is not a
    regular file (a folder raises IsADirectoryError instead). Both worlds raise it, by this
    class, so the shell can tell "not a file" from a look that failed."""


class FileOperations(NamedTuple):
    """Files, by name. Text is UTF-8."""

    read: Callable[[str], bytes]  # a regular file, or a link to one; raises OSError
    # (FileNotFoundError, IsADirectoryError, NotARegularFile for a pipe, a device, a socket, a
    # link to one of those), and never waits on what is there
    # read_lines: (name, limit): the same file as `read`, handed back a line at a time so what is
    # held never grows with the file. Each line is its bytes without the line's end, at most
    # `limit` of them, and whether it was cut: a longer line gives its first `limit` bytes and
    # True, and the rest of it is skipped, never held. A file that ends without a line end gives
    # its last line as it is; an empty file gives none. Raises, when called, as `read` does
    read_lines: Callable[[str, int], Iterator[tuple[bytes, bool]]]
    exists: Callable[[str], bool]  # a name is there, even if it leads nowhere
    write_new: Callable[[str, str], None]  # create, write, flush to disk; FileExistsError if there
    link: Callable[[str, str], None]  # (existing name, new name); FileExistsError if new is there
    copy: Callable[
        [str, str], None
    ]  # (existing name, new name): the same bytes, flushed; FileExistsError if new is there,
    # FileNotFoundError if existing is not, IsADirectoryError if existing is a folder,
    # NotARegularFile if existing is a link (to anything, a missing name too), a pipe, a device
    # or a socket: a link is never followed and nothing waits on what is there. At most the
    # size seen when it opened is copied. Nothing is left under the new name when it raises
    hash: Callable[
        [str], str
    ]  # the sha256 of the file's bytes, as 64 lower-case hex digits; raises as read
    remove: Callable[[str], None]  # FileNotFoundError when there is no such name
    usable_folder: Callable[
        [str], bool
    ]  # a folder a new name can be made in; looks, writes nothing
    # The run area (shuttle.core.run_area). None of these reads a file's content except
    # `copy_path`, which copies the bytes without looking at them, and none follows a link
    # except `share_by_link`, which makes one.
    make_temporary_folder: Callable[
        [str], str
    ]  # (name prefix): a new, empty folder only its owner can enter, in the system's temporary place; the path, absolute. OSError
    make_folders: Callable[
        [str], None
    ]  # the folder and any missing folder above it; nothing if it is there; OSError (FileExistsError if the name is a file)
    copy_path: Callable[
        [str, str, Sequence[str]], None
    ]  # (existing, new, left out): a regular file as `copy` does, or a folder with everything below
    # it that is a regular file or a folder (a link, a pipe, a device or a socket below is skipped,
    # never followed or opened) except the names left out, which are relative to `existing`
    # ("a/b" leaves out that file or folder). FileExistsError if new is there, FileNotFoundError if
    # existing is not or the folder above new is not, NotARegularFile if existing itself is a link,
    # a pipe, a device or a socket. Nothing is left under the new name when it raises
    share_by_link: Callable[
        [str, str], None
    ]  # (existing, new): a symbolic link at new leading to existing, which is looked at (not
    # opened) and must be there: FileNotFoundError otherwise; FileExistsError if new is there
    make_writable: Callable[
        [str], None
    ]  # the owner may write a regular file, and a folder with everything below it; a link is
    # never followed: NotARegularFile for one at the name itself, a link below is left as it is;
    # FileNotFoundError when nothing is there
    remove_tree: Callable[
        [str], None
    ]  # a folder and everything in it, read-only parts too; a link inside is removed, never
    # followed; FileNotFoundError when nothing is there, NotADirectoryError for a name that is not a folder


class Starter(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        environment: Mapping[str, str],
        report: int | None = None,
        input_from: str | None = None,
        output_to: str | None = None,
    ) -> Process: ...


class ProcessOperations(NamedTuple):
    """Child processes. The handle is whatever `start` returns."""

    find_program: Callable[[str], bool]  # whether a command can be found and run
    # start: argv, environment, the number `open_report` gave or None, and the name of a file the
    # child reads as its standard input (None: nothing to read, the null device). The file is
    # opened before anything starts: FileNotFoundError and nothing started when it is not there.
    # `output_to` is a name made new for the child's standard output (None: the null device):
    # FileExistsError, or FileNotFoundError when the folder above it is not there, and nothing
    # started. OSError, ValueError
    start: Starter
    poll: Callable[[Process], int | None]  # None while running; negative: ended by that signal
    wait: Callable[
        [Process, float], int | None
    ]  # blocks up to that many seconds for the exit; the status, or None if still running
    open_report: Callable[
        [], int
    ]  # a report channel for one start: the number the child sees its write end as; OSError
    read_report: Callable[
        [Process], str
    ]  # what the child wrote to its report so far (nothing if it had none); never waits


class BoundaryOperations(NamedTuple):
    """The boundary's scope, by its unit name (shuttle.core.boundary.unit_of)."""

    show: Callable[
        [str, Sequence[str]], Mapping[str, str]
    ]  # the named properties of the unit; OSError when they cannot be read
    stop: Callable[
        [str], None
    ]  # stop the unit and everything in it; OSError when it cannot be asked
    forget: Callable[[str], None]  # clear a failed unit's record; OSError when it cannot be asked
    resolve: Callable[
        [str], str
    ]  # a path made absolute with links resolved, as the boundary sees it


class ClockOperations(NamedTuple):
    """Time: a steady count of seconds for durations, and a stamp for records."""

    now: Callable[[], float]  # seconds on a clock that only goes forward
    timestamp: Callable[[], str]  # UTC, ISO 8601, milliseconds, for records


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


class PlaceFacts(TypedDict):
    """What looking at a place found. A place that is not there, or not a git checkout, has no
    commit, nothing unclean and nothing nested."""

    exists: bool  # a folder is there
    is_checkout: bool  # the folder is the top of a git working copy
    head: str | None  # the commit the checkout is at; None when it has none
    unclean: list[str]  # names git reports as changed, or new and not ignored
    nested: list[str]  # folders, below the top, that hold a git repository of their own
    filtered: list[str]  # tracked paths with a `filter` attribute; when any, git looked no further


class FreezeAnswer(NamedTuple):
    """How the freeze's command ended: its exit status (negative: ended by that signal) and what
    it wrote to standard output."""

    status: int
    output: bytes


class GitOperations(NamedTuple):
    """The place's repository. Every call is made with exactly the environment it is given (so
    nothing of the caller's git configuration is read), reads its input from nowhere and never
    asks a question."""

    look_at_place: Callable[
        [str, Mapping[str, str]], PlaceFacts
    ]  # (place, environment); looks only, changes nothing there, not even the index; OSError when git cannot answer
    freeze: Callable[
        [Sequence[str], Mapping[str, str]], FreezeAnswer
    ]  # (command, environment): run the freeze's command to its end; OSError when it cannot be started


class Operations(NamedTuple):
    """The world, as one set of operations."""

    files: FileOperations
    processes: ProcessOperations
    boundary: BoundaryOperations
    clock: ClockOperations
    signals: SignalOperations
    environment: EnvironmentOperations
    identity: IdentityOperations
    git: GitOperations
