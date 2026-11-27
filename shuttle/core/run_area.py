"""The run area: the run's own folder, and the plan for what a driver asks to be set up in it.

A driver says, as data, what its tool needs: a path copied in (some of what is below it left
out), a path shared in place by a link (the tool reads and writes the original, so nothing is
copied and nothing is read here), a variable passed, a path made writable, a file written from
text. This module turns those requests into a plan of whole paths, or says why they are refused;
the shell acts on the plan through the world's operations. Nothing here touches the world.

Every name in the run area is relative to the area, made of letters, digits, `.`, `_` and `-`
in parts joined by `/`, and never `.` or `..` as a part, so nothing a request names can be
outside the area. A source, outside the area, is any absolute path: it is only handed on, never
split or quoted. A name that sits under a shared name is refused (a write there would land in
the original); so is a name made twice.
"""

import re
from collections.abc import Sequence

from shuttle.core import fixed
from shuttle.core.shapes import SetupPlan, SetupRequest, SetupStep

# The folder the run area is made in, by this name followed by what the system adds.
AREA_PREFIX = "shuttle-run-area-"
# Where the instruction is put for the executor's standard input; no request may name it.
INSTRUCTION_NAME = "shuttle-instruction.txt"

_PART = r"(?!\.{1,2}(?:/|$))[A-Za-z0-9._-]+"
_NAME = re.compile(f"{_PART}(?:/{_PART})*")
_ACTIONS = ("copy", "share", "leave_out", "write", "writable", "variable")
# The variables the shell itself owns.
_OWN_VARIABLES = ("PATH",)


def valid_name(name: object) -> bool:
    return isinstance(name, str) and len(name) <= 200 and _NAME.fullmatch(name) is not None


def valid_source(source: object) -> bool:
    return isinstance(source, str) and source.startswith("/") and "\0" not in source


def _under(name: str, folder: str) -> bool:
    return name.startswith(folder + "/")


def _inside(area: str, name: str) -> str:
    return area + "/" + name


def _refused(why: str) -> SetupPlan:
    return {"steps": [], "variables": {}, "problem": why}


def _name_problem(index: int, request: SetupRequest, field: str = "name") -> str | None:
    if not valid_name(request.get(field)):
        return (
            f"setup request {index + 1} ({request['action']}): {field} is not a name inside the "
            "run area (letters, digits, '.', '_' and '-', parts joined by '/', no '.' or '..' part)"
        )
    if request.get(field) == INSTRUCTION_NAME:
        return f"setup request {index + 1}: the name {INSTRUCTION_NAME!r} is kept for the instruction"
    return None


def _shape_problem(index: int, request: object) -> str | None:
    """Why one request is not one of the actions, or None."""
    if not isinstance(request, dict) or request.get("action") not in _ACTIONS:
        return f"setup request {index + 1} is not one of: {', '.join(_ACTIONS)}"
    action = request["action"]
    if action == "variable":
        return _variable_problem(index, request)
    problem = _name_problem(index, request)
    if problem:
        return problem
    if action in ("copy", "share") and not valid_source(request.get("source")):
        return f"setup request {index + 1} ({action}): source is not an absolute path"
    if action == "write" and not isinstance(request.get("text"), str):
        return f"setup request {index + 1} (write): text is missing"
    return None


def _variable_problem(index: int, request: SetupRequest) -> str | None:
    name = request.get("variable")
    if (
        not isinstance(name, str)
        or not name
        or any(c not in fixed.ID_CHARACTERS for c in name)
        or name in _OWN_VARIABLES
    ):
        return f"setup request {index + 1} (variable): the variable's name is not usable"
    if ("value" in request) == ("in_run_area" in request):
        return f"setup request {index + 1} (variable): give exactly one of value and in_run_area"
    if "value" in request and not isinstance(request["value"], str):
        return f"setup request {index + 1} (variable): value is not text"
    if "in_run_area" in request:
        return _name_problem(index, request, "in_run_area")
    return None


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
            return f"setup request {index + 1}: {name!r} is shared in place and is not made writable"
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


def plan(area: str, requests: Sequence[SetupRequest]) -> SetupPlan:
    """The plan for `requests` in the run area at `area`, or the problem that refuses them all.

    A request is checked against those before it; the leave-outs apply to every copy, wherever
    in the list they stand.
    """
    for index, request in enumerate(requests):
        problem = _shape_problem(index, request)
        if problem:
            return _refused(problem)
    leave_out = [r["name"] for r in requests if r["action"] == "leave_out"]
    steps: list[SetupStep] = []
    variables: dict[str, str] = {}
    made: dict[str, str] = {}
    for index, request in enumerate(requests):
        problem = _one(index, request, area, leave_out, made, steps, variables)
        if problem:
            return _refused(problem)
    problem = _leave_out_problem(leave_out, [n for n, how in made.items() if how == "copy"])
    return _refused(problem) if problem else {"steps": steps, "variables": variables, "problem": None}


def _one(
    index: int,
    request: SetupRequest,
    area: str,
    leave_out: Sequence[str],
    made: dict[str, str],
    steps: list[SetupStep],
    variables: dict[str, str],
) -> str | None:
    action = request["action"]
    if action == "leave_out":
        return None
    if action == "variable":
        if request["variable"] in variables:
            return f"setup request {index + 1}: the variable is passed twice"
        variables[request["variable"]] = request.get("value") or _inside(
            area, request.get("in_run_area", "")
        )
        return None
    problem = (
        _writable_problem(index, request, made)
        if action == "writable"
        else _taken_problem(index, request, made)
    )
    if problem:
        return problem
    name = request["name"]
    target = _inside(area, name)
    if action == "writable":
        steps.append({"do": "writable", "target": target})
        return None
    made[name] = action
    if action == "write":
        steps.append({"do": "write", "target": target, "text": request["text"]})
    elif action == "share":
        steps.append({"do": "share", "source": request["source"], "target": target})
    else:
        steps.append(
            {
                "do": "copy",
                "source": request["source"],
                "target": target,
                "leave_out": _left_out_of(name, leave_out),
            }
        )
    return None
