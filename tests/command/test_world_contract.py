"""The contract cases (tests/rehearsal/contract.py) against the real operations.

Command-seam tests: a temporary folder the test makes, real short-lived child processes (a
Python interpreter running a line or two), and the test process's own signals, each put back
as it was. The simulated half is tests/by_value/test_world_contract.py.
"""

import importlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import unittest

from shuttle.core import boundary, place
from shuttle.world import real

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TESTS)

contract = importlib.import_module("rehearsal.contract")
real_place = importlib.import_module("rehearsal.real_place")
the_boundary = importlib.import_module("rehearsal.the_boundary")

REPORTS_STREAMS = (
    "import os, sys\n"
    "def kind(fd):\n"
    "    return 'null' if os.path.samestat(os.fstat(fd), os.stat(os.devnull)) else 'other'\n"
    "open(sys.argv[1], 'w').write(' '.join(kind(fd) for fd in (0, 1, 2)))\n"
)
REPORTS_SESSION = (
    "import os, sys\nopen(sys.argv[1], 'w').write(f'{os.getsid(0)} {os.getpgid(0)}')\n"
)


class RealHarness:
    def __init__(self, case):
        self.case = case
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.folders = 0

    def folder(self):
        self.folders += 1
        path = os.path.join(self.root, f"folder-{self.folders}")
        os.mkdir(path)
        return path

    def names_in(self, folder):
        return sorted(os.listdir(folder))

    def end(self, process):
        process.kill()

    def argv(self, kind, report=None, fd=None):
        self.last_report = report or getattr(self, "last_report", None)
        python = sys.executable
        return {
            "exits_at_once": [python, "-c", "pass"],
            "exits_with_three": [python, "-c", "import sys; sys.exit(3)"],
            "sleeps": [python, "-c", "import time; time.sleep(60)"],
            "reports_streams": [python, "-c", REPORTS_STREAMS, report],
            "reports_session": [python, "-c", REPORTS_SESSION, report],
            "writes_to_the_report": [
                python,
                "-c",
                "import os, sys; os.write(int(sys.argv[1]), b'hello\\n')",
                str(fd),
            ],
            "not_a_program": [os.path.join(self.root, "no-such-program")],
        }[kind]

    def streams_the_child_saw(self):
        return tuple(self.reported().split())

    def session_the_child_saw(self):
        session, group = (int(n) for n in self.reported().split())
        return (session == os.getsid(0), group == os.getpgid(0))

    def reported(self):
        with open(self.last_report) as f:
            return f.read()

    def make_a_name_that_leads_nowhere(self, path):
        os.symlink(os.path.join(self.root, "nowhere"), path)

    def host_name(self):
        return socket.gethostname()

    def environment(self):
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}

    # ------------------------------------------------------------ a git checkout, for real

    def checkout(self, files=None, folder_name=None):
        folder = self.folder()
        where = os.path.join(folder, folder_name) if folder_name else folder
        return where, real_place.make_checkout(where, files or {"README": "x\n"})

    def edit(self, where, name, text):
        real_place.write(where, name, text)

    def remove(self, where, name):
        os.remove(os.path.join(where, name))

    def can_hold(self, where, name):
        try:
            self.edit(where, name, "")
            self.remove(where, name)
        except (OSError, ValueError):
            return False
        return True

    def nested_repository(self, where, name):
        folder = os.path.join(where, name)
        os.makedirs(folder, exist_ok=True)
        real_place.git(folder, "init", "-q")

    def commit_everything(self, where):
        return real_place.commit_everything(where)

    def everything_in(self, where):
        found = {}
        for folder, _, names in os.walk(where):
            for name in names:
                path = os.path.join(folder, name)
                with open(path, "rb") as f:
                    found[os.path.relpath(path, where)] = f.read()
        return found

    def needs_the_freeze(self):
        the_boundary.require(self.case)  # the freeze runs in a scope of its own

    def freeze_environment(self):
        environment = place.git_environment(os.environ["PATH"])
        for name in boundary.BUS_VARIABLES:
            if name in os.environ:
                environment[name] = os.environ[name]
        return environment

    def references(self, where):
        listing = real_place.git(
            where, "for-each-ref", "refs/shuttle", "--format=%(refname) %(objectname)"
        )
        return [tuple(line.split(" ")) for line in listing.splitlines()]

    def parent_of(self, where, commit):
        return real_place.git(where, "rev-parse", f"{commit}^")

    def files_of(self, where, commit):
        done = subprocess.run(
            ["git", "-C", where, "ls-tree", "-r", "--name-only", "-z", commit],
            env=real_place.environment(),
            capture_output=True,
            check=True,
        )
        return [os.fsdecode(name) for name in done.stdout.split(b"\0") if name]

    def have_previous_handler(self, handler):
        for number in (getattr(signal, name) for name in contract.HANDLED_SIGNALS):
            was = signal.signal(number, lambda n, frame: handler(signal.Signals(n).name))
            self.case.addCleanup(signal.signal, number, was)

    def send(self, name):
        signal.raise_signal(getattr(signal, name))

    def set_variable(self, name, value):
        was = os.environ.get(name)
        os.environ[name] = value
        self.case.addCleanup(self.put_back, name, was)

    @staticmethod
    def put_back(name, was):
        if was is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = was


class RealOperationsHoldTheContract(contract.ContractCases, unittest.TestCase):
    def setUp(self):
        self.world = real.OPERATIONS
        self.harness = RealHarness(self)

    # What only the real half can show: the simulated world runs no program and has no
    # operating system to compare with.

    def test_a_started_child_has_exactly_the_environment_it_was_given(self):
        # The interpreter adds variables of its own at start-up (LC_CTYPE when no locale is
        # set), so the child is compared with one started directly with the same environment:
        # whatever the interpreter adds, it adds to both, and anything of the caller's that
        # `start` let through would show only in the first.
        folder = self.harness.folder()
        started, direct = os.path.join(folder, "started"), os.path.join(folder, "direct")
        script = "import json, os, sys\njson.dump(sorted(os.environ), open(sys.argv[1], 'w'))\n"
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SHUTTLE_ONLY": "1"}
        subprocess.run([sys.executable, "-c", script, direct], env=environment, check=True)
        process = self.world.processes.start([sys.executable, "-c", script, started], environment)
        self.addCleanup(self.harness.end, process)
        self.assertTrue(contract.ended(self.world, process))
        with open(started) as f, open(direct) as g:
            seen, expected = json.load(f), json.load(g)
        self.assertEqual(seen, expected)
        self.assertIn("SHUTTLE_ONLY", seen)

    def test_installing_changes_the_handlers_of_the_handled_signals_and_no_other(self):
        before = {n: signal.getsignal(n) for n in signal.valid_signals() if n < signal.NSIG}
        restore = self.world.signals.install(lambda name: None)
        try:
            changed = {
                signal.Signals(n).name
                for n in before
                if signal.getsignal(n) is not before[n] and n != signal.SIGKILL
            }
        finally:
            restore()
        self.assertEqual(changed, set(contract.HANDLED_SIGNALS))

    def test_the_process_number_is_this_processs(self):
        self.assertEqual(self.world.identity.process_number(), os.getpid())

    def test_the_steady_clock_counts_from_an_arbitrary_start_not_from_1970(self):
        # A wall clock reads about 1.8e9 seconds in 2026; a monotonic clock reads the time since
        # boot or some such start, which is never that large.
        self.assertLess(self.world.clock.now(), 10**9)

    def test_a_path_is_resolved_to_an_absolute_one_with_links_followed(self):
        folder = os.path.realpath(self.harness.folder())
        os.mkdir(os.path.join(folder, "real"))
        os.symlink(os.path.join(folder, "real"), os.path.join(folder, "link"))
        self.assertEqual(
            self.world.boundary.resolve(os.path.join(folder, "link")),
            os.path.join(folder, "real"),
        )
        self.assertTrue(os.path.isabs(self.world.boundary.resolve("relative")))


if __name__ == "__main__":
    unittest.main()
