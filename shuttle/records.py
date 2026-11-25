"""Records: the shell that reads and writes the two JSON records.

Each record is built in memory, written under a temporary name, flushed and then
linked into place, which fails if the name exists. So a record is whole or absent,
is written once, and the request record's claim is first one wins.
"""

import contextlib
import json
import os
from collections.abc import Callable, Mapping
from typing import Any


def request_path(records_location: str, request_id: str) -> str:
    return os.path.join(records_location, f"{request_id}.request.json")


def outcome_path(records_location: str, request_id: str) -> str:
    return os.path.join(records_location, f"{request_id}.outcome.json")


Fault = Callable[[str], None]


class RecordNotBuilt(Exception):
    """The text of a record could not be built; nothing was written."""


def _put_whole(final: str, record: Mapping[str, Any], fault: Fault | None) -> str:
    """Put a record under its real name whole, or not at all.

    The text is built first, written under a temporary name in the same folder, flushed, and
    then linked to the real name, which fails if the name exists. The temporary name is always
    removed. `fault` is a test seam: it is called with the name of each point and may raise.
    """
    fault = fault or (lambda point: None)
    try:
        fault("build_text")
        text = json.dumps(record, indent=2) + "\n"
    except Exception as error:
        raise RecordNotBuilt(type(error).__name__) from error
    temporary = f"{final}.tmp-{os.getpid()}"
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            fault("write_temporary")
            f.write(text)
            fault("flush")
            f.flush()
            os.fsync(f.fileno())
        fault("put_in_place")
        os.link(temporary, final)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
    return final


def claim_request_record(
    records_location: str, request_id: str, record: Mapping[str, Any], fault: Fault | None = None
) -> str:
    """Claim the request id by putting the request record in place whole.

    Raises FileExistsError when the id is used, and RecordNotBuilt when the text cannot be
    built (the id is then not spent). The id is used when either record of the pair exists.
    """
    if os.path.lexists(outcome_path(records_location, request_id)):
        raise FileExistsError(outcome_path(records_location, request_id))
    return _put_whole(request_path(records_location, request_id), record, fault)


def write_outcome_record(
    records_location: str, request_id: str, record: Mapping[str, Any], fault: Fault | None = None
) -> str:
    """Write the outcome record once. Raises FileExistsError when one exists.

    Returns the path.
    """
    return _put_whole(outcome_path(records_location, request_id), record, fault)


def read_record(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data
