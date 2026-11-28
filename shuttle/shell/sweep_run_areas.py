"""Before a run makes its own area, remove the areas of runs that are gone.

Only in a real run (the check form makes no area and never calls this), only in the temporary
folder this run will use, and only what shuttle.core.sweep shows to be Shuttle's and unused. The
sweep holds the lock of an area while it looks at it and removes it, so two sweeps at once never
remove the same area twice and neither can reach an area a live run holds: the lock of a live run
is held from before its area exists to after it is gone.

It never changes a run: any trouble is a line on standard error, and the run goes on. What it says
is one line, and only when it found something that looked stale.
"""

import contextlib
from collections.abc import Sequence

from shuttle.core import run_area, sweep
from shuttle.core.shapes import NotARegularFile, Operations, RunState

# What one run part came to: "ignored" (not Shuttle's, or in use), "removed_area",
# "removed_lock", or "left" with the reason it was left.
_Result = tuple[str, str]


def _take(world: Operations, lock: str) -> sweep.Taken:
    try:
        return "taken" if world.files.try_lock(lock) else "held"
    except (FileNotFoundError, NotARegularFile, IsADirectoryError):
        return "gone"  # swapped or removed since it was looked at: not what was looked at


def _scopes(world: Operations, part: str) -> sweep.Scopes:
    try:
        return world.boundary.list_units(sweep.unit_pattern(part))
    except OSError:
        return "unknown"


def _remove_the_area(world: Operations, area: str, lock: str) -> _Result:
    files = world.files
    try:
        files.remove_tree(area)
    except FileNotFoundError:
        pass  # gone already
    except OSError as error:
        return "left", sweep.reason_not_removed(type(error).__name__)
    with contextlib.suppress(
        OSError
    ):  # a lock file left over is harmless: a later sweep removes it
        files.release_lock(lock, True)
    return "removed_area", ""


def _remove_the_lock(world: Operations, lock: str) -> _Result:
    try:
        world.files.release_lock(lock, True)
    except FileNotFoundError:
        return "ignored", ""
    except OSError as error:
        return "left", sweep.reason_not_removed(type(error).__name__)
    return "removed_lock", ""


def _one(world: Operations, folder: str, part: str) -> _Result:
    files = world.files
    area = f"{folder}/{run_area.area_name(part)}"
    lock = run_area.lock_path(area)
    area_look, lock_look = files.look_at(area), files.look_at(lock)
    taken: sweep.Taken | None = None
    scopes: sweep.Scopes | None = None
    try:
        while True:
            step = sweep.next_step(area_look, lock_look, taken, scopes)
            if step == "take_lock":
                taken = _take(world, lock)
            elif step == "ask_scopes":
                scopes = _scopes(world, part)
            elif step == "remove_area":
                return _remove_the_area(world, area, lock)
            elif step == "remove_lock":
                return _remove_the_lock(world, lock)
            elif step == "scope_active":
                return "left", sweep.REASON_SCOPE_ACTIVE
            elif step == "scopes_unknown":
                return "left", sweep.REASON_SCOPES_UNKNOWN
            else:
                return "ignored", ""
    finally:
        # Let go of a lock taken for the look, leaving the file (after a removal this does
        # nothing). Never one this process holds for a run of its own: that was not taken here.
        if taken == "taken":
            with contextlib.suppress(OSError):
                files.release_lock(lock, False)


def _sweep(world: Operations) -> str | None:
    folder = world.files.temporary_folder()
    names: Sequence[str] = world.files.list_names(folder, run_area.AREA_PREFIX)
    areas = locks = 0
    left: list[tuple[str, str]] = []
    for part in sweep.run_parts(names):
        try:
            kind, why = _one(world, folder, part)
        except OSError as error:  # one name that cannot be seen to the end does not stop the rest
            kind, why = "left", sweep.reason_not_checked(type(error).__name__)
        if kind == "removed_area":
            areas += 1
        elif kind == "removed_lock":
            locks += 1
        elif kind == "left":
            left.append((run_area.area_name(part), why))
    return sweep.summary(areas, locks, left)


def sweep_before_the_run_makes_its_area(state: RunState) -> None:
    """Remove the areas of runs that are gone, and say so in one line on standard error. Nothing
    it does or fails to do reaches the run."""
    try:
        line = _sweep(state["world"])
    except Exception as error:  # fail closed: say what was not done
        line = sweep.not_swept(type(error).__name__)
    if line:
        with contextlib.suppress(OSError, ValueError):  # a reader that went away is not the run's
            state["err"].write(line + "\n")
            state["err"].flush()
