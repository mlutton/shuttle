"""The executor's own output, kept: what is kept, under what name, and how a failure reads.

A run keeps three files whole and unedited beside the statement, in the records folder the
executor cannot see: what the executor wrote to its standard output and to its standard error,
and the final message the driver's tool left (a driver whose tool leaves none keeps none). Nothing is
scrubbed: a kept file holds whatever the executor printed.
"""

from typing import Final, Literal

from shuttle.core.shapes import NotARegularFile

# The three kept files, by what each is. A kind names the receipt field (`<kind>_kept`) and, with
# its dashes, the kept file (`<request id>.<kind>.kept`).
KINDS: Final = ("standard_output", "standard_error", "final_message")

# The key of a driver's `output_files` that says where the tool leaves each kind.
SOURCE_KEYS: Final = {
    "standard_output": "standard_output",
    "standard_error": "standard_error",
    "final_message": "last_message",
}


def kept_name(request_id: str, kind: str) -> str:
    """The name of the kept file, beside the records. A request id holds no dot, so no record's
    name (`<id>.<kind>.json`) can be this one."""
    return f"{request_id}.{kind.replace('_', '-')}.kept"


def field_name(kind: str) -> str:
    return f"{kind}_kept"


def reading_after(error: BaseException) -> Literal["none", "cannot_tell"]:
    """What a kept file's field reads after the copy raised `error`: a name that holds a folder, a
    link, a pipe or a device was looked at and holds no file to keep, so there is none; a failure
    of any other kind could not look, so Shuttle cannot tell."""
    if isinstance(error, IsADirectoryError | NotARegularFile):
        return "none"
    return "cannot_tell"
