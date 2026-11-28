"""The real command and the real boundary: the lock beside a run's area says its Shuttle is alive,
and a run that starts removes the areas of runs that are gone.

A run's area is named for the run and has a lock file beside it, held while the run lives. These
tests run the real command with `TMPDIR` set to a folder of the test's own, so nothing but that
folder is looked at. None keeps time: a script says it is up through a pipe the test reads and is
let go through one the test writes.
"""

import ast
import fcntl
import importlib
import os
import subprocess
import sys
import uuid

from shuttle.core import boundary, run_area, sweep

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


QUICK = "pass\n"

# A program that says it is up and then waits to be ended.
HOLDS = [
    sys.executable,
    "-c",
    "import sys; print('up', flush=True); sys.stdin.read()",
]


class ARunThatStartsAfterAShuttleWasKilled(RealRunInItsOwnTemporaryFolder):
    def kill_a_run_with_its_executor_up(self, request_id="r-1"):
        """Start a run, kill Shuttle with SIGKILL while its executor runs, and return the area's
        name. A killed Shuttle takes its executor with it (the box dies with its parent), so no
        scope stays active; the manager is only told of the end a moment later."""
        up, go = self.pipe(f"up-{request_id}"), self.pipe(f"go-{request_id}")
        script = self.script("reports.py", REPORTS_WHAT_IT_SEES_AND_WAITS)
        proc = self.start(self.document(script, [up, go], request_id), variables=self.variables)
        with open(up) as f:
            f.read()
        proc.kill()
        proc.communicate()
        return run_area.area_name(self.run_part(request_id))

    def wait_until_the_scope_is_gone(self, request_id="r-1"):
        """The killed run's scope is not active. The kernel has ended its processes by the time
        Shuttle is dead, but the manager learns of it asynchronously and a sweep that asked in
        between would see the scope active. `systemctl stop` returns only once the manager has
        settled the unit (at once for one already ended), which is the wait with no sleep."""
        name = boundary.scope_name(request_id, self.run_part(request_id))
        subprocess.run(["systemctl", "--user", "stop", boundary.unit_of(name)], capture_output=True)
        self.assertNotEqual(self.scope_state(request_id), "active")

    def run_a_quick_one_here(self, request_id):
        script = self.script(f"quick-{request_id}.py", QUICK)
        proc = self.start(self.document(script, request_id=request_id), variables=self.variables)
        stdout, stderr = proc.communicate(timeout=120)
        return proc.returncode, stdout.splitlines(), stderr

    def test_removes_the_area_and_the_lock_file_the_dead_run_left_and_its_own_ending_is_unaffected(
        self,
    ):
        area = self.kill_a_run_with_its_executor_up()
        self.assertEqual(self.names_in_the_temporary_folder(), [area, area + ".lock"])
        self.wait_until_the_scope_is_gone()
        code, lines, err = self.run_a_quick_one_here("r-2")
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertEqual(err, "shuttle: removed 1 stale run area of runs that are gone\n")
        self.assertEqual(self.names_in_the_temporary_folder(), [])
        ending = flat(self.outcome("r-2")["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("ended_by_itself", "none", "none"),
        )

    def test_leaves_a_stale_looking_area_whose_scope_is_still_active_and_says_so(self):
        # A killed Shuttle takes its executor with it (the box dies with its parent), so no run of
        # this suite leaves a scope active. The scope here is made by the test, by the name a
        # run's executor scope has (shuttle.core.boundary.scope_name) for a part of its own, and
        # ended by the test: the unit is stopped and forgotten on every path out.
        part = uuid.uuid4().hex
        area = os.path.join(self.temporary, run_area.area_name(part))
        os.makedirs(os.path.join(area, "home"))
        with open(run_area.lock_path(area), "w"):
            pass
        unit = boundary.unit_of(boundary.scope_name("sweep-test", part))
        holder = subprocess.Popen(
            ["systemd-run", "--user", "--scope", "--quiet", f"--unit={unit}", "--", *HOLDS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(self.end_the_unit, unit, holder)
        self.assertEqual(holder.stdout.readline(), "up\n")  # the scope is there, active
        code, lines, err = self.run_a_quick_one_here("r-2")
        self.assertEqual((code, lines[-1]), (0, "ended_by_itself"))
        name = os.path.basename(area)
        self.assertEqual(
            err,
            "shuttle: removed 0 stale run areas of runs that are gone; left alone: "
            f"{name!r} ({sweep.REASON_SCOPE_ACTIVE})\n",
        )
        self.assertEqual(self.names_in_the_temporary_folder(), [name, name + ".lock"])
        self.end_the_unit(unit, holder)  # the scope is gone: nothing keeps the area now
        code, lines, err = self.run_a_quick_one_here("r-3")
        self.assertEqual(err, "shuttle: removed 1 stale run area of runs that are gone\n")
        self.assertEqual(self.names_in_the_temporary_folder(), [])

    @staticmethod
    def end_the_unit(unit, holder):
        """The test's own unit is stopped, which returns when it is gone, and forgotten."""
        for action in ("stop", "reset-failed"):
            subprocess.run(["systemctl", "--user", action, unit], capture_output=True)
        holder.stdin.close()


class ARunThatIsAliveWhileAnotherStarts(RealRunInItsOwnTemporaryFolder):
    def test_keeps_its_area_whole_and_ends_normally_while_a_second_run_starts_and_ends(self):
        up, go = self.pipe("up"), self.pipe("go")
        script = self.script("reports.py", REPORTS_WHAT_IT_SEES_AND_WAITS)
        first = self.start(self.document(script, [up, go], "r-1"), variables=self.variables)
        with open(up) as f:
            f.read()
        area = run_area.area_name(self.run_part("r-1"))
        self.assertEqual(self.names_in_the_temporary_folder(), [area, area + ".lock"])
        quick = self.script("quick.py", QUICK)
        second = self.start(self.document(quick, request_id="r-2"), variables=self.variables)
        stdout, stderr = second.communicate(timeout=120)
        self.assertEqual((second.returncode, stderr), (0, ""))  # it found nothing that looked stale
        self.assertEqual(stdout.splitlines()[-1], "ended_by_itself")
        self.assertEqual(self.names_in_the_temporary_folder(), [area, area + ".lock"])
        let_go(go)
        stdout, stderr = first.communicate(timeout=120)
        self.assertEqual((first.returncode, stderr), (0, ""))
        self.assertEqual(stdout.splitlines()[-1], "ended_by_itself")
        ending = flat(self.outcome("r-1")["receipt"])["ending"]
        self.assertEqual(
            (
                ending["ending"],
                ending["reason"],
                ending["failed_step"],
                ending["everything_stopped"],
            ),
            ("ended_by_itself", "none", "none", True),
        )
        self.assertEqual(self.names_in_the_temporary_folder(), [])
        self.assertEqual(self.units_left(), [])
