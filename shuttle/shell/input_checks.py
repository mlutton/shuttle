"""The input checks that need facts from the world: kinds, references, the statement location.

Each fact is gathered here and handed to a pure check in shuttle.core.refusals; this module decides
nothing. `run_input_checks` returns every check's answer, in order, for the run (which records the
first) and for the check form (which lists them all).
"""

import hashlib
from typing import Any

from shuttle.core import place, refusals
from shuttle.core.refusals import Found
from shuttle.core.shapes import Document, Operations
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
    return [
        refusals.check_kind(raw["kind"], known),
        refusals.check_statement_location(known.get(raw["kind"], False), location, occupied),
    ]


def run_input_checks(world: Operations, raw: Document) -> list[Found | None]:
    references = raw.get("references", [])
    return [
        *_kind_checks(world, raw),
        refusals.check_instruction(raw.get("instruction"), raw.get("instruction_hash")),
        refusals.check_references(references, _found_references(world, references)),
        refusals.check_reach(raw.get("reach")),
        place.check_place(raw.get("place"), the_place.look(world, raw)),
    ]
