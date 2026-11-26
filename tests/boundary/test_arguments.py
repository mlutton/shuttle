"""What reaches a command through the real boundary unchanged: its arguments and the records path.

The scope tool (`systemd-run`) expands `$` in the command it is given; names are data, so an
argument must arrive byte for byte, for the executor and for a gate, and a records location with
special characters must still be protected. Rows come from the hostile names table.
"""

import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")
real_place = importlib.import_module("rehearsal.real_place")
names_table = importlib.import_module("hostile.names_table")

TRIES_TO_WRITE_THE_RECORDS = importlib.import_module(
    "boundary.test_boundary"
).TRIES_TO_WRITE_THE_RECORDS

# Writes the arguments it was given (after the first, a file name) as JSON to that file.
WRITES_ITS_ARGUMENTS = """
import json, sys
open(sys.argv[1], "w").write(json.dumps(sys.argv[2:]))
"""

# Arguments that systemd treats specially in a unit file or a command line: dollars, a braced
# variable, a specifier-like percent, a backslash; the rows of the names table that hold them.
SPECIAL = [
    row["name"]
    for row in names_table.NAMES
    if any(c in row["name"] for c in "$%\\") and "\\udc" not in ascii(row["name"])
]


class ArgumentsArriveByteForByte(real_run.RealRun):
    def test_the_executors_and_a_gates_arguments_are_not_changed_by_the_scope_tool(self):
        self.assertGreaterEqual(len(SPECIAL), 5)
        seen_by_executor = os.path.join(self.place, "executor.json")
        seen_by_gate = os.path.join(self.root, "gate.json")
        writer = self.script("writes.py", WRITES_ITS_ARGUMENTS)
        doc = self.document(writer, [seen_by_executor, *SPECIAL])
        doc["gates"] = [
            {
                "name": "g",
                "command": sys.executable,
                "arguments": [writer, seen_by_gate, *SPECIAL],
                "limit_seconds": 60,
            }
        ]
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(seen_by_gate) as f:
            self.assertEqual(json.load(f), SPECIAL)
        with open(seen_by_executor) as f:
            self.assertEqual(json.load(f), SPECIAL)


class ARecordsLocationWithSpecialCharacters(real_run.RealRun):
    def test_is_still_protected_and_the_run_still_works(self):
        self.records = os.path.join(self.root, "rec$$a${X}b$HOME%h%n%%\\")
        os.mkdir(self.records)
        with open(os.path.join(self.records, "old.txt"), "w") as f:
            f.write("original")
        script = self.script("tries.py", TRIES_TO_WRITE_THE_RECORDS)
        code, lines, err = self.run_to_the_end(self.document(script, [self.records, self.place]))
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(os.path.join(self.place, "log.txt")) as f:
            tries = f.read().splitlines()
        self.assertEqual(len(tries), 8, tries)
        self.assertEqual([t for t in tries if "GOT THROUGH" in t], [])
        with open(os.path.join(self.records, "old.txt")) as f:
            self.assertEqual(f.read(), "original")


# Each row of the table that a folder can be named, one folder inside the next: the place's own
# path holds a dollar, a braced name, a percent, a backslash, spaces, a newline, a leading dash
# and the rest. (Names that are not valid UTF-8 are left out, as in the test above.)
FOLDER_NAMES = [
    row["name"]
    for row in names_table.NAMES
    if row["holdable"]
    and not row["path"]
    and "\\udc" not in ascii(row["name"])
    and row["name"] not in (".", "..")
]

WRITES_A_FILE_IN_THE_PLACE = """
import os, sys
open(os.path.join(sys.argv[1], "made by the script.txt"), "w").write("x")
"""


class APlaceWhoseOwnPathHoldsEveryAwkwardName(real_run.RealRun):
    def test_is_looked_at_frozen_and_counted_with_its_path_unchanged(self):
        self.assertGreaterEqual(len(FOLDER_NAMES), 30)
        place = os.path.join(self.root, *FOLDER_NAMES)
        real_place.make_checkout(place)
        head = real_place.git(place, "rev-parse", "HEAD")
        doc = self.document(self.script("writes.py", WRITES_A_FILE_IN_THE_PLACE), [place])
        doc["place"] = place
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        saw = self.outcome()["receipt"]["execution"]
        self.assertEqual(saw["fingerprint_before"]["value"], head)
        self.assertEqual(saw["files_added"]["value"], 1)
        frozen = saw["fingerprint_after"]["value"]
        self.assertEqual(real_place.git(place, "rev-parse", f"{frozen}^"), head)
