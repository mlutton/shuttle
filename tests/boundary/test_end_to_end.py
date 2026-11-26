"""The end-to-end test: one real request through every piece that is real so far: an input check,
a gate, the opening fingerprint of a real place, the boundary, the closing freeze and the outcome
record.

From the input document, through the real command and the real boundary, to the outcome record,
asserting only what a caller can see: the exit code, what is printed, the record files, and what
is left running. It keeps no time: the limit is the boundary's, the script says it is up through
a pipe, and the run's end is waited for, not slept to. It skips, with its reason, on a machine
that lacks the boundary, and fails there instead when SHUTTLE_REQUIRE_BOUNDARY is set (the
hosted runner sets it).

#47 (delivery) extends this test when its piece becomes real; it does not add one of its own.
"""

import hashlib
import importlib
import os
import select
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")
real_place = importlib.import_module("rehearsal.real_place")

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
        # the place is a linked working copy of the caller's repository, as it is in use
        callers = os.path.join(self.root, "callers-repo")
        real_place.make_checkout(callers)
        doc["place"] = os.path.join(self.root, "linked-place")
        head = real_place.make_linked_checkout(callers, doc["place"])
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
        # Block until the script says it is up or the command ends, whichever comes first: a run
        # that is refused never starts the script, and must fail here, not hang.
        said = os.open(up, os.O_RDONLY | os.O_NONBLOCK)
        ended = os.pidfd_open(proc.pid)
        try:
            ready, _, _ = select.select([said, ended], [], [])
        finally:
            os.close(said)
            os.close(ended)
        if said not in ready:
            stdout, stderr = proc.communicate(timeout=120)
            self.fail(f"the command ended before the script was up: {stdout!r} {stderr!r}")
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
        saw = receipt["execution"]  # the script wrote nothing in the place
        self.assertEqual((saw["fingerprint_before"], saw["fingerprint_after"]), (head, head))
        self.assertIs(saw["changed_nothing"], True)
        self.assertEqual(self.processes_with(marker), 0)  # the child the script started is gone
        self.assertNotEqual(self.scope_state(), "active")
        self.assertTrue(os.path.exists(asked))  # the gate was asked, said yes, and the run went on
        self.assertEqual(self.units_left(), [])  # no scope of the run, a gate or the freeze is left
