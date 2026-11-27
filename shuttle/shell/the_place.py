"""Looking at the place the document names: the one place the shell gathers its facts."""

from shuttle.core import place
from shuttle.core.shapes import Document, Operations, PlaceFacts


def look(world: Operations, raw: Document) -> PlaceFacts | None:
    """The place's facts, or None when the document names no place that can be looked at.

    The path is made absolute, with links resolved, as the boundary sees it. Looking changes
    nothing in the place, not even its index; git is given nothing of the caller's configuration.
    """
    path = raw.get("place")
    if not isinstance(path, str) or not place.usable_place(path):
        return None
    return world.git.look_at_place(
        world.boundary.resolve(path),
        place.git_environment(world.environment.read_variable("PATH")),
    )
