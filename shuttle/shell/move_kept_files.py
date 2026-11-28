"""Step 13, move kept files: the statement the executor left, and the executor's own output, each
kept exactly as written.

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
there; otherwise nowhere (a parent the executor swapped for a link is not followed). The session
file and the list of changed files belong to later steps.

The executor's standard output and standard error, and the final message its driver's tool left, are
each copied whole to a name beside the statement's (shuttle.core.evidence), made readable and
writable by the owner only, and the copy is what is hashed. Each is looked at on its own, and
a failure in one never changes another, the statement or the run's ending: a file that is not there
reads "none", a folder, link, pipe or device in its place is not followed and reads "none", and a
file that could not be moved or hashed reads "cannot tell". Nothing is scrubbed. The step runs
before the tear-down, which removes the files it copies from, and for every ending the run
lives to see the executor start.

A result key left out reads as "cannot tell" in the receipt; an empty text reads as "none".
"""

import contextlib
from collections.abc import Callable, Mapping
from typing import Any, cast

from shuttle.core import decisions, evidence, run_area, statement
from shuttle.core.shapes import (
    HeaderSource,
    NotARegularFile,
    Operations,
    OutputFiles,
    RunState,
    StepResult,
)
from shuttle.shell import statement_schema, the_driver

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


def keep_output_file(
    world: Operations, source: HeaderSource, kind: str, name: str | None
) -> dict[str, dict[str, str] | str]:
    """The result for one kept file of the executor's output, as its field's key alone. `name` is
    where the tool left it, None when the driver has no such file. A key left out reads
    "cannot tell", an empty text "none"."""
    field = evidence.field_name(kind)
    try:
        if name is None or not world.files.exists(name):
            return {field: ""}
        kept = decisions.join_path(
            source["records_location"], evidence.kept_name(source["request_id"], kind)
        )
        try:
            world.files.copy_private(name, kept)
        except OSError as error:
            return {field: ""} if evidence.reading_after(error) == "none" else {}
        return {field: {"kept_at": kept, "hash": world.files.hash(kept)}}
    except Exception:  # a failure to keep evidence never changes the run's ending
        return {}


def keep_output(world: Operations, source: HeaderSource, files: OutputFiles) -> StepResult:
    """The results of keeping the standard output, the standard error and the final message."""
    named = cast("Mapping[str, str]", files)
    kept: dict[str, dict[str, str] | str] = {}
    for kind in evidence.KINDS:
        kept.update(keep_output_file(world, source, kind, named.get(evidence.SOURCE_KEYS[kind])))
    return cast(StepResult, kept)


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

    statement_result = keep_statement(world, source, inner, location if area else None, copy_to)
    files = the_driver.of(state["raw"]).output_files(area) if area else {}
    state["stand_ins"]["kept_files"] = {**statement_result, **keep_output(world, source, files)}
