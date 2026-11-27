"""A real run of the command against the real boundary, for the tests under tests/boundary/.

Everything is in one temporary root: the records folder, the place the scripts may write, and the
scripts. A script says it is up through a named pipe the test reads, so no test polls or sleeps.
"""

import json
import os
import resource
import subprocess
import sys
import tempfile
import unittest

from shuttle.core import boundary

import rehearsal.real_place as real_place
import rehearsal.the_boundary as the_boundary

# The one place the limits of a real command live. A test whose input has no end (a device, a
# pipe, a file of any size) must fail an assertion in seconds, not grow until the machine gives
# out: no file the command or its executor makes can pass 16 MB, and no process of theirs can
# map more than 1 GB.
DEFAULT_LIMITS = {
    resource.RLIMIT_FSIZE: 16 * 1024 * 1024,
    resource.RLIMIT_AS: 1024 * 1024 * 1024,
}

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RealRun(unittest.TestCase):
    """The set-up shared by the tests that run a real script in the real boundary."""

    def setUp(self):
        the_boundary.require(self)
        self.limits = dict(DEFAULT_LIMITS)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.records = os.path.join(self.root, "records")
        self.records_folders = [self.records]  # every records folder a run of this test uses
        self.place = os.path.join(self.root, "place")
        os.mkdir(self.records)
        real_place.make_checkout(self.place)

    def script(self, name, text):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def pipe(self, name):
        path = os.path.join(self.root, name)
        os.mkfifo(path)
        return path

    def document(self, script, arguments=(), request_id="r-1", limit=60):
        return {
            "format_version": 1,
            "request_id": request_id,
            "records_location": self.records,
            "place": self.place,
            "thread": "t",
            "round": 1,
            "kind": "plain",
            "time_limit_seconds": limit,
            "executor": {
                "name": "command",
                "settings": {"command": sys.executable, "arguments": [script, *arguments]},
            },
        }

    def limited(self):
        """Runs in the child just before it execs: the limits are inherited by what it starts,
        through the scope tool and the boundary, so the executor is held to them too."""
        for which, size in self.limits.items():
            resource.setrlimit(which, (size, size))

    def raise_limit(self, which, size, why):
        """One test's own larger limit. `why` is the reason, stated at the call."""
        assert why, "a raised limit needs its reason"
        self.limits[which] = size

    def start(self, doc, path_first=None, variables=None, form="run", root=None):
        """The real command, started; the caller waits for it with `communicate`. With
        `path_first`, that folder comes first on the command's PATH; `variables` are added to its
        environment; `form` is the command's name (`run` unless given) and `root` the folder the
        input document is written in (`self.root` unless given). The command and what it starts
        run under `self.limits` (DEFAULT_LIMITS unless the test raised one)."""
        path = os.path.join(root or self.root, f"{doc['request_id']}.input.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        proc = subprocess.Popen(
            [sys.executable, "-m", "shuttle", form, path],
            cwd=REPO,
            env={**self.environment(path_first), **(variables or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=self.limited,
        )
        self.addCleanup(self.end, doc["request_id"], proc)
        return proc

    @staticmethod
    def environment(path_first):
        environment = dict(os.environ)
        if path_first:
            environment["PATH"] = path_first + os.pathsep + environment.get("PATH", "")
        return environment

    def end(self, request_id, proc):
        """Nothing a test started outlives it."""
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        for unit in self.units_left():  # only the units this test's own runs made
            subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True)
            subprocess.run(["systemctl", "--user", "reset-failed", unit], capture_output=True)

    def run_to_the_end(self, doc, path_first=None, variables=None):
        """Run the command to its end: (exit code, standard output lines, standard error)."""
        proc = self.start(doc, path_first, variables)
        stdout, stderr = proc.communicate(timeout=120)
        return proc.returncode, stdout.splitlines(), stderr

    def outcome(self, request_id="r-1", records=None):
        with open(os.path.join(records or self.records, f"{request_id}.outcome.json")) as f:
            return json.load(f)

    def run_part(self, request_id="r-1", records=None):
        """The run's own part of its scope names, read from its request record."""
        path = os.path.join(records or self.records, f"{request_id}.request.json")
        with open(path) as f:
            return boundary.run_part_of(json.load(f))

    def run_parts(self):
        """The part of every run whose request record is in a records folder of this test."""
        parts = []
        for records in self.records_folders:
            try:
                names = sorted(os.listdir(records))
            except FileNotFoundError:
                continue  # the test's folder is already gone, and its records with it
            for name in names:
                if name.endswith(".request.json"):
                    parts.append(self.run_part(name[: -len(".request.json")], records))
        return parts

    def units_left(self):
        """The loaded units (failed ones too) of the runs this test's records hold. Units of
        other tests, other suites and other users of the machine are not looked at."""
        done = subprocess.run(
            ["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", "shuttle-*"],
            capture_output=True,
            text=True,
        )
        parts = self.run_parts()
        names = [line.split()[0] for line in done.stdout.splitlines() if line.split()]
        return [name for name in names if any(part in name for part in parts)]

    def scope_state(self, request_id="r-1", records=None):
        """The state of the executor's scope of the run of `request_id` in this test's records."""
        name = boundary.scope_name(request_id, self.run_part(request_id, records))
        done = subprocess.run(
            ["systemctl", "--user", "is-active", boundary.unit_of(name)],
            capture_output=True,
            text=True,
        )
        return done.stdout.strip()

    def marker(self, label):
        """A string for a child process to carry in its command line so the test can count it:
        the label and the name of this test's own temporary folder, so another suite's test of
        the same kind (counting machine-wide in `processes_with`) never sees it."""
        return f"{label}-{os.path.basename(self.root)}"

    def processes_with(self, marker):
        """How many processes on this machine carry `marker` in their command line."""
        found = 0
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == os.getpid():
                continue
            try:
                with open(f"/proc/{name}/cmdline", "rb") as f:
                    found += marker.encode() in f.read()
            except OSError:
                continue  # it ended while looked at
        return found
