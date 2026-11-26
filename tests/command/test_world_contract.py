"""The contract cases (tests/rehearsal/contract.py) against the real operations.

Command-seam tests: a temporary folder the test makes, real short-lived child processes (a
Python interpreter running a line or two), and the test process's own signals, each put back
as it was. The simulated half is tests/by_value/test_world_contract.py.
"""

import importlib
import os
import signal
import sys
import tempfile
import unittest

from shuttle.world import real

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TESTS)

contract = importlib.import_module("rehearsal.contract")

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

    def argv(self, kind, ready=None):
        python = sys.executable
        return {
            "exits_at_once": [python, "-c", "pass"],
            "exits_with_three": [python, "-c", "import sys; sys.exit(3)"],
            "sleeps": [python, "-c", "import time; time.sleep(60)"],
            "ignores_the_ask": [python, "-c", IGNORES_THE_ASK, ready],
            "not_a_program": [os.path.join(self.root, "no-such-program")],
        }[kind]

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


if __name__ == "__main__":
    unittest.main()
