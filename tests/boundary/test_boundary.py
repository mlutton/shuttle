"""The real boundary, through the real command: what is left, what is refused.

Each test runs a small real script as the executor and asserts only what a caller can see. None
keeps time: a script says it is up through a pipe the test reads, and a wait is a block on the
thing waited for (a pipe, a process's end), never a sleep. They skip, with a reason, where the
boundary is absent (see rehearsal/the_boundary.py). The time limit itself is in test_end_to_end.py.
"""

import importlib
import os
import select
import signal
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")

LEAVES_A_CHILD = """
import subprocess, sys
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", sys.argv[1]],
                 start_new_session=True)
"""

SAYS_IT_IS_UP_AND_SLEEPS = """
import sys, time
open(sys.argv[1], "w").write("up")
time.sleep(600)
"""

KILLS_ITSELF = """
import os, signal
os.kill(os.getpid(), signal.SIGKILL)
"""

# A tool that stands in for the real one on PATH and fails as the real one does when it cannot
# make what it was asked to: it says why on standard error and exits with status 1.
FAILS = "#!/bin/sh\necho 'could not do it' >&2\nexit 1\n"

# Each attempt on the records folder (argv 1) is one line in a file in the place (argv 2):
# "<name> refused" or "<name> GOT THROUGH".
TRIES_TO_WRITE_THE_RECORDS = """
import os, subprocess, sys
records, place = sys.argv[1], sys.argv[2]
log = open(os.path.join(place, "log.txt"), "w")

def attempt(name, action):
    try:
        action()
    except OSError:
        log.write(name + " refused\\n")
    else:
        log.write(name + " GOT THROUGH\\n")

def write(path, text="changed"):
    with open(path, "w") as f:
        f.write(text)

attempt("create", lambda: write(os.path.join(records, "new.txt")))
attempt("overwrite", lambda: write(os.path.join(records, "old.txt")))
attempt("delete", lambda: os.unlink(os.path.join(records, "old.txt")))
attempt("rename", lambda: os.rename(os.path.join(records, "old.txt"), os.path.join(records, "x")))
attempt("make a folder", lambda: os.mkdir(os.path.join(records, "d")))
attempt("through the root", lambda: write("/proc/self/root" + records + "/via-root.txt"))
os.symlink(records, os.path.join(place, "link"))
attempt("through a link", lambda: write(os.path.join(place, "link", "via-link.txt")))

def remount():
    done = subprocess.run(["mount", "-o", "remount,rw", records], capture_output=True)
    if done.returncode != 0:
        raise OSError("the remount was refused")

attempt("remount read-write", remount)
write(os.path.join(place, "new.txt"), "the place is writable")
"""


class ABoundaryThatNeverStarted(real_run.RealRun):
    """The boundary's tools are on the machine but cannot make the box: the executor never ran,
    so the run could not start, and nothing about the executor's end is claimed."""

    def a_failing(self, tool):
        folder = os.path.join(self.root, "shims")
        os.mkdir(folder)
        path = os.path.join(folder, tool)
        with open(path, "w") as f:
            f.write(FAILS)
        os.chmod(path, 0o755)
        return folder

    def assert_could_not_start_at_the_launch(self, tool):
        script = self.script("never-runs.py", "open(__import__('sys').argv[1], 'w').write('ran')")
        ran = os.path.join(self.root, "ran")
        code, lines, err = self.run_to_the_end(
            self.document(script, [ran]), path_first=self.a_failing(tool)
        )
        self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
        receipt = self.outcome()["receipt"]
        ending = flat(receipt)["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "launch_failed", "launch"),
        )
        self.assertNotEqual(receipt["execution"]["exit_code"]["state"], "value")
        self.assertFalse(os.path.exists(ran))
        self.assertNotEqual(self.scope_state(), "active")

    def test_a_bubblewrap_that_fails_is_a_launch_that_failed(self):
        self.assert_could_not_start_at_the_launch("bwrap")

    def test_a_systemd_run_that_fails_is_a_launch_that_failed(self):
        self.assert_could_not_start_at_the_launch("systemd-run")


class AScriptThatKillsItself(real_run.RealRun):
    def test_is_recorded_with_the_exit_code_seen_and_a_signal_that_cannot_be_told(self):
        # bubblewrap reports a signalled child as 128 + n, which is also what a script that
        # exits with that number reports: the signal is not read out of the number.
        script = self.script("kills.py", KILLS_ITSELF)
        code, lines, err = self.run_to_the_end(self.document(script))
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        saw = self.outcome()["receipt"]["execution"]
        self.assertEqual(saw["exit_code"], {"state": "value", "value": 137})
        self.assertEqual(saw["signal"], {"state": "cannot tell", "value": None})


class AChildThatOutlivesItsScript(real_run.RealRun):
    def test_is_stopped_and_the_boundary_is_seen_empty(self):
        marker = "shuttle-boundary-outliving-child"
        script = self.script("leaves.py", LEAVES_A_CHILD)
        code, lines, err = self.run_to_the_end(self.document(script, [marker]))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertIs(flat(self.outcome()["receipt"])["ending"]["everything_stopped"], True)
        self.assertEqual(self.processes_with(marker), 0)
        self.assertNotEqual(self.scope_state(), "active")


class TheCommandKilledHard(real_run.RealRun):
    def cgroup_of(self, request_id):
        done = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                "-p",
                "ControlGroup",
                "--value",
                f"shuttle-run-{request_id}.scope",
            ],
            capture_output=True,
            text=True,
        )
        return "/sys/fs/cgroup" + done.stdout.strip()

    def processes_in(self, cgroup):
        with open(os.path.join(cgroup, "cgroup.procs")) as f:
            return [int(n) for n in f.read().split()]

    def populated(self, cgroup):
        try:
            with open(os.path.join(cgroup, "cgroup.events")) as f:
                return "populated 1" in f.read()
        except FileNotFoundError:
            return False  # the scope's folder is gone: nothing is in it

    def test_leaves_the_boundary_empty(self):
        up = self.pipe("up")
        script = self.script("sleeps.py", SAYS_IT_IS_UP_AND_SLEEPS)
        proc = self.start(self.document(script, [up]))
        with open(up) as f:
            f.read()  # blocks until the script is running in the boundary
        cgroup = self.cgroup_of("r-1")
        inside = self.processes_in(cgroup)
        self.assertTrue(inside, "nothing is in the boundary while the script runs")
        proc.send_signal(signal.SIGKILL)
        proc.communicate()
        for pid in inside:  # block until each one has ended, by a handle on the process itself
            try:
                handle = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            select.select([handle], [], [])
            os.close(handle)
        self.assertFalse(self.populated(cgroup))
        self.assertFalse(os.path.exists(os.path.join(self.records, "r-1.outcome.json")))


class AScriptThatTriesToWriteTheRecords(real_run.RealRun):
    def test_is_refused_every_time_the_records_are_unchanged_and_the_place_is_writable(self):
        with open(os.path.join(self.records, "old.txt"), "w") as f:
            f.write("original")
        script = self.script("tries.py", TRIES_TO_WRITE_THE_RECORDS)
        code, lines, err = self.run_to_the_end(self.document(script, [self.records, self.place]))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines[-1], "ended_by_itself")
        with open(os.path.join(self.place, "log.txt")) as f:
            tries = f.read().splitlines()
        self.assertEqual(len(tries), 8, tries)
        self.assertEqual([t for t in tries if "GOT THROUGH" in t], [])
        self.assertEqual(
            sorted(os.listdir(self.records)), ["old.txt", "r-1.outcome.json", "r-1.request.json"]
        )
        with open(os.path.join(self.records, "old.txt")) as f:
            self.assertEqual(f.read(), "original")
        with open(os.path.join(self.place, "new.txt")) as f:
            self.assertEqual(f.read(), "the place is writable")


class AGateWhoseScopeNameIsTakenByAnotherUnit(real_run.RealRun):
    def test_reads_failed_and_the_other_unit_is_left_running(self):
        up = self.pipe("up")
        holder = self.script("holder.py", SAYS_IT_IS_UP_AND_SLEEPS)
        name = "shuttle-gate-r-1-0"  # the name this run's first gate would take
        other = subprocess.Popen(
            ["systemd-run", "--user", "--scope", "--quiet", f"--unit={name}", sys.executable]
            + [holder, up]
        )
        self.addCleanup(other.wait)
        self.addCleanup(
            subprocess.run, ["systemctl", "--user", "stop", f"{name}.scope"], capture_output=True
        )
        with open(up) as f:
            f.read()  # blocks until the other unit is running
        doc = self.document(self.script("never.py", "raise SystemExit(0)"))
        doc["gates"] = [{"name": "g", "command": "/bin/true", "arguments": [], "limit_seconds": 60}]
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines[-1], "could_not_start")
        self.assertEqual(flat(self.outcome()["receipt"])["ending"]["reason"], "gate_failed")
        state = subprocess.run(
            ["systemctl", "--user", "is-active", f"{name}.scope"], capture_output=True, text=True
        )
        self.assertEqual(state.stdout.strip(), "active")
