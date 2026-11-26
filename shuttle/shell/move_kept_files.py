"""Step 13, move kept files: the statement the executor left, kept exactly as written.

The file at the statement location is copied, byte for byte, to a name beside the records (which
the executor cannot write) and the copy is what is hashed and judged, so the hash and the shape
are those of the file kept. Nothing here rewrites, completes or tidies the statement, and the
claim is passed on as the word the statement holds. Only the statement is kept so far; the
session file and the list of changed files belong to later steps.

A result key left out reads as "cannot tell" in the receipt; an empty text reads as "none".
"""

from typing import Any

from shuttle.core import decisions, statement
from shuttle.core.shapes import HeaderSource, Operations, RunState, StepResult
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


def keep_statement(world: Operations, source: HeaderSource, location: str | None) -> StepResult:
    """The step's result for one statement location (None: this run has none)."""
    if location is None or not world.files.exists(location):
        return {**NOTHING}
    kept = decisions.join_path(
        source["records_location"], statement.kept_name(source["request_id"])
    )
    try:
        world.files.copy(location, kept)
        return {"session_file": "", **_judged(world, kept)}
    except IsADirectoryError:  # something is there that is not a file: it is not a statement
        return {**NOTHING, "statement_state": statement.WRONG_SHAPE}
    except OSError:
        return {"session_file": ""}  # looked and could not keep it: the four fields cannot tell


def step(state: RunState) -> None:
    source = state["facts"].get("header_source")
    if source is None:
        raise RuntimeError("no header source: the document was not read")
    location = state["raw"].get("statement_location")
    state["stand_ins"]["kept_files"] = keep_statement(state["world"], source, location)
