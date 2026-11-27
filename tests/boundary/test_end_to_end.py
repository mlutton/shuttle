"""The end-to-end test: one real request through every piece that is real so far: an input check,
a gate, the opening fingerprint of a real place, the boundary, the statement the script leaves,
the closing freeze, the kept statement and the outcome record.

From the input document, through the real command and the real boundary, to the outcome record,
asserting only what a caller can see: the exit code, what is printed, the record files, and what
is left running. It keeps no time: the limit is the boundary's, the script says it is up through
a pipe, and the run's end is waited for, not slept to. It skips, with its reason, on a machine
that lacks the boundary, and fails there instead when SHUTTLE_REQUIRE_BOUNDARY is set (the
hosted runner sets it).

The executor is given the instruction and the notice on its standard input, and the run area made
for it (in a temporary folder of the test's own) is there while it runs and gone at the end.

The statement (#48) is left by the script before it hangs and reads "right shape".

#47 (delivery) extends this test when its piece becomes real; it does not add one of its own.
"""

import ast
import hashlib
import importlib
import os
import select
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")
real_place = importlib.import_module("rehearsal.real_place")

# The statement the script leaves, right-shaped and untidy (no final newline): a kept copy that
# was tidied or completed would differ from it.
STATEMENT_TEXT = (
    '{"claim": "partly_done", "summary": "Started; still running.", "evidence":'
    ' [{"claim": "it ran", "command": "true"}], "not_tested": ["everything"],'
    ' "feedback": "none"}'
)

HANGS_WITH_A_CHILD = """
import os, subprocess, sys, time
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", sys.argv[2]])
open(sys.argv[3], "w").write(sys.argv[4])  # the statement, before the hang
open(sys.argv[5], "w").write(sys.stdin.read())  # what it was given as its standard input
areas = os.listdir(sys.argv[6])  # the run areas there are while it runs, with what each holds
open(sys.argv[7], "w").write(repr({a: sorted(os.listdir(sys.argv[6] + "/" + a)) for a in areas}))
open(sys.argv[1], "w").write("up")
time.sleep(600)
"""


GATE_THAT_SAYS_YES = """
import sys
open(sys.argv[1], "w").write("asked")
"""

REFERENCE_TEXT = "the runbook"
INSTRUCTION = "Do the work.\nSecond line with 'quotes', $HOME and `ticks`.\n"


class AScriptThatHangsEndsAsTimeLimit(real_run.RealRun):
    def test_a_script_that_hangs_ends_as_time_limit_and_nothing_it_started_is_left(self):
        up = self.pipe("up")
        marker = "shuttle-e2e-child-marker"
        script = self.script("hangs.py", HANGS_WITH_A_CHILD)
        asked = os.path.join(self.root, "asked")
        runbook = self.script("runbook.txt", REFERENCE_TEXT)
        statement = os.path.join(self.root, "statement.json")
        given, seen = os.path.join(self.root, "given"), os.path.join(self.root, "seen")
        temporary = os.path.join(self.root, "temporary")
        os.mkdir(temporary)
        doc = self.document(
            script, [up, marker, statement, STATEMENT_TEXT, given, temporary, seen], limit=1
        )
        doc["kind"], doc["statement_location"] = "judge", statement  # a kind that expects one
        doc["instruction"] = INSTRUCTION
        doc["instruction_hash"] = hashlib.sha256(INSTRUCTION.encode()).hexdigest()
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
        proc = self.start(doc, variables={"TMPDIR": temporary})
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
        with open(given) as f:  # the instruction, then the notice, on its standard input
            text = f.read()
        self.assertTrue(text.startswith(INSTRUCTION + "\n"))
        self.assertIn("Shuttle notice, version", text)
        self.assertIn(statement, text)
        self.assertIn("- runbook: " + runbook, text)
        with open(seen) as f:  # one run area while it ran, holding the instruction's file
            during = ast.literal_eval(f.read())
        self.assertEqual(len(during), 1)
        ((name, held),) = during.items()
        self.assertTrue(name.startswith("shuttle-run-area-"))
        self.assertEqual(held, ["shuttle-instruction.txt"])
        self.assertEqual(os.listdir(temporary), [])  # removed whole at the end
        self.assertEqual(receipt["execution"]["teardown_failure"], "none")
        kept = os.path.join(self.records, "r-1.statement.kept")
        with open(kept, "rb") as f:  # the statement is kept as written, even at the time limit
            self.assertEqual(f.read(), STATEMENT_TEXT.encode())
        self.assertEqual(
            receipt["executor"],
            {
                "statement_state": "right_shape",
                "statement_hash": hashlib.sha256(STATEMENT_TEXT.encode()).hexdigest(),
                "statement_location": kept,
                "claim": "partly_done",
            },
        )
