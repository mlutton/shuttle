"""Step 13, move kept files: the statement the executor left, kept exactly as written.

The executor writes its statement at one fixed path inside the run area (never at the document's
statement location, which it is not told), and this is the one place that moves it out. Only a
regular file at that path is a statement: a link (never followed), a pipe,
a device, a socket or a folder reads wrong_shape and nothing is copied. The file is copied, byte for byte, to a name beside the records (which
the executor cannot write) and the copy is what is hashed and judged, so the hash and the shape
are those of the file kept. Nothing here rewrites, completes or tidies the statement, and the
claim is passed on as the word the statement holds. The kept copy is then copied to the document's
statement location, where nothing is replaced: a name taken there since the start is left as it is
and does not change what was kept or judged. It is written into the folder the location's parent
resolved to when the run began, and only when the stop is confirmed and the parent still resolves
there; otherwise nowhere (a parent the executor swapped for a link is not followed). Only the statement is kept so far; the
session file and the list of changed files belong to later steps.

A result key left out reads as "cannot tell" in the receipt; an empty text reads as "none".
"""

import contextlib
from collections.abc import Callable
from typing import Any

from shuttle.core import decisions, run_area, statement
from shuttle.core.shapes import HeaderSource, NotARegularFile, Operations, RunState, StepResult
from shuttle.shell import statement_schema

# Looked, and there is nothing. A plain command has no session file of its own to keep.
NOTHING: StepResult = {
    "statement_state": "",
    "statement_hash": "",
    "statement_location": "",
    "claim": "",
    "session_file": "",
}


def _judged(world: Operations, kept: str) -> StepResult:
    """The state and claim of the kept file; left out (cannot tell) when the schema is not readable."""
    data = world.files.read(kept)
    held: StepResult = {"statement_hash": world.files.hash(kept), "statement_location": kept}
    try:
        schema: dict[str, Any] = statement_schema.read_schema(world)
    except (OSError, ValueError):
        return held
    examined = statement.examine(data, schema)
    wrong = bool(examined["problems"])
    held["statement_state"] = statement.WRONG_SHAPE if wrong else statement.RIGHT_SHAPE
    held["claim"] = examined["claim"] or ""
    return held


def keep_statement(
    world: Operations,
    source: HeaderSource,
    inner: str,
    location: str | None,
    copy_to: Callable[[str], str | None],
) -> StepResult:
    """The step's result for the statement at `inner`, in the run area (`location` None: this run
    has none, and nothing is looked at). `copy_to` gives where the document's location may be
    written, or None."""
    if location is None or not world.files.exists(inner):
        return {**NOTHING}
    kept = decisions.join_path(
        source["records_location"], statement.kept_name(source["request_id"])
    )
    try:
        world.files.copy(inner, kept)
        held: StepResult = {"session_file": "", **_judged(world, kept)}
    except (
        IsADirectoryError,
        NotARegularFile,
    ):  # a folder, a link, a pipe, a device: not a statement
        return {**NOTHING, "statement_state": statement.WRONG_SHAPE}
    except OSError:
        return {"session_file": ""}  # looked and could not keep it: the four fields cannot tell
    target = copy_to(location)
    if target is not None:
        with contextlib.suppress(OSError):  # the location is another's if taken; leave it
            world.files.copy(kept, target)
    return held


def step(state: RunState) -> None:
    source = state["facts"].get("header_source")
    if source is None:
        raise RuntimeError("no header source: the document was not read")
    area = state.get("run_area")
    location = state["raw"].get("statement_location")
    inner = run_area.statement_path(area) if area else ""
    world, facts = state["world"], state["facts"]

    def copy_to(wanted: str) -> str | None:
        # The folder the location's parent was at the start, looked at again just before the write.
        start = state.get("statement_parent")
        now = world.boundary.resolve(statement.location_parent(wanted)) if start else None
        return statement.location_copy_target(wanted, start, now, facts.get("stop") == "confirmed")

    state["stand_ins"]["kept_files"] = keep_statement(
        world, source, inner, location if area else None, copy_to
    )
