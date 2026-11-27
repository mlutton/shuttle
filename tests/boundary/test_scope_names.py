"""The real boundary, through the real command: a run's scopes are its own.

Scope names are shared across the whole user session, so each scope a run makes carries a part
unique to that run (see shuttle.core.boundary). These tests look at what that is for: two runs of
one request id at once, units of the names a run used to take held by something else, and a
`check` of a document while a `run` of it is in its gates. None keeps time: a script says it is up
through a pipe the test reads and is let go through one the test writes.
"""

import importlib
import os
import subprocess
import sys
import tempfile
import uuid

from shuttle.core import boundary

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")
real_place = importlib.import_module("rehearsal.real_place")

# Says it is up (one byte on the pipe in argument 1), then waits for one byte on the pipe in
# argument 2, which it opens for reading and writing so that it never sees an end of file.
SAYS_IT_IS_UP_AND_WAITS_TO_BE_LET_GO = """
import os, sys
with open(sys.argv[1], "w") as up:
    up.write("u")
go = os.open(sys.argv[2], os.O_RDWR)
os.read(go, 1)
"""

HOLDS = """
import sys, time
open(sys.argv[1], "w").write("up")
time.sleep(600)
"""


HOLDS_AND_IGNORES_TERM = """
import signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(sys.argv[1], "w").write("up")
time.sleep(600)
"""


def read_bytes(path, count):
    """Block until `count` bytes have come through the pipe at `path`."""
    got = b""
    while len(got) < count:
        with open(path, "rb") as f:
            got += f.read()
    return got


def let_go(path, count):
    descriptor = os.open(path, os.O_RDWR)
    os.write(descriptor, b"g" * count)
    os.close(descriptor)  # the bytes stay in the pipe while a reader has it open


def gate(script, up, go):
    return {
        "name": "g",
        "command": sys.executable,
        "arguments": [script, up, go],
        "limit_seconds": 60,
    }


class TwoRunsOfOneRequestIdAtOnce(real_run.RealRun):
    def test_in_two_records_locations_both_end_as_each_would_alone(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        records = os.path.join(os.path.realpath(other.name), "records")
        place = os.path.join(os.path.realpath(other.name), "place")
        os.mkdir(records)
        real_place.make_checkout(place)
        self.records_folders.append(records)
        script = self.script("waits.py", SAYS_IT_IS_UP_AND_WAITS_TO_BE_LET_GO)
        up, go = self.pipe("up"), self.pipe("go")
        one = self.document(script, [up, go])
        one["gates"] = [gate(script, up, go)]  # each run has a gate and an executor
        two = {**one, "records_location": records, "place": place}
        first = self.start(one)
        second = self.start(two, root=other.name)
        # Both gates are up at once, then both executors, then each is let go in turn.
        for _ in range(2):
            read_bytes(up, 2)
            let_go(go, 2)
        for proc in (first, second):
            stdout, stderr = proc.communicate(timeout=120)
            self.assertEqual((proc.returncode, stderr), (0, ""))
            self.assertEqual(stdout.splitlines()[-1], "ended_by_itself")
        for where in (self.records, records):
            ending = flat(self.outcome(records=where)["receipt"])["ending"]
            self.assertEqual(
                (ending["ending"], ending["reason"], ending["failed_step"]),
                ("ended_by_itself", "none", "none"),
            )
            self.assertIs(ending["everything_stopped"], True)
        parts = {self.run_part("r-1"), self.run_part("r-1", records)}
        self.assertEqual(len(parts), 2)
        self.assertEqual(self.units_left(), [])


class UnitsOfTheOldNamesHeldByAnotherUser(real_run.RealRun):
    # The names a run took before they carried a part of its own, and the one before that.
    def setUp(self):
        super().setUp()
        # A request id of its own, so that the old names held here are this test's alone and
        # another suite's test of the same kind (or of this one) holds other names.
        self.request_id = "old-" + uuid.uuid4().hex[:8]
        self.old_names = tuple(
            template.format(self.request_id)
            for template in (
                "shuttle-{}",
                "shuttle-run-{}",
                "shuttle-gate-{}-0",
                "shuttle-freeze-{}",
            )
        )

    def hold(self, name, how):
        """A unit of `name`, made by this test and not by a run: running, or failed (made by
        stopping it while it ignores the request to end, so the scope's stop timeout kills it)."""
        up = self.pipe(f"held-{name}")
        script = self.script("holds.py", HOLDS if how == "running" else HOLDS_AND_IGNORES_TERM)
        holder = subprocess.Popen(
            ["systemd-run", "--user", "--scope", "--quiet", f"--unit={name}"]
            + ["-p", "TimeoutStopSec=100ms", sys.executable, script, up]
        )
        self.addCleanup(self.let_go_of, name, holder)
        with open(up) as f:
            f.read()  # blocks until the holder is running
        if how == "failed":
            subprocess.run(["systemctl", "--user", "stop", f"{name}.scope"], check=True)
        return holder

    @staticmethod
    def let_go_of(name, holder):
        subprocess.run(["systemctl", "--user", "stop", f"{name}.scope"], capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "reset-failed", f"{name}.scope"], capture_output=True
        )
        holder.wait()

    @staticmethod
    def state_of(name):
        done = subprocess.run(
            ["systemctl", "--user", "show", "-p", "ActiveState", "--value", f"{name}.scope"],
            capture_output=True,
            text=True,
        )
        return done.stdout.strip()

    def assert_the_run_ends_as_it_would_alone_and_the_units_are_left(self, how, still):
        holders = {name: self.hold(name, how) for name in self.old_names}
        script = self.script("ends.py", "raise SystemExit(0)")
        doc = self.document(script, request_id=self.request_id)
        doc["gates"] = [{"name": "g", "command": "/bin/true", "arguments": [], "limit_seconds": 60}]
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        ending = flat(self.outcome(self.request_id)["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("ended_by_itself", "none", "none"),
        )
        self.assertEqual(self.units_left(), [])
        for name, holder in holders.items():
            self.assertEqual(self.state_of(name), still, name)  # not stopped, not forgotten
            if how == "running":
                self.assertIsNone(holder.poll(), name)

    def test_running_do_not_change_a_runs_ending_and_are_left_untouched(self):
        self.assert_the_run_ends_as_it_would_alone_and_the_units_are_left("running", "active")

    def test_failed_do_not_change_a_runs_ending_and_are_left_untouched(self):
        self.assert_the_run_ends_as_it_would_alone_and_the_units_are_left("failed", "failed")


class ACheckWhileARunOfTheSameDocumentIsInItsGates(real_run.RealRun):
    def test_disturbs_neither(self):
        request_id = (
            "check-" + uuid.uuid4().hex[:8]
        )  # so the units listed below are this test's own
        script = self.script("waits.py", SAYS_IT_IS_UP_AND_WAITS_TO_BE_LET_GO)
        up, go = self.pipe("up"), self.pipe("go")
        doc = self.document(self.script("ends.py", "raise SystemExit(0)"), request_id=request_id)
        doc["gates"] = [gate(script, up, go)]
        run = self.start(doc)
        read_bytes(up, 1)  # the run is in its gate
        check = self.start(doc, form="check")
        read_bytes(up, 1)  # and so is the check, in a gate of its own
        gates = [u for u in self.listed(f"shuttle-gate-{request_id}-*")]
        self.assertEqual(len(gates), 2, gates)
        self.assertEqual(len(set(gates)), 2)
        let_go(go, 2)
        stdout, stderr = run.communicate(timeout=120)
        self.assertEqual((run.returncode, stderr), (0, ""))
        self.assertEqual(stdout.splitlines()[-1], "ended_by_itself")
        ending = flat(self.outcome(request_id)["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("ended_by_itself", "none", "none"),
        )
        check.communicate(timeout=120)
        self.assertEqual(self.listed(f"shuttle-*-{request_id}-*"), [])
        self.assertEqual(
            sorted(n for n in os.listdir(self.records) if n.startswith(request_id)),
            [f"{request_id}.outcome.json", f"{request_id}.request.json"],
        )

    @staticmethod
    def listed(pattern):
        done = subprocess.run(
            ["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", pattern],
            capture_output=True,
            text=True,
        )
        return [line.split()[0] for line in done.stdout.splitlines() if line.split()]


class TheRunsPartIsWhereALaterCommandCanFindIt(real_run.RealRun):
    def test_the_executors_scope_has_the_name_built_from_the_request_record(self):
        up, go = self.pipe("up"), self.pipe("go")
        script = self.script("waits.py", SAYS_IT_IS_UP_AND_WAITS_TO_BE_LET_GO)
        proc = self.start(self.document(script, [up, go]))
        read_bytes(up, 1)
        name = boundary.scope_name("r-1", self.run_part())
        self.assertEqual(self.scope_state(), "active")
        done = subprocess.run(
            ["systemctl", "--user", "is-active", boundary.unit_of(name)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.stdout.strip(), "active")
        let_go(go, 1)
        proc.communicate(timeout=120)
        self.assertEqual(self.units_left(), [])
