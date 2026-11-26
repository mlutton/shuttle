"""The shapes of the plain data that passes between the core and the shell.

Types only; nothing here runs. Where a shape is known it is a typed record.
Where it still varies (the facts of a run, the receipt, the shell's state) it is a
dictionary of anything, and is listed in the pull request as loosely typed.
"""

from typing import Any, TypedDict

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
