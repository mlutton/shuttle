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
