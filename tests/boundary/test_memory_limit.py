"""The memory cap through the real command and the real boundary.

A document that names `memory_limit_bytes` runs in a scope held to that memory and no swap. A
program that goes over it is ended by the scope and the run ends `memory_limit`; the same program
with no cap, or a program that stays under the cap, ends as its own exit. The programs allocate
little (tens of megabytes held, at most 200 MB tried, in steps) and the harness's limits apply to
them. A machine that cannot cap memory for a user scope skips the tests that need a cap held
(`the_boundary.require_memory_cap`), and the test of the refusal runs there instead.
"""

import importlib
import json
import os
import shutil
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")
the_boundary = importlib.import_module("rehearsal.the_boundary")
real_place = importlib.import_module("rehearsal.real_place")
flat = importlib.import_module("rehearsal.receipts").flat

MEGABYTE = 1 << 20
CAP = 64 * MEGABYTE

# argv: 1 where to write what it reached, 2 the most it may try, in megabytes, 3 where it says it
# finished, 4 a marker for a child it leaves running. It holds what it allocates and touches each
# page (a byte string of one repeated byte is written, not merely mapped), ten megabytes at a time.
ALLOCATES_IN_STEPS = """
import subprocess, sys
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", sys.argv[4]])
held = []
for step in range(1, int(sys.argv[2]) // 10 + 1):
    held.append(b"x" * (10 << 20))
    open(sys.argv[1], "w").write(str(step * 10))
open(sys.argv[3], "w").write("finished")
"""

HANGS = """
import time
time.sleep(600)
"""


class AMemoryCapEndsARunThatGrowsWithoutBound(real_run.RealRun):
    def setUp(self):
        super().setUp()
        the_boundary.require_memory_cap(self)

    def allocating(self, limit_bytes, most_megabytes=200, limit=60):
        """The document for a program that allocates in steps up to `most_megabytes`, with the cap
        named by `limit_bytes` (None for none); where it got to and whether it finished are
        written in the place."""
        marker = self.marker("shuttle-memory-child-marker")
        script = self.script("allocates.py", ALLOCATES_IN_STEPS)
        reached, finished = os.path.join(self.place, "reached"), os.path.join(self.place, "done")
        doc = self.document(script, [reached, str(most_megabytes), finished, marker], limit=limit)
        if limit_bytes is not None:
            doc["memory_limit_bytes"] = limit_bytes
        return doc, marker, reached, finished

    def reached(self, path):
        with open(path) as f:
            return int(f.read())

    def test_a_program_that_goes_over_the_cap_ends_as_memory_limit_and_nothing_is_left(self):
        doc, marker, reached, finished = self.allocating(CAP)
        temporary = os.path.join(self.root, "temporary")
        os.mkdir(temporary)
        code, lines, err = self.run_to_the_end(doc, variables={"TMPDIR": temporary})
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines[-1], "memory_limit")
        receipt = flat(self.outcome()["receipt"])
        ending = receipt["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("memory_limit", "memory_limit", "none"),
        )
        self.assertIs(ending["everything_stopped"], True)
        self.assertFalse(os.path.exists(finished))  # it did not get to the end
        self.assertLess(self.reached(reached), 200)  # and was ended well short of what it tried
        self.assertEqual(self.processes_with(marker), 0)  # the child it left running is gone
        self.assertNotEqual(self.scope_state(), "active")
        # A failed unit stays loaded until it is reset: none of the run's is left.
        self.assertEqual(self.units_left(), [])
        self.assertEqual(os.listdir(temporary), [])  # the run area is removed
        self.assertEqual(receipt["execution"]["teardown_failure"], "none")
        # no exit code or signal is claimed for a program the scope ended
        self.assertEqual(
            (receipt["execution"]["exit_code"], receipt["execution"]["signal"]),
            ("none", "cannot tell"),
        )

    def test_the_closing_freeze_and_the_place_are_as_for_a_time_limit(self):
        doc, *_ = self.allocating(CAP)
        head = real_place.git(self.place, "rev-parse", "HEAD")
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "memory_limit"))
        saw = flat(self.outcome()["receipt"])["execution"]
        self.assertEqual(saw["fingerprint_before"], head)
        # what it wrote in the place before it was ended is frozen: its progress file
        self.assertEqual(
            (saw["files_added"], saw["files_changed"], saw["files_deleted"]), (1, 0, 0)
        )
        self.assertNotIn(saw["fingerprint_after"], ("none", "cannot tell", head))

    def test_the_same_program_with_no_cap_ends_as_its_own_exit(self):
        doc, marker, reached, finished = self.allocating(None)
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        self.assertEqual(self.reached(reached), 200)
        self.assertTrue(os.path.exists(finished))
        saw = flat(self.outcome()["receipt"])["execution"]
        self.assertEqual(saw["exit_code"], 0)

    def test_a_program_that_stays_under_the_cap_ends_as_its_own_exit(self):
        doc, marker, reached, finished = self.allocating(CAP, most_megabytes=30)
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        self.assertTrue(os.path.exists(finished))
        self.assertEqual(flat(self.outcome()["receipt"])["execution"]["exit_code"], 0)
        self.assertEqual(self.units_left(), [])

    def test_a_program_that_hangs_under_a_cap_and_a_short_time_limit_ends_as_time_limit(self):
        script = self.script("hangs.py", HANGS)
        doc = self.document(script, limit=1)
        doc["memory_limit_bytes"] = CAP
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "time_limit"))
        ending = flat(self.outcome()["receipt"])["ending"]
        self.assertEqual((ending["ending"], ending["reason"]), ("time_limit", "time_limit"))
        self.assertEqual(self.units_left(), [])

    def test_a_program_the_box_cannot_execute_under_a_cap_is_program_not_started(self):
        # The box's report holds no end for the program, as it does for one a cap ended; only the
        # scope's own result tells the two apart: this scope ended by itself, with a success.
        script = os.path.join(self.support, "script")
        with open(script, "w") as f:
            f.write("#!/nonexistent-folder/sh\n")
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        doc = self.document("unused")
        doc["executor"]["settings"] = {"command": script, "arguments": []}
        doc["memory_limit_bytes"] = CAP
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
        ending = flat(self.outcome()["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "program_not_started", "launch"),
        )
        self.assertEqual(self.units_left(), [])


class ANamedCapOnAMachineThatCannotHoldItIsRefused(real_run.RealRun):
    """The machine is made to look unable to cap by a `systemd-run` in front of the real one on
    the command's PATH that makes no scope (the trial scope is its only user here: the document
    has no gates), so nothing about the machine changes."""

    def a_machine_that_cannot_make_a_scope(self):
        folder = os.path.join(self.root, "no-scope")
        os.mkdir(folder)
        tool = os.path.join(folder, "systemd-run")
        with open(tool, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(tool, os.stat(tool).st_mode | stat.S_IXUSR)
        self.assertNotEqual(shutil.which("systemd-run", path=folder), None)
        return folder

    def document_with_a_cap(self, request_id):
        doc = self.document(self.script("hangs.py", HANGS), request_id=request_id)
        doc["memory_limit_bytes"] = CAP
        return doc

    def test_the_run_and_the_check_refuse_with_the_same_line_and_launch_nothing(self):
        folder = self.a_machine_that_cannot_make_a_scope()
        code, lines, err = self.run_to_the_end(self.document_with_a_cap("run-1"), path_first=folder)
        self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
        ending = flat(self.outcome("run-1")["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "memory_cap_unavailable", "input_check"),
        )
        line = ending["reason_text"]
        self.assertIn("cannot cap memory for a user scope", line)
        self.assertIn("leave memory_limit_bytes out", line)
        proc = self.start(self.document_with_a_cap("check-1"), path_first=folder, form="check")
        stdout, stderr = proc.communicate(timeout=120)
        self.assertEqual((proc.returncode, stderr), (0, ""))
        printed = stdout.splitlines()
        self.assertIn("check: refused: memory_cap_unavailable", printed)
        would_write = flat(json.loads(printed[1])["receipt"])["ending"]
        self.assertEqual(
            (would_write["reason"], would_write["failed_step"], would_write["reason_text"]),
            ("memory_cap_unavailable", "input_check", line),
        )
        self.assertEqual(self.units_left(), [])  # nothing was launched, and no trial is left
