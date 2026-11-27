"""A real run of the command against the real boundary, for the tests under tests/boundary/.

Everything is in one temporary root: the records folder, the place the scripts may write, and the
scripts. A script says it is up through a named pipe the test reads, so no test polls or sleeps.
"""

import hashlib
import json
import os
import resource
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from shuttle.core import boundary
from shuttle.core.drivers import table

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


# What the boundary needs on a PATH besides a stand-in's folder: the system's own two folders.
SYSTEM_PATH = ("/usr/bin", "/bin")

# The interpreter a script runs under inside the box, and the folder that holds it and its
# libraries. The suite's own interpreter is a link from a virtual environment (or a copy of one
# under the hosted runner's tool cache), which the box hides, so a run names the real file and
# lists its installation as visible (the way a caller does for a tool installed in a hidden
# folder). On a machine where it is under /usr this lists a folder the box already shows.
INTERPRETER = os.path.realpath(sys.executable)
INTERPRETER_FOLDERS = (os.path.realpath(sys.base_prefix),)


def tool_driver_names():
    """The names of the drivers whose tool is a program of its own, not the plain command."""
    return sorted(name for name in table.DRIVERS if name != "command")


class RealRun(unittest.TestCase):
    """The set-up shared by the tests that run a real script in the real boundary."""

    # The folder the test's own folders are made in; None is the machine's temporary folder. A
    # test of where the box's paths may live sets it to another.
    ROOT_PARENT: str | None = None

    def setUp(self):
        the_boundary.require(self)
        self.limits = dict(DEFAULT_LIMITS)
        tmp = tempfile.TemporaryDirectory(dir=self.ROOT_PARENT)
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.records = os.path.join(self.root, "records")
        self.records_folders = [self.records]  # every records folder a run of this test uses
        self.place = os.path.join(self.root, "place")
        # What the executor may read but not write, listed as visible in every document: its
        # scripts, the pipes it says it is up through (a named pipe can be written to where a file
        # cannot) and the stand-in tool. The test's root is not: it holds the records.
        self.support = os.path.join(self.root, "support")
        os.mkdir(self.records)
        os.mkdir(self.support)
        real_place.make_checkout(self.place)

    def script(self, name, text):
        path = os.path.join(self.support, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def pipe(self, name):
        path = os.path.join(self.support, name)
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
            "reach": {"visible": [self.support, *INTERPRETER_FOLDERS]},
            "executor": {
                "name": "command",
                "settings": {"command": INTERPRETER, "arguments": [script, *arguments]},
            },
        }

    @staticmethod
    def expecting_a_statement(doc, location, instruction="Do the task."):
        """The document as a kind that expects a statement takes it: the kind, where the statement
        goes, and the instruction with its hash, which that kind must have."""
        doc["kind"], doc["statement_location"] = "judge", location
        doc["instruction"] = instruction
        doc["instruction_hash"] = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
        return doc

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

    def run_a_stand_in_tool(self, doc, script, variables=None, path_first=None):
        """Run the command on `doc` with `script` standing in for the executor driver's tool. It is
        the way to do that, because it checks where the program resolves before anything starts.

        The script (a Python program's text) is written into this test's own folder under the
        program name the driver asks for (`program(settings)` of the driver the document names),
        and the command runs with a PATH of that folder, then only the system's. Before anything
        starts the program is looked up on exactly that PATH and must be the file just written,
        inside this test's folder: anywhere else, or nowhere, fails the test and starts nothing.
        `path_first` puts a folder of the test's own ahead of the stand-in's, which only a test
        of the guard has use for. Returns what `run_to_the_end` does."""
        executor = doc["executor"]
        program = table.DRIVERS[executor["name"]].program(executor["settings"])
        folder = os.path.join(self.support, "stand-in")
        os.makedirs(folder, exist_ok=True)
        written = os.path.join(folder, program)
        with open(written, "w") as f:
            f.write(f"#!{INTERPRETER}\n{script}")
        os.chmod(written, os.stat(written).st_mode | stat.S_IXUSR)
        path = os.pathsep.join([*([path_first] if path_first else []), folder, *SYSTEM_PATH])
        found = shutil.which(program, path=path)
        inside = os.path.realpath(written).startswith(self.root + os.sep)
        if found is None or os.path.realpath(found) != os.path.realpath(written) or not inside:
            self.fail(f"the program {program!r} does not resolve to the stand-in written for it")
        # The stand-in's folder is under the support folder, which every document made here lists
        # as visible; a document of the test's own is given the same reach.
        reach = doc.setdefault("reach", {})
        reach["visible"] = [*reach.get("visible", []), self.support, *INTERPRETER_FOLDERS]
        return self.run_to_the_end(doc, variables={**(variables or {}), "PATH": path})

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
