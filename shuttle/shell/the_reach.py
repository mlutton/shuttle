"""What the shell finds of the box's reach that exists before the run does.

The launch builds the box from it (the run area is added there) and the executor driver's check
asks the core from it whether the box shows the program, so the two read the same paths.
"""

from collections.abc import Mapping
from typing import Any

from shuttle.core import boundary, refusals
from shuttle.core import place as git_place
from shuttle.core.shapes import Operations


def resolver_file(world: Operations) -> str | None:
    """The file `/etc/resolv.conf` leads to, when it leads to one that is there (the box shows
    what the core decides to; this is only the fact)."""
    target = world.boundary.resolve("/etc/resolv.conf")
    if world.files.exists(target) and not world.files.is_folder(target):
        return target
    return None


def account_folders(world: Operations) -> tuple[str, str | None]:
    """The user's runtime folder (the box hides it, with the systemd and D-Bus sockets in it)
    and home folder, resolved, as the system gives them for this user. Never from the caller's
    environment: a caller that misnames a variable must not be able to switch a refusal off."""
    home = world.identity.home_folder()
    return (
        world.boundary.resolve(world.identity.runtime_folder()),
        world.boundary.resolve(home) if home else None,
    )


def shown(world: Operations, raw: Mapping[str, Any]) -> boundary.Shown | None:
    """The paths the document's reach shows, each resolved as the box binds it; None when the
    document names no place (the input check refuses it)."""
    place = raw.get("place")
    if not isinstance(place, str):
        return None
    resolve = world.boundary.resolve
    resolved = resolve(place)
    return {
        "place": resolved,
        "references": [
            resolve(r["path"])
            for r in raw.get("references", [])
            if isinstance(r, dict) and isinstance(r.get("path"), str)
        ],
        "visible": [resolve(path) for path in refusals.visible_paths(raw.get("reach"))],
        "git_folders": world.git.git_folders(
            resolved, git_place.git_environment(world.environment.read_variable("PATH"))
        ),
        "resolver": resolver_file(world),
    }
