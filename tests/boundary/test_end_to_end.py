"""The end-to-end test: one real request through every piece that is real so far: an input check,
a gate, the boundary and the outcome record.

From the input document, through the real command and the real boundary, to the outcome record,
asserting only what a caller can see: the exit code, what is printed, the record files, and what
is left running. It keeps no time: the limit is the boundary's, the script says it is up through
a pipe, and the run's end is waited for, not slept to. It skips, with its reason, on a machine
that lacks the boundary, and fails there instead when SHUTTLE_REQUIRE_BOUNDARY is set (the
hosted runner sets it).

#46 (fingerprints) and #47 (delivery) extend this test when their pieces become real; they do
not add one of their own.
"""

import hashlib
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")

HANGS_WITH_A_CHILD = """
import subprocess, sys, time
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", sys.argv[2]])
open(sys.argv[1], "w").write("up")
time.sleep(600)
"""


GATE_THAT_SAYS_YES = """
import sys
open(sys.argv[1], "w").write("asked")
"""

REFERENCE_TEXT = "the runbook"


class AScriptThatHangsEndsAsTimeLimit(real_run.RealRun):
    def test_a_script_that_hangs_ends_as_time_limit_and_nothing_it_started_is_left(self):
        up = self.pipe("up")
        marker = "shuttle-e2e-child-marker"
        script = self.script("hangs.py", HANGS_WITH_A_CHILD)
        asked = os.path.join(self.root, "asked")
        runbook = self.script("runbook.txt", REFERENCE_TEXT)
        doc = self.document(script, [up, marker], limit=1)
        doc["references"] = [  # an input check that passes
            {
                "name": "runbook",
                "path": runbook,
                "hash": hashlib.sha256(REFERENCE_TEXT.encode()).hexdigest(),
                "size": len(REFERENCE_TEXT),
                "hash_source": "caller",
            }
        ]
        doc["gates"] = [  # a gate that says yes
            {
                "name": "quota",
                "command": sys.executable,
                "arguments": [self.script("gate.py", GATE_THAT_SAYS_YES), asked],
                "limit_seconds": 60,
            }
        ]
        proc = self.start(doc)
        with open(up) as f:
            f.read()  # blocks until the script is running
        stdout, stderr = proc.communicate(timeout=120)
        self.assertEqual((proc.returncode, stderr), (0, ""))
        lines = stdout.splitlines()
        self.assertEqual(
            lines, ["r-1", os.path.join(self.records, "r-1.outcome.json"), "time_limit"]
        )
        receipt = flat(self.outcome()["receipt"])
        ending = receipt["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("time_limit", "time_limit", "none"),
        )
        self.assertIs(ending["everything_stopped"], True)
        self.assertEqual(self.processes_with(marker), 0)  # the child the script started is gone
        self.assertNotEqual(self.scope_state(), "active")
        self.assertTrue(os.path.exists(asked))  # the gate was asked, said yes, and the run went on
        self.assertEqual(self.units_left(), [])  # no scope of the run or of the gate is left
