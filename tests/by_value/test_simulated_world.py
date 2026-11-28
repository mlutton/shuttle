"""By value: the simulated world counts every operation of the record and can fail every one.

The sweep in test_injection.py fails each call the run makes; it can only reach an operation the
simulated world counts. This test reads the fields of `Operations` itself, so an operation cannot
be added to the record without the simulated world counting it, being able to fail it, and a row
here saying how to call it.
"""

import contextlib
import importlib
import os
import sys
import unittest

from shuttle.core import place, shapes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
simulated = importlib.import_module("rehearsal.simulated_world")

# How to call each operation: its arguments (None: the handle `start` returned, the first).
CALLS = {
    "files.read": ("/f",),
    "files.read_lines": ("/f", 5),
    "files.exists": ("/f",),
    "files.write_new": ("/f", "text"),
    "files.link": ("/f", "/g"),
    "files.copy": ("/f", "/h"),
    "files.hash": ("/f",),
    "files.remove": ("/f",),
    "files.usable_folder": ("/f",),
    "files.is_folder": ("/f",),
    "files.temporary_folder": (),
    "files.make_private_folder": ("/g/area",),
    "files.create_lock": ("/g/area.lock",),
    "files.try_lock": ("/f",),
    "files.release_lock": ("/f", False),
    "files.list_names": ("/g", "area-"),
    "files.look_at": ("/f",),
    "files.make_folders": ("/g/h",),
    "files.copy_path": ("/f", "/h", ["x"]),
    "files.make_writable": ("/f",),
    "files.remove_tree": ("/f",),
    "processes.find_program": ("tool",),
    "processes.start": (["tool"], {}, None, "/f"),
    "processes.poll": (None,),
    "processes.wait": (None, 0.01),
    "processes.open_report": (),
    "processes.read_report": (None,),
    "boundary.show": ("u.scope", ("ActiveState",)),
    "boundary.stop": ("u.scope",),
    "boundary.forget": ("u.scope",),
    "boundary.list_units": ("shuttle-*",),
    "boundary.resolve": ("/f",),
    "boundary.try_memory_cap": (67108864, 0),
    "clock.now": (),
    "clock.timestamp": (),
    "signals.install": (print,),
    "signals.name_of": (15,),
    "environment.read_variable": ("PATH",),
    "identity.host_name": (),
    "identity.new_id": (),
    "identity.process_number": (),
    "identity.home_folder": (),
    "identity.runtime_folder": (),
    "git.look_at_place": ("/place", {}),
    "git.git_folders": ("/place", {}),
    "git.freeze": (
        [
            "systemd-run",
            "--unit=u",
            "--",
            "sh",
            "-c",
            place.FREEZE_SCRIPT,
            "sh",
            "/place",
            "a" * 40,
            "ref",
            "m",
        ],
        {},
    ),
}


def every_operation():
    """group.field for every function of the Operations record, read from the record itself."""
    return [
        f"{group}.{name}"
        for group, kind in zip(
            shapes.Operations._fields, shapes.Operations.__annotations__.values(), strict=True
        )
        for name in kind._fields
    ]


def a_world():
    world = simulated.SimulatedWorld()
    world.program("tool")
    child = world.operations.processes.start(["tool"], {})
    world.counts.clear()
    return world, child


def call(world, child, operation):
    group, name = operation.split(".")
    function = getattr(getattr(world.operations, group), name)
    arguments = tuple(child if a is None else a for a in CALLS[operation])
    return function(*arguments)


class EveryOperationIsCountedAndCanBeFailed(unittest.TestCase):
    def test_the_table_has_a_row_for_each_operation_of_the_record_and_no_other(self):
        self.assertEqual(sorted(CALLS), sorted(every_operation()))
        self.assertGreaterEqual(len(CALLS), 21)

    def test_each_operation_is_counted_when_called(self):
        for operation in every_operation():
            with self.subTest(operation):
                world, child = a_world()
                with contextlib.suppress(OSError):  # a file operation on a name not there
                    call(world, child, operation)
                self.assertEqual(world.counts.get(operation), 1)

    def test_each_operation_can_be_told_to_raise_and_then_does_nothing_else(self):
        for operation in every_operation():
            with self.subTest(operation):
                world, child = a_world()
                world.will_raise(operation, RuntimeError("injected"))
                with self.assertRaises(RuntimeError):
                    call(world, child, operation)
                self.assertEqual(world.counts.get(operation), 1)

    def test_each_operation_can_have_a_function_run_just_before_it(self):
        for operation in every_operation():
            with self.subTest(operation):
                world, child = a_world()
                seen = []
                world.on_call(operation, lambda seen=seen: seen.append(1))
                with contextlib.suppress(OSError):
                    call(world, child, operation)
                self.assertEqual(seen, [1])


if __name__ == "__main__":
    unittest.main()
