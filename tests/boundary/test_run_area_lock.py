"""The real command and the real boundary: the lock beside a run's area says its Shuttle is alive.

A run's area is named for the run and has a lock file beside it, held while the run lives. These
tests run the real command with `TMPDIR` set to a folder of the test's own, so nothing but that
folder is looked at. None keeps time: a script says it is up through a pipe the test reads and is
let go through one the test writes.
"""

import ast
import fcntl
import importlib
import os
import sys

from shuttle.core import run_area

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")

# Says what the executor sees of the area's surroundings (on the pipe in argument 1), then waits
# for one byte on the pipe in argument 2, which it opens for reading and writing so that it never
# sees an end of file. The area is where the executor's own home (HOME) is kept.
REPORTS_WHAT_IT_SEES_AND_WAITS = """
import os, sys
area = os.path.dirname(os.environ["HOME"])
seen = {
    "area": os.path.isdir(area),
    "lock": os.path.lexists(area + ".lock"),
}
try:
    os.close(os.open(area + ".lock", os.O_WRONLY))
    seen["lock_opened"] = True
except OSError:
    seen["lock_opened"] = False
with open(sys.argv[1], "w") as up:
    up.write(repr(seen))
go = os.open(sys.argv[2], os.O_RDWR)
os.read(go, 1)
"""


def let_go(path):
    descriptor = os.open(path, os.O_RDWR)
    os.write(descriptor, b"g")
    os.close(descriptor)  # the byte stays in the pipe while a reader has it open


class RealRunInItsOwnTemporaryFolder(real_run.RealRun):
    def setUp(self):
        super().setUp()
        self.temporary = os.path.join(self.root, "temporary")
        os.mkdir(self.temporary)
        self.variables = {"TMPDIR": self.temporary}

    def names_in_the_temporary_folder(self):
        return sorted(os.listdir(self.temporary))


class TheLockOfARun(RealRunInItsOwnTemporaryFolder):
    def test_is_beside_the_area_named_for_the_run_held_while_it_lives_hidden_from_the_executor_and_gone_after(
        self,
    ):
        up, go = self.pipe("up"), self.pipe("go")
        script = self.script("reports.py", REPORTS_WHAT_IT_SEES_AND_WAITS)
        proc = self.start(self.document(script, [up, go]), variables=self.variables)
        with open(up) as f:
            seen = ast.literal_eval(f.read())
        area = run_area.area_name(self.run_part())
        self.assertEqual(self.names_in_the_temporary_folder(), [area, area + ".lock"])
        lock = os.path.join(self.temporary, area + ".lock")
        descriptor = os.open(lock, os.O_RDONLY)
        self.addCleanup(os.close, descriptor)
        with self.assertRaises(BlockingIOError):  # the run holds it
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(os.stat(lock).st_mode & 0o777, 0o600)
        self.assertEqual(seen, {"area": True, "lock": False, "lock_opened": False})
        let_go(go)
        stdout, stderr = proc.communicate(timeout=120)
        self.assertEqual((proc.returncode, stderr), (0, ""))
        self.assertEqual(stdout.splitlines()[-1], "ended_by_itself")
        self.assertEqual(self.names_in_the_temporary_folder(), [])
        fcntl.flock(
            descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB
        )  # the file is gone; the lock was let go

    def test_of_a_run_killed_hard_is_free_and_its_area_and_file_stay(self):
        up, go = self.pipe("up"), self.pipe("go")
        script = self.script("reports.py", REPORTS_WHAT_IT_SEES_AND_WAITS)
        proc = self.start(self.document(script, [up, go]), variables=self.variables)
        with open(up) as f:
            f.read()
        proc.kill()
        proc.communicate()
        area = run_area.area_name(self.run_part())
        self.assertEqual(self.names_in_the_temporary_folder(), [area, area + ".lock"])
        descriptor = os.open(os.path.join(self.temporary, area + ".lock"), os.O_RDONLY)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)  # free: the kernel gave it back
