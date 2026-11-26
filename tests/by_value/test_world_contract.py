"""The contract cases (tests/rehearsal/contract.py) against the simulated world, by value.

No disk, no process and no time passes. The real half is tests/command/test_world_contract.py.
"""

import importlib
import os
import sys
import unittest

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TESTS)

contract = importlib.import_module("rehearsal.contract")
simulated = importlib.import_module("rehearsal.simulated_world")


class SimulatedHarness:
    def __init__(self, world):
        self.world = world
        self.folders = 0

    def folder(self):
        self.folders += 1
        return self.world.make_folder(f"/area/folder-{self.folders}")

    def names_in(self, folder):
        return self.world.names_in(folder)

    def end(self, process):
        """Kill the child, as the real half does."""
        if process.returncode is None:
            process.returncode = -9

    def argv(self, kind, report=None, fd=None):
        behaviours = {
            "exits_at_once": {},
            "exits_with_three": {"exit_code": 3},
            "sleeps": {"hangs": True},
            "reports_streams": {},
            "reports_session": {},
            "writes_to_the_report": {"report": "hello\n"},
        }
        if kind in behaviours:
            self.world.program(kind, **behaviours[kind])
        return [kind]  # "not_a_program" is never registered

    # The simulated world runs no program, so what a started child sees of its streams and
    # session is what the simulated `start` is declared to give it: the same as the real one.
    def streams_the_child_saw(self):
        return ("null", "null", "null")

    def session_the_child_saw(self):
        return (True, True)

    def make_a_name_that_leads_nowhere(self, path):
        self.world.put_a_name_that_leads_nowhere(path)

    def make_a_link(self, path, leads_to):
        self.world.put_link(path, leads_to)
        return path

    def make_a_pipe(self, path):
        self.world.put_pipe(path)
        return path

    def a_device(self):
        self.world.put_device("/dev/zero")
        return "/dev/zero"

    def host_name(self):
        return self.world.host

    def environment(self):
        return {"PATH": "/bin"}

    def have_previous_handler(self, handler):
        self.world.have_previous_handler(handler)

    def send(self, name):
        self.world.deliver(name)

    def set_variable(self, name, value):
        self.world.variables[name] = value


class SimulatedWorldHoldsTheContract(contract.ContractCases, unittest.TestCase):
    def setUp(self):
        self.simulated = simulated.SimulatedWorld()
        self.world = self.simulated.operations
        self.harness = SimulatedHarness(self.simulated)

    def test_a_signal_that_is_not_one_of_the_handled_is_not_handed_to_the_handler(self):
        # the real half shows that only the handled ones are installed (it cannot send the others)
        calls = []
        self.world.signals.install(calls.append)
        for name in ("SIGPIPE", "SIGCHLD"):
            self.simulated.deliver(name)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
