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
import sys
import tempfile
import time
import unittest

from shuttle.world import real

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TESTS)

contract = importlib.import_module("rehearsal.contract")

REPORTS_STREAMS = (
    "import os, sys\n"
    "def kind(fd):\n"
    "    return 'null' if os.path.samestat(os.fstat(fd), os.stat(os.devnull)) else 'other'\n"
    "open(sys.argv[1], 'w').write(' '.join(kind(fd) for fd in (0, 1, 2)))\n"
)
REPORTS_SESSION = (
    "import os, sys\nopen(sys.argv[1], 'w').write(f'{os.getsid(0)} {os.getpgid(0)}')\n"
)
IGNORES_THE_ASK = (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "open(sys.argv[1], 'w').close()\n"
    "time.sleep(60)\n"
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

    def argv(self, kind, ready=None, report=None):
        self.last_report = report or getattr(self, "last_report", None)
        python = sys.executable
        return {
            "exits_at_once": [python, "-c", "pass"],
            "exits_with_three": [python, "-c", "import sys; sys.exit(3)"],
            "sleeps": [python, "-c", "import time; time.sleep(60)"],
            "ignores_the_ask": [python, "-c", IGNORES_THE_ASK, ready],
            "reports_streams": [python, "-c", REPORTS_STREAMS, report],
            "reports_session": [python, "-c", REPORTS_SESSION, report],
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

    def have_previous_handler(self, handler):
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
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
        report = os.path.join(self.harness.folder(), "report")
        script = "import json, os, sys\njson.dump(sorted(os.environ), open(sys.argv[1], 'w'))\n"
        environment = {"PATH": os.environ["PATH"], "SHUTTLE_ONLY": "1"}
        process = self.world.processes.start([sys.executable, "-c", script, report], environment)
        self.addCleanup(self.stop, process)
        self.assertTrue(contract.until(self.world, lambda: self.world.processes.poll(process) == 0))
        with open(report) as f:
            seen = json.load(f)
        # the interpreter may add LC_CTYPE and the like; nothing of the caller's may leak
        self.assertIn("SHUTTLE_ONLY", seen)
        self.assertNotIn("HOME", seen)
        self.assertEqual([n for n in seen if n in os.environ and n not in environment], [])

    def test_installing_changes_the_handlers_of_the_three_signals_and_no_other(self):
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
        self.assertEqual(changed, {"SIGINT", "SIGTERM", "SIGHUP"})

    def test_the_process_number_is_this_processs(self):
        self.assertEqual(self.world.identity.process_number(), os.getpid())

    def test_the_steady_clock_is_the_monotonic_clock(self):
        self.assertAlmostEqual(self.world.clock.now(), time.monotonic(), delta=1.0)
        self.assertNotAlmostEqual(self.world.clock.now(), time.time(), delta=1000.0)


if __name__ == "__main__":
    unittest.main()
