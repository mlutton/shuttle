"""Which run areas a run's start may remove: those whose run is gone, and only those.

A run area is left behind when its Shuttle is killed hard. The next run to start in the same
temporary folder removes it, if it can show that nobody is using it: the lock beside the area is
free (the kernel frees it when the process that held it dies) and no scope of that run is still
active. Everything here is a decision over facts the shell gathered; nothing touches the world.

What counts as Shuttle's: a name that is exactly an area's name or a lock's, a real folder owned by
the user beside a regular file the user owns. Anything else is not looked at again: the sweep does
not guess, so a doubt about a name leaves it where it is.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from shuttle.core import boundary, run_area

_PART = r"[0-9a-f]{32}"
_AREA = re.compile(re.escape(run_area.AREA_PREFIX) + f"({_PART})")
_LOCK = re.compile(re.escape(run_area.AREA_PREFIX) + f"({_PART})" + re.escape(run_area.LOCK_SUFFIX))

# What the shell saw of one name (shuttle.core.shapes.FileOperations.look_at): its kind and
# whether the user owns it.
Look = tuple[str, bool]
# What taking the lock gave: "taken" (now held), "held" (another holds it) or "gone" (the name
# is no longer a regular file, or no longer the file that was opened).
Taken = Literal["taken", "held", "gone"]
# The scopes of the run: unit to active state, or "unknown" when they could not be looked up.
Scopes = Mapping[str, str] | Literal["unknown"]
Step = Literal[
    "ignore",  # not Shuttle's: leave it, say nothing
    "in_use",  # its lock is held: the run is alive, leave it, say nothing
    "take_lock",
    "ask_scopes",
    "remove_lock",  # a lock file whose area is gone
    "remove_area",
    "scope_active",  # looked stale, left: a scope of the run is still active
    "scopes_unknown",  # looked stale, left: whether a scope is active could not be seen
]


def run_parts(names: Sequence[str]) -> list[str]:
    """The run part of every name that is exactly an area's or a lock's, each once, in order."""
    found: set[str] = set()
    for name in names:
        matched = _AREA.fullmatch(name) or _LOCK.fullmatch(name)
        if matched:
            found.add(matched.group(1))
    return sorted(found)


def unit_pattern(run_part: str) -> str:
    """What fits the unit of any scope of the run (the executor's, a gate's, the closing
    freeze's): their names end in the run part, or the part and a number. The part is hex, so the
    pattern holds no character that is special to the manager's glob but the stars."""
    return f"shuttle-*-{run_part}*"


def next_step(area: Look, lock: Look, taken: Taken | None, scopes: Scopes | None) -> Step:
    """What to do next about one run part, given what is known so far. `taken` and `scopes` are
    None until they have been asked for: the step says what to ask next."""
    if lock != ("file", True):
        return "ignore"
    if area[0] != "missing" and area != ("folder", True):
        return "ignore"
    if taken is None:
        return "take_lock"
    if taken == "held":
        return "in_use"
    if taken != "taken":
        return "ignore"
    if area[0] == "missing":
        return "remove_lock"
    if scopes is None:
        return "ask_scopes"
    if isinstance(scopes, str):
        return "scopes_unknown"
    quiet = all(boundary.scope_is_empty({"ActiveState": state}) for state in scopes.values())
    return "remove_area" if quiet else "scope_active"


REASON_SCOPE_ACTIVE = "a scope of the run is still active"
REASON_SCOPES_UNKNOWN = "whether a scope of the run is still active could not be seen"


def reason_not_removed(error: str) -> str:
    return f"it could not be removed ({error})"


def reason_not_checked(error: str) -> str:
    return f"it could not be checked ({error})"


def _count(number: int, what: str) -> str:
    return f"{number} {what}" if number == 1 else f"{number} {what}s"


def summary(areas_removed: int, locks_removed: int, left: Sequence[tuple[str, str]]) -> str | None:
    """The one line a sweep prints, or None when it found nothing that looked stale. Each name is
    shown as a quoted literal: it is data, never text to be read as anything else."""
    if not areas_removed and not locks_removed and not left:
        return None
    line = f"shuttle: removed {_count(areas_removed, 'stale run area')} of runs that are gone"
    if locks_removed:
        line += f" and {_count(locks_removed, 'leftover lock file')}"
    if left:
        line += "; left alone: " + ", ".join(f"{name!r} ({why})" for name, why in left)
    return line


def not_swept(error: str) -> str:
    """The line when the sweep itself could not be done; the run goes on."""
    return (
        f"shuttle: stale run areas were not looked for ({error}); "
        "nothing was removed and the run goes on"
    )
