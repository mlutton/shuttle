"""A run on the simulated world, set up in a line: a document, a records folder, a program.

`scene()` gives a SimulatedWorld holding an input document and an empty records folder, with one
program registered. `run_in(world)` runs the real `run` on it and returns what the command would
have printed. Nothing real is touched and no time passes.
"""

import hashlib
import io
import json

from shuttle.shell import run

from rehearsal.simulated_world import SimulatedWorld

RECORDS = "/records"
PLACE = "/place"
DOCUMENT = "/input.json"
REQUEST_ID = "inj-1"


def document(command="tool", limit=30, **extra):
    doc = {
        "format_version": 1,
        "request_id": REQUEST_ID,
        "records_location": RECORDS,
        "place": PLACE,
        "thread": "t",
        "round": 1,
        "kind": "plain",
        "time_limit_seconds": limit,
        "executor": {"name": "command", "settings": {"command": command, "arguments": []}},
    }
    doc.update(extra)
    if doc["kind"] != "plain" and "instruction" not in doc:  # a kind with a statement needs one
        doc["instruction"] = "Do the task."
        doc["instruction_hash"] = hashlib.sha256(doc["instruction"].encode()).hexdigest()
    return doc


def scene(doc=None, **program):
    """A world with the document in place, a clean place, and a program "tool" (see SimulatedWorld.program;
    by default one that exits at once)."""
    world = SimulatedWorld()
    world.make_folder(RECORDS)
    world.put_shipped_data()
    world.make_place(PLACE, {"README": "the place\n"})
    world.put_file(DOCUMENT, json.dumps(doc or document()))
    world.program("tool", **(program if program else {}))
    return world


def run_in(world, steps=None):
    """(exit code, standard output lines, standard error text) of the run, on the world."""
    out, err = io.StringIO(), io.StringIO()
    if steps is None:
        code = run.run(DOCUMENT, out, err, world.operations)
    else:
        code = run.run_steps(steps, DOCUMENT, out, err, world.operations)
    return code, out.getvalue().splitlines(), err.getvalue()


def outcome(world, request_id=REQUEST_ID):
    return json.loads(world.text_of(f"{RECORDS}/{request_id}.outcome.json"))
