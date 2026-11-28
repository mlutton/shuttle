"""The executor's own output, kept: what is kept, under what name, and how a failure reads.

A run keeps three files unedited beside the statement, in the records folder the
executor cannot see: what the executor wrote to its standard output and to its standard error,
and the final message the driver's tool left (a driver whose tool leaves none keeps none). Nothing is
scrubbed: a kept file holds whatever the executor printed.
"""

from typing import Final, Literal

# The three kept files, by what each is. A kind names the receipt field (`<kind>_kept`) and, with
# its underscores made dashes, the kept file (`<request id>.<kind>.kept`).
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


Step = Literal["copy", "none", "cannot_tell"]


def what_to_do(kind: str, named: bool, look: str) -> Step:
    """What the step does for one kept file, from what looking at its name found.

    `look` is what `look_at` of the file operations says: "missing", "file", "folder", "link" (to
    anything) or "other" (a pipe, a device, a socket).

    "none" means looked, and there is nothing: the driver has no such file (`named` False), or the
    tool did not write its final message. A standard output or standard error file was made new
    for the executor before it started, so one that is missing now was removed, and output may
    have been written and cannot be shown: "cannot tell". So is anything but a regular file at the
    name (a link is never followed), since something is there that was not kept.
    """
    if not named:
        return "none"
    if look == "file":
        return "copy"
    if look == "missing" and kind == "final_message":
        return "none"
    return "cannot_tell"
