"""The contract cases (tests/rehearsal/contract.py) against the real operations.

Command-seam tests: a temporary folder the test makes, real short-lived child processes (a
Python interpreter running a line or two), and the test process's own signals, each put back
as it was. The simulated half is tests/by_value/test_world_contract.py.
"""

import contextlib
import fcntl
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
            "copies_its_input": [
                python,
                "-c",
                "import sys; open(sys.argv[1], 'wb').write(sys.stdin.buffer.read())",
                report,
            ],
            "prints_hello": [python, "-c", "print('hello')"],
            "not_a_program": [os.path.join(self.root, "no-such-program")],
        }[kind]

    def what_the_child_read(self):
        with open(self.last_report, "rb") as f:
            return f.read()

    def everything_below(self, folder):
        found = []
        for where, names, files in os.walk(folder):
            for name in [*names, *files]:
                path = os.path.join(where, name)
                kind = "@" if os.path.islink(path) else "/" if os.path.isdir(path) else ""
                found.append(os.path.relpath(path, folder) + kind)
        return sorted(found)

    def is_a_link(self, path):
        return os.path.islink(path)

    def make_read_only(self, path):
        os.chmod(path, os.stat(path).st_mode & ~0o222)

    def is_writable(self, path):
        return bool(os.stat(path).st_mode & 0o200)

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

    def make_a_link(self, path, leads_to):
        os.symlink(leads_to, path)
        return path

    def make_a_pipe(self, path):
        """A named pipe nobody writes. A call that waits on it fails after a bounded wait (an
        alarm that raises) instead of hanging the run; the alarm is put away with the test."""
        os.mkfifo(path)
        self.guard_against_waiting()
        return path

    def a_device(self):
        self.guard_against_waiting()
        return "/dev/zero"  # reads without end

    def guard_against_waiting(self):
        def blocked(number, frame):
            raise AssertionError("a call waited on, or read without end from, a pipe or device")

        was = signal.signal(signal.SIGALRM, blocked)
        signal.alarm(60)
        self.case.addCleanup(signal.signal, signal.SIGALRM, was)
        self.case.addCleanup(signal.alarm, 0)

    def hold_the_lock_elsewhere(self, path):
        """A lock held on its own open description, as another process holds one: a lock on the
        same file by a second open conflicts with it, in this process or any other."""
        descriptor = os.open(path, os.O_RDONLY)
        self.case.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def a_name_owned_by_another_user(self):
        return "/" if os.geteuid() != 0 else None

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

    def filter_attribute(self, where, name):
        real_place.write(where, ".gitattributes", f"{name} filter=anything\n")
        real_place.commit_everything(where)

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

    # What only a real process can show about a lock: the kernel gives it back when the holder
    # dies, a hard kill included, and a child the holder started never keeps it.

    HOLDS_A_LOCK_AND_STARTS_A_CHILD = (
        "import subprocess, sys\n"
        "from shuttle.world import files\n"
        "files.create_lock(sys.argv[1])\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n"
        "sys.stdin.read()\n"
    )

    def test_a_lock_is_free_when_its_holder_is_killed_though_a_child_it_started_lives_on(self):
        lock = os.path.join(self.harness.folder(), "area.lock")
        holder = subprocess.Popen(
            [sys.executable, "-c", self.HOLDS_A_LOCK_AND_STARTS_A_CHILD, lock],
            cwd=os.path.dirname(TESTS),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.stdin.close)
        child = int(holder.stdout.readline())  # the line says the lock is held and the child is up
        self.addCleanup(self.stop_a_child, child)
        self.assertIs(self.world.files.try_lock(lock), False)
        holder.kill()
        holder.wait()
        os.kill(child, 0)  # the child it started is still there
        self.assertIs(self.world.files.try_lock(lock), True)
        self.world.files.release_lock(lock, True)

    @staticmethod
    def stop_a_child(pid):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)

    def test_a_lock_taken_and_let_go_is_free_for_a_second_open_of_the_same_file(self):
        lock = os.path.join(self.harness.folder(), "area.lock")
        self.world.files.create_lock(lock)
        descriptor = os.open(lock, os.O_RDONLY)
        self.addCleanup(os.close, descriptor)
        with self.assertRaises(BlockingIOError):
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.world.files.release_lock(lock, False)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_a_lock_file_is_a_regular_file_only_its_owner_can_use_and_a_private_folder_likewise(
        self,
    ):
        folder = self.harness.folder()
        self.world.files.create_lock(os.path.join(folder, "area.lock"))
        self.world.files.make_private_folder(os.path.join(folder, "area"))
        self.assertEqual(os.stat(os.path.join(folder, "area.lock")).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.join(folder, "area")).st_mode & 0o777, 0o700)
        self.world.files.release_lock(os.path.join(folder, "area.lock"), True)

    def test_the_temporary_folder_is_the_one_the_environment_names_with_links_resolved(self):
        folder = self.harness.folder()
        link = os.path.join(self.harness.folder(), "link")
        os.symlink(folder, link)
        self.harness.set_variable("TMPDIR", link)
        self.assertEqual(self.world.files.temporary_folder(), os.path.realpath(folder))


if __name__ == "__main__":
    unittest.main()
