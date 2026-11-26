"""The shapes of the plain data that passes between the core and the shell.

Types only; nothing here runs. Where a shape is known it is a typed record.
Where it still varies (the facts of a run, the receipt, the shell's state) it is a
dictionary of anything, and is listed in the pull request as loosely typed.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, NamedTuple, TypedDict

# Loosely typed for now: the facts of a run, the receipt and its groups, a step's
# result, the document as read from JSON, and the shell's state of a run.
Facts = dict[str, Any]
Receipt = dict[str, dict[str, Any]]
StepResult = dict[str, Any]
Document = dict[str, Any]
State = dict[str, Any]
HeaderSource = dict[str, Any]


class Decision(TypedDict):
    ending: str
    reason: str
    failed_step: str


class DocumentCheck(TypedDict):
    header_source: HeaderSource | None
    refusal: dict[str, str] | None
    problem: str | None


class Conclusion(TypedDict):
    stdout: list[str]
    stderr: list[str]
    exit: int


class LaunchSpec(TypedDict):
    argv: list[str]


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
    new_id: Callable[[], str]  # a fresh id: letters and digits only, never the same twice


class Operations(NamedTuple):
    """The world, as one set of operations."""

    files: FileOperations
    processes: ProcessOperations
    clock: ClockOperations
    signals: SignalOperations
    environment: EnvironmentOperations
    identity: IdentityOperations
