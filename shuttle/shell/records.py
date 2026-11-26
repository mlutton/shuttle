"""Records: the shell code that puts the two JSON records in place and reads them.

Each record is built in memory, written under a temporary name, flushed and then
linked into place, which fails if the name exists. So a record is whole or absent,
is written once, and the request record's claim is first one wins. The files are
reached through the operations passed in, never directly.
"""

import contextlib
import json
from collections.abc import Mapping
from typing import Any

from shuttle.core import decisions
from shuttle.core.shapes import Operations


def request_path(records_location: str, request_id: str) -> str:
    return decisions.join_path(records_location, f"{request_id}.request.json")


def outcome_path(records_location: str, request_id: str) -> str:
    return decisions.join_path(records_location, f"{request_id}.outcome.json")


class RecordNotBuilt(Exception):
    """The text of a record could not be built; nothing was written."""


def _put_whole(world: Operations, final: str, record: Mapping[str, Any]) -> str:
    """Put a record under its real name whole, or not at all.

    The text is built first, written under a temporary name in the same folder, flushed, and
    then linked to the real name, which fails if the name exists. The temporary name is always
    removed.
    """
    try:
        text = json.dumps(record, indent=2) + "\n"
    except Exception as error:
        raise RecordNotBuilt(type(error).__name__) from error
    temporary = f"{final}.tmp-{world.identity.process_number()}"
    try:
        world.files.write_new(temporary, text)
        world.files.link(temporary, final)
    finally:
        with contextlib.suppress(FileNotFoundError):
            world.files.remove(temporary)
    return final


def claim_request_record(
    world: Operations, records_location: str, request_id: str, record: Mapping[str, Any]
) -> str:
    """Claim the request id by putting the request record in place whole.

    Raises FileExistsError when the id is used, and RecordNotBuilt when the text cannot be
    built (the id is then not spent). The id is used when either record of the pair exists.
    """
    if world.files.exists(outcome_path(records_location, request_id)):
        raise FileExistsError(outcome_path(records_location, request_id))
    return _put_whole(world, request_path(records_location, request_id), record)


def write_outcome_record(
    world: Operations, records_location: str, request_id: str, record: Mapping[str, Any]
) -> str:
    """Write the outcome record once. Raises FileExistsError when one exists.

    Returns the path.
    """
    return _put_whole(world, outcome_path(records_location, request_id), record)


def read_record(world: Operations, path: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(world.files.read(path).decode("utf-8"))
    return data
