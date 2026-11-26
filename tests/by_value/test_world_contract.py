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

    def argv(self, kind, ready=None):
        behaviours = {
            "exits_at_once": {"exits_after": 0},
            "exits_with_three": {"exits_after": 0, "exit_code": 3},
            "sleeps": {},
            "ignores_the_ask": {"obeys": ("kill",), "creates": (ready,) if ready else ()},
        }
        if kind in behaviours:
            self.world.program(kind, **behaviours[kind])
        return [kind]  # "not_a_program" is never registered

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


if __name__ == "__main__":
    unittest.main()
