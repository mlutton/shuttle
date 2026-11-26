"""Records: the shell code that puts the two JSON records in place and reads them.

Each record is built in memory, written under a temporary name, flushed and then
linked into place, which fails if the name exists. So a record is whole or absent,
is written once, and the request record's claim is first one wins. The files are
reached through the operations passed in, never directly.
"""

import contextlib
import json
from collections.abc import Callable
from typing import Any

from shuttle.core import decisions
from shuttle.core.shapes import Operations, OutcomeRecord, RequestRecord


def request_path(records_location: str, request_id: str) -> str:
    return decisions.join_path(records_location, decisions.record_name(request_id, "request"))


def outcome_path(records_location: str, request_id: str) -> str:
    return decisions.join_path(records_location, decisions.record_name(request_id, "outcome"))


def _no_note(line: str) -> None:
    """For a caller with nowhere to put a note."""


class RecordNotBuilt(Exception):
    """The text of a record could not be built; nothing was written."""


def _put_whole(
    world: Operations,
    final: str,
    record: RequestRecord | OutcomeRecord,
    note: Callable[[str], None] = _no_note,
) -> str:
    """Put a record under its real name whole, or not at all.

    The text is built first, written under a temporary name in the same folder, flushed, and
    then linked to the real name, which fails if the name exists. Once the link is made the write
    has succeeded: a temporary name that cannot be removed afterwards is a note, not a failure.
    """
    try:
        text = json.dumps(record, indent=2) + "\n"
    except Exception as error:
        raise RecordNotBuilt(type(error).__name__) from error
    temporary = decisions.temporary_name(final, world.identity.process_number())
    try:
        world.files.write_new(temporary, text)
        world.files.link(temporary, final)
    except BaseException:
        with contextlib.suppress(Exception):  # the write failed: tidy up, and keep its error
            world.files.remove(temporary)
        raise
    _remove_temporary(world, temporary, note)
    return final


def _remove_temporary(world: Operations, temporary: str, note: Callable[[str], None]) -> None:
    try:
        world.files.remove(temporary)
    except FileNotFoundError:
        pass
    except Exception as error:
        note(
            f"shuttle: the temporary name {temporary} could not be removed "
            f"({type(error).__name__}); the record itself is in place"
        )


def claim_request_record(
    world: Operations,
    records_location: str,
    request_id: str,
    record: RequestRecord,
    note: Callable[[str], None] = _no_note,
) -> str:
    """Claim the request id by putting the request record in place whole.

    Raises FileExistsError when the id is used, and RecordNotBuilt when the text cannot be
    built (the id is then not spent). The id is used when either record of the pair exists.
    `note` is given one line about anything left behind that does not change the result.
    """
    if world.files.exists(outcome_path(records_location, request_id)):
        raise FileExistsError(outcome_path(records_location, request_id))
    return _put_whole(world, request_path(records_location, request_id), record, note)


def write_outcome_record(
    world: Operations,
    records_location: str,
    request_id: str,
    record: OutcomeRecord,
    note: Callable[[str], None] = _no_note,
) -> str:
    """Write the outcome record once. Raises FileExistsError when one exists.

    Returns the path. `note` is given one line about anything left behind that does not change the result.
    """
    return _put_whole(world, outcome_path(records_location, request_id), record, note)


def read_record(world: Operations, path: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(world.files.read(path).decode("utf-8"))
    return data
