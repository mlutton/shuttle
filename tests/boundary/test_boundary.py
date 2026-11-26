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
