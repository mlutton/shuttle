"""The run area: the run's own folder, and the plan for what a driver asks to be set up in it.

A driver says what its tool needs, as data. This module turns those requests into a plan of
whole paths, or says why they are refused; the shell acts on the plan through the world's
operations. Nothing here touches the world.

What an action means is one block (a subclass of `_Action`: its fields' shape check and the
steps it becomes), found by name in `ACTIONS`. The rules that hold between requests are in
`plan`, which calls the blocks.

Why the refusals are what they are: a name is plain and relative so nothing a request names can
be outside the area; a source is only handed on, never split or quoted; a shared path is linked,
never copied or read, so a name under it is refused, since a write there would land in the
original.
"""

import re
from collections.abc import Sequence
from typing import Literal, cast

from shuttle.core import boundary, fixed
from shuttle.core.shapes import SetupAction, SetupPlan, SetupRequest, SetupStep

# The folder the run area is made in, by this name followed by what the system adds.
AREA_PREFIX = "shuttle-run-area-"
# Where the instruction is put for the executor's standard input; no request may name it.
INSTRUCTION_NAME = "shuttle-instruction.txt"
# Where the executor writes its statement: the one name Shuttle fixes inside the run area, so the
# document's own statement location is never shown to the executor. No request may name it.
STATEMENT_NAME = "shuttle-statement.json"
_KEPT_NAMES = (INSTRUCTION_NAME, STATEMENT_NAME)

_PART = r"(?!\.{1,2}(?:/|$))[A-Za-z0-9._-]+"
_NAME = re.compile(f"{_PART}(?:/{_PART})*")
# The variables the shell and the boundary handle themselves, and the prefix of those that change
# how a program starts (the dynamic loader's): no request may pass one.
_OWN_VARIABLES = ("PATH", *boundary.BUS_VARIABLES)
_LOADER_PREFIX = "LD_"


def valid_name(name: object) -> bool:
    return isinstance(name, str) and len(name) <= 200 and _NAME.fullmatch(name) is not None


def valid_source(source: object) -> bool:
    return isinstance(source, str) and source.startswith("/") and "\0" not in source


def _under(name: str, folder: str) -> bool:
    return name.startswith(folder + "/")


def _inside(area: str, name: str) -> str:
    return area + "/" + name


def statement_path(area: str) -> str:
    """The path inside the run area where the executor writes its statement."""
    return _inside(area, STATEMENT_NAME)


def _refused(why: str) -> SetupPlan:
    return {"steps": [], "variables": {}, "problem": why}


def _name_problem(index: int, request: SetupRequest, field: str = "name") -> str | None:
    if not valid_name(request.get(field)):
        return (
            f"setup request {index + 1} ({request['action']}): {field} is not a name inside the "
            "run area (letters, digits, '.', '_' and '-', parts joined by '/', no '.' or '..' part)"
        )
    name = str(request.get(field))
    for kept in _KEPT_NAMES:
        if name == kept or _under(name, kept):
            return (
                f"setup request {index + 1}: the name {kept!r} and anything below it are "
                "kept for the instruction and the statement"
            )
    return None


class _Action:
    """What one setup action is: how its request is checked, and what it becomes.

    `role` picks the rule between requests the flow applies to it: a path made is made once and
    never under a shared one; a path edited was made by an earlier request; a variable is passed
    once; a name left out applies to every copy that holds it.
    """

    role: Literal["makes", "edits", "passes", "leaves_out"]

    def shape_problem(self, index: int, request: SetupRequest) -> str | None:
        """Why the request's fields are not this action's, or None."""
        return _name_problem(index, request)

    def steps(self, request: SetupRequest, area: str, leave_out: Sequence[str]) -> list[SetupStep]:
        """What the shell does for it; `leave_out` is every name left out of any copy."""
        return []

    def variables(self, request: SetupRequest, area: str) -> dict[str, str]:
        """The variable it passes to the executor, by name."""
        return {}

    def required_source(self, request: SetupRequest) -> str | None:
        """The path outside the area that the run's set-up fails without, or None."""
        return None


def _folder_above(name: str, area: str) -> list[SetupStep]:
    above = name.rpartition("/")[0]
    return [{"do": "folder", "target": _inside(area, above)}] if above else []


class _Sourced(_Action):
    """What a copy and a share have in common: a name made from an absolute source."""

    role = "makes"

    def shape_problem(self, index: int, request: SetupRequest) -> str | None:
        return _name_problem(index, request) or (
            None
            if valid_source(request.get("source"))
            else f"setup request {index + 1} ({request['action']}): source is not an absolute path"
        )


class _Copy(_Sourced):
    def shape_problem(self, index: int, request: SetupRequest) -> str | None:
        return super().shape_problem(index, request) or (
            None
            if isinstance(request.get("optional", False), bool)
            else f"setup request {index + 1} (copy): optional is not true or false"
        )

    def steps(self, request: SetupRequest, area: str, leave_out: Sequence[str]) -> list[SetupStep]:
        name = request["name"]
        copy: SetupStep = {
            "do": "copy",
            "source": request["source"],
            "target": _inside(area, name),
            "leave_out": _left_out_of(name, leave_out),
        }
        if request.get("optional"):
            copy["optional"] = True
        return [*_folder_above(name, area), copy]

    def required_source(self, request: SetupRequest) -> str | None:
        return None if request.get("optional") else request["source"]


class _Share(_Sourced):
    def required_source(self, request: SetupRequest) -> str | None:
        return request["source"]

    def steps(self, request: SetupRequest, area: str, leave_out: Sequence[str]) -> list[SetupStep]:
        name = request["name"]
        return [
            *_folder_above(name, area),
            {"do": "share", "source": request["source"], "target": _inside(area, name)},
        ]


class _LeaveOut(_Action):
    role = "leaves_out"


class _Write(_Action):
    role = "makes"

    def shape_problem(self, index: int, request: SetupRequest) -> str | None:
        return _name_problem(index, request) or (
            None
            if isinstance(request.get("text"), str)
            else f"setup request {index + 1} (write): text is missing"
        )

    def steps(self, request: SetupRequest, area: str, leave_out: Sequence[str]) -> list[SetupStep]:
        name = request["name"]
        return [
            *_folder_above(name, area),
            {"do": "write", "target": _inside(area, name), "text": request["text"]},
        ]


class _Writable(_Action):
    role = "edits"

    def steps(self, request: SetupRequest, area: str, leave_out: Sequence[str]) -> list[SetupStep]:
        return [{"do": "writable", "target": _inside(area, request["name"])}]


class _Variable(_Action):
    role = "passes"

    def shape_problem(self, index: int, request: SetupRequest) -> str | None:
        name = request.get("variable")
        if (
            not isinstance(name, str)
            or not name
            or any(c not in fixed.ID_CHARACTERS for c in name)
            or name in _OWN_VARIABLES
            or name.startswith(_LOADER_PREFIX)
        ):
            return f"setup request {index + 1} (variable): the variable's name is not usable"
        if ("value" in request) == ("in_run_area" in request):
            return (
                f"setup request {index + 1} (variable): give exactly one of value and in_run_area"
            )
        if "value" in request and not isinstance(request["value"], str):
            return f"setup request {index + 1} (variable): value is not text"
        if "in_run_area" in request:
            return _name_problem(index, request, "in_run_area")
        return None

    def variables(self, request: SetupRequest, area: str) -> dict[str, str]:
        value = request.get("value") or _inside(area, request.get("in_run_area", ""))
        return {request["variable"]: value}


# From an action's name to its block. A new action also needs its name in `SetupAction` and its
# fields in `SetupRequest` (shapes.py), a step kind and a case in the shell's `match` only if it
# does something no step does, and a role only if it follows a rule no role has. A test fails
# for a name in `SetupAction` with no entry here.
ACTIONS: dict[SetupAction, _Action] = {
    "copy": _Copy(),
    "share": _Share(),
    "leave_out": _LeaveOut(),
    "write": _Write(),
    "writable": _Writable(),
    "variable": _Variable(),
}


def _shape_problem(index: int, request: object) -> str | None:
    """Why one request is not one of the actions, or None."""
    action = request.get("action") if isinstance(request, dict) else None
    if not isinstance(action, str) or action not in ACTIONS:
        return f"setup request {index + 1} is not one of: {', '.join(ACTIONS)}"
    return ACTIONS[cast(SetupAction, action)].shape_problem(index, cast(SetupRequest, request))


def _taken_problem(index: int, request: SetupRequest, made: dict[str, str]) -> str | None:
    """Why the name of a copy, share or write cannot be made now, or None."""
    name = request["name"]
    if name in made:
        return f"setup request {index + 1}: {name!r} is made twice"
    for earlier, how in made.items():
        if how == "share" and _under(name, earlier):
            return (
                f"setup request {index + 1}: {name!r} is under {earlier!r}, which is shared in "
                "place; anything made there would land in the original"
            )
    return None


def _writable_problem(index: int, request: SetupRequest, made: dict[str, str]) -> str | None:
    name = request["name"]
    for earlier, how in made.items():
        if how == "share" and (name == earlier or _under(name, earlier)):
            return (
                f"setup request {index + 1}: {name!r} is shared in place and is not made writable"
            )
    if name in made or any(_under(name, e) for e, how in made.items() if how == "copy"):
        return None
    return f"setup request {index + 1}: {name!r} was not made by an earlier request"


def _left_out_of(target: str, leave_out: Sequence[str]) -> list[str]:
    return [name[len(target) + 1 :] for name in leave_out if _under(name, target)]


def _leave_out_problem(leave_out: Sequence[str], copies: Sequence[str]) -> str | None:
    for name in leave_out:
        if not any(_under(name, copy) for copy in copies):
            return f"{name!r} is left out, and no copy holds it"
    return None


def _is_made(name: str, made: dict[str, str]) -> bool:
    """Whether some request makes this name, or a path through it."""
    return any(
        name == n or _under(n, name) or (how == "copy" and _under(name, n))
        for n, how in made.items()
    )


def _variable_path_problem(requests: Sequence[SetupRequest], made: dict[str, str]) -> str | None:
    for request in requests:
        name = request.get("in_run_area")
        if name is not None and not _is_made(name, made):
            return f"variable {request['variable']!r} names {name!r}, which no request makes"
    return None


def _one(
    index: int,
    request: SetupRequest,
    area: str,
    leave_out: Sequence[str],
    made: dict[str, str],
    steps: list[SetupStep],
    variables: dict[str, str],
) -> str | None:
    """The rules between requests, for one request whose own shape is already checked."""
    block = ACTIONS[request["action"]]
    if block.role == "passes":
        passed = block.variables(request, area)
        if passed.keys() & variables.keys():
            return f"setup request {index + 1}: the variable is passed twice"
        variables.update(passed)
        return None
    if block.role == "edits":
        problem = _writable_problem(index, request, made)
    elif block.role == "makes":
        problem = _taken_problem(index, request, made)
    else:
        problem = None
    if problem:
        return problem
    if block.role == "makes":
        made[request["name"]] = request["action"]
    steps.extend(block.steps(request, area, leave_out))
    return None


def plan(area: str, requests: Sequence[SetupRequest]) -> SetupPlan:
    """The plan for `requests` in the run area at `area`, or the problem that refuses them all."""
    for index, request in enumerate(requests):
        problem = _shape_problem(index, request)
        if problem:
            return _refused(problem)
    leave_out = [r["name"] for r in requests if ACTIONS[r["action"]].role == "leaves_out"]
    steps: list[SetupStep] = []
    variables: dict[str, str] = {}
    made: dict[str, str] = {}
    for index, request in enumerate(requests):
        problem = _one(index, request, area, leave_out, made, steps, variables)
        if problem:
            return _refused(problem)
    problem = _leave_out_problem(leave_out, [n for n, how in made.items() if how == "copy"])
    problem = problem or _variable_path_problem(requests, made)
    return (
        _refused(problem) if problem else {"steps": steps, "variables": variables, "problem": None}
    )


def refusal(requests: Sequence[SetupRequest]) -> str | None:
    """Why the requests are refused, or None: the plan's own answer, needing no run area yet."""
    return plan("/area", requests)["problem"]


def required_sources(requests: Sequence[SetupRequest]) -> list[str]:
    """The paths outside the area that the set-up of these requests fails without (a copy's source
    and a share's, unless the copy is optional), so a check can look for them before a run."""
    held = [ACTIONS[r["action"]].required_source(r) for r in requests if r["action"] in ACTIONS]
    return [source for source in held if source is not None]
