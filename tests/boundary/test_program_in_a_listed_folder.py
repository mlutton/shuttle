"""A program in a folder the caller listed under `reach.visible`, through the real command in the
real box: the check accepts it and the run starts it inside the box.

The same program in a folder that is not listed is refused by the check and the run before
anything starts (tests/command/test_refusals.py); here the folder is listed and the program runs.
"""

import importlib
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")

# Writes what only the box can say: it ran, and its own name for the folder it was found in.
WRITES_WHERE_IT_RAN = """import os, sys
open(sys.argv[1], "w").write(os.path.dirname(os.path.abspath(sys.argv[0])))
"""


class AProgramInAListedFolder(real_run.RealRun):
    def program(self):
        folder = os.path.join(self.root, "elsewhere")  # not the support folder, not listed
        os.mkdir(folder)
        path = os.path.join(folder, "the-program")
        with open(path, "w") as f:
            f.write(f"#!{real_run.INTERPRETER}\n{WRITES_WHERE_IT_RAN}")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return folder, path

    def document_naming(self, program, listed):
        witness = os.path.join(self.place, "witness.txt")
        doc = self.document("unused", [witness])
        doc["executor"]["settings"] = {"command": program, "arguments": [witness]}
        doc["reach"]["visible"] = [*doc["reach"]["visible"], *listed]
        return doc, witness

    def test_the_folder_listed_makes_the_program_accepted_by_the_check_and_started_by_the_run(self):
        folder, program = self.program()
        doc, witness = self.document_naming(program, [folder])
        checked, _ = self.start(doc, form="check").communicate(timeout=120)
        self.assertEqual(checked.splitlines()[-2], "check: no refusal found")
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(witness) as f:
            self.assertEqual(f.read(), folder)  # it ran in the box, at its own path

    def test_the_same_document_without_the_listing_is_refused_and_nothing_runs(self):
        _, program = self.program()
        doc, witness = self.document_naming(program, [])
        code, lines, _ = self.run_to_the_end(doc)
        self.assertEqual((code, lines[-1]), (0, "could_not_start"))
        self.assertFalse(os.path.exists(witness))
