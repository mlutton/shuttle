"""The input checks that need facts from the world: kinds, references, the statement location,
the reach.

Each fact is gathered here and handed to a pure check in shuttle.core.refusals; this module decides
nothing. `run_input_checks` returns every check's answer, in order, for the run (which records the
first) and for the check form (which lists them all).
"""

import hashlib
from typing import Any

from shuttle.core import place, refusals
from shuttle.core.refusals import Found
from shuttle.core.shapes import Document, Operations, VisibleLook
from shuttle.shell import kinds, the_place


def _found_references(world: Operations, references: list[Document]) -> dict[str, dict[str, Any]]:
    """The hash and size of each reference's file, {"folder": True} for a folder; a reference
    that cannot be read is left out."""
    found: dict[str, dict[str, Any]] = {}
    for reference in references:
        try:
            data = world.files.read(reference["path"])
        except IsADirectoryError:
            found[reference["name"]] = {"folder": True}
            continue
        except OSError:
            continue
        found[reference["name"]] = {"hash": hashlib.sha256(data).hexdigest(), "size": len(data)}
    return found


def _kind_checks(world: Operations, raw: Document) -> list[Found | None]:
    try:
        known = kinds.read_kinds(world)
    except OSError:
        return [
            {
                "reason": "unknown_kind",
                "step": "input_check",
                "problem": "the files that list the kinds could not be read; reinstall Shuttle",
            }
        ]
    location = raw.get("statement_location")
    occupied = location is not None and world.files.exists(location)
    # Resolved through links and `..`, the way the place is, so no spelling reaches the records.
    in_records = location is not None and refusals.inside_folder(
        world.boundary.resolve(location), world.boundary.resolve(raw["records_location"])
    )
    return [
        refusals.check_kind(raw["kind"], known),
        refusals.check_statement_location(
            known.get(raw["kind"], False), location, occupied, in_records
        ),
    ]


def _expects_a_statement(world: Operations, raw: Document) -> bool:
    """Whether the kind expects a statement; False when the kinds cannot be read (the kind
    check says so)."""
    try:
        return kinds.read_kinds(world).get(raw["kind"], False)
    except OSError:
        return False


def _look_at_visible(world: Operations, raw: Document) -> dict[str, VisibleLook]:
    """Each folder the reach lists as visible that has a path to look at: whether it is there,
    whether it is a folder, and where it resolves to."""
    found: dict[str, VisibleLook] = {}
    for path in refusals.visible_paths(raw.get("reach")):
        if path.startswith("/") and "\0" not in path:
            found[path] = {
                "exists": world.files.exists(path),
                "folder": world.files.is_folder(path),
                "resolved": world.boundary.resolve(path),
            }
    return found


def _account_folders(world: Operations) -> tuple[str, str | None]:
    """The user's runtime folder (the box hides it, with the systemd and D-Bus sockets in it)
    and home folder, resolved, as the system gives them for this user. Never from the caller's
    environment: a caller that misnames a variable must not be able to switch a refusal off."""
    home = world.identity.home_folder()
    return (
        world.boundary.resolve(world.identity.runtime_folder()),
        world.boundary.resolve(home) if home else None,
    )


def run_input_checks(world: Operations, raw: Document) -> list[Found | None]:
    references = raw.get("references", [])
    runtime, home = _account_folders(world)
    return [
        *_kind_checks(world, raw),
        refusals.check_instruction(
            raw.get("instruction"), raw.get("instruction_hash"), _expects_a_statement(world, raw)
        ),
        refusals.check_references(references, _found_references(world, references)),
        refusals.check_reach(
            raw.get("reach"),
            _look_at_visible(world, raw),
            world.boundary.resolve(raw["records_location"]),
            runtime,
            home,
        ),
        place.check_place(raw.get("place"), the_place.look(world, raw)),
    ]
