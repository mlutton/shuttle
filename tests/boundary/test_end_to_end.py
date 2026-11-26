"""The end-to-end test: one real request through every piece that is real so far.

From the input document, through the real command and the real boundary, to the outcome record,
asserting only what a caller can see: the exit code, what is printed, the record files, and what
is left running. It keeps no time: the limit is the boundary's, the script says it is up through
a pipe, and the run's end is waited for, not slept to. It skips, with its reason, on a machine
that lacks the boundary, and fails there instead when SHUTTLE_REQUIRE_BOUNDARY is set (the
hosted runner sets it).

#46 (fingerprints) and #47 (delivery) extend this test when their pieces become real; they do
not add one of their own.
"""

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


class AScriptThatHangsEndsAsTimeLimit(real_run.RealRun):
    def test_a_script_that_hangs_ends_as_time_limit_and_nothing_it_started_is_left(self):
        up = self.pipe("up")
        marker = "shuttle-e2e-child-marker"
        script = self.script("hangs.py", HANGS_WITH_A_CHILD)
        proc = self.start(self.document(script, [up, marker], limit=1))
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
