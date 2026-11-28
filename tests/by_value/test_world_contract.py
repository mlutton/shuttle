"""The contract cases (tests/rehearsal/contract.py) against the simulated world, by value.

No disk, no process and no time passes. The real half is tests/command/test_world_contract.py.
"""

import importlib
import os
import sys
import unittest

from shuttle.core import place

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
            "copies_its_input": {},
            "prints_hello": {"output": "hello\n"},
            "prints_to_error": {"error": "oops\n"},
        }
        if kind in behaviours:
            self.world.program(kind, **behaviours[kind])
        return [kind]  # "not_a_program" is never registered

    def what_the_child_read(self):
        return self.world.children[-1].input

    def everything_below(self, folder):
        found = []
        for name in self.world._below(folder):
            kind = "@" if name in self.world.links else "/" if name in self.world.folders else ""
            found.append(name[len(folder) + 1 :] + kind)
        return sorted(found)

    def mode_of(self, path):
        return self.world.mode_of(path)

    def is_a_link(self, path):
        return path in self.world.links

    def make_read_only(self, path):
        self.world.read_only.add(path)

    def is_writable(self, path):
        return path not in self.world.read_only

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

    def hold_the_lock_elsewhere(self, path):
        self.world.put_lock_held_elsewhere(path)

    def a_name_owned_by_another_user(self):
        path = self.folder()
        self.world.put_foreign(path)
        return path

    def host_name(self):
        return self.world.host

    def environment(self):
        return {"PATH": "/bin"}

    # ------------------------------------------------------- a git checkout, simulated

    def checkout(self, files=None, folder_name=None):
        folder = self.folder()
        where = f"{folder}/{folder_name}" if folder_name else folder
        return where, self.world.make_place(where, files or {"README": "x\n"})

    def edit(self, where, name, text):
        self.world.put_file(f"{where}/{name}", text)

    def remove(self, where, name):
        del self.world.files[f"{where}/{name}"]

    def can_hold(self, where, name):
        return True

    def nested_repository(self, where, name):
        self.world.places[where]["nested"].append(name)

    def filter_attribute(self, where, name):
        self.world.places[where]["filtered"].append(name)

    def commit_everything(self, where):
        return self.world.commit_everything(where)

    def everything_in(self, where):
        return {name: bytes(data) for name, data in self.world.files.items()}

    def needs_the_freeze(self):
        pass

    def freeze_environment(self):
        return place.git_environment("/bin")

    def references(self, where):
        return sorted(self.world.refs.items())

    def parent_of(self, where, commit):
        return self.world.commits[commit]["parent"]

    def files_of(self, where, commit):
        return list(self.world.commits[commit]["files"])

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
