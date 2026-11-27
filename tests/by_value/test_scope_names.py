"""By value: the names of the scopes a run makes. Each carries a part that is the run's own, so
no two runs, and no check of the same document, ask systemd for the same name.

The part is the id of the run's request record, which a later command reads back from the record.
The real boundary's side of this (two runs at once, a unit of an old name held by something else,
a check during a run's gates) is in tests/boundary/test_scope_names.py.
"""

import importlib
import io
import json
import os
import re
import sys
import unittest

from shuttle.core import boundary, fixed
from shuttle.shell import check_form

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")

GATE = {"name": "quota", "command": "gate", "arguments": [], "limit_seconds": 5}
A_PART = "0123456789abcdef0123456789abcdef"
# What systemd takes in a unit name's first part: ASCII letters, digits and ":-_.\" (not more than
# 255 characters with the suffix).
UNIT_NAME = re.compile(r"[A-Za-z0-9:_.\\-]+")


def units_started(world):
    """The unit names asked of the scope tool, from the processes and the freeze."""
    commands = [args[0] for args, _ in world.calls("processes.start")]
    commands += [args[0] for args, _ in world.calls("git.freeze")]
    return [
        part[len("--unit=") :]
        for command in commands
        for part in command
        if part.startswith("--unit=")
    ]


def another_place(world, records, place):
    """The document the scene holds, moved to another records folder and place."""
    doc = json.loads(world.text_of(scenes.DOCUMENT))
    doc["records_location"], doc["place"] = records, place
    world.make_folder(records)
    world.make_place(place, {"README": "the place\n"})
    world.put_file(scenes.DOCUMENT, json.dumps(doc))


class TheNamesAreMadeOfTheRequestAndTheRunsPart(unittest.TestCase):
    def test_each_kind_of_scope_has_the_request_and_the_part_in_its_name(self):
        self.assertEqual(boundary.scope_name("r-1", "p"), "shuttle-run-r-1-p")
        self.assertEqual(boundary.gate_scope_name("r-1", "p", 2), "shuttle-gate-r-1-p-2")
        self.assertEqual(boundary.freeze_scope_name("r-1", "p"), "shuttle-freeze-r-1-p")

    def test_every_request_id_the_code_accepts_makes_a_valid_unit_name_within_the_length(self):
        longest = fixed.ID_CHARACTERS * 2
        for request_id in (*fixed.ID_CHARACTERS, longest[:64]):
            names = (
                boundary.scope_name(request_id, A_PART),
                boundary.gate_scope_name(request_id, A_PART, 99),
                boundary.freeze_scope_name(request_id, A_PART),
            )
            for name in names:
                with self.subTest(name=name):
                    self.assertRegex(boundary.unit_of(name), UNIT_NAME)
                    self.assertLessEqual(len(boundary.unit_of(name)), 255)

    def test_the_runs_part_is_read_back_from_its_request_record(self):
        record = {"header": {"record_id": A_PART, "request_id": "r-1"}, "input": "{}"}
        self.assertEqual(boundary.run_part_of(record), A_PART)
        for bad in ({}, {"header": []}, {"header": {"record_id": 3}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError if bad else KeyError):
                boundary.run_part_of(bad)


class ARunsScopes(unittest.TestCase):
    def a_run(self):
        world = scenes.scene(scenes.document(gates=[GATE]))
        world.program("gate")
        scenes.run_in(world)
        return world

    def test_all_three_kinds_carry_the_part_the_request_record_holds(self):
        world = self.a_run()
        part = scenes.run_part(world)
        names = units_started(world)
        self.assertEqual(
            sorted(names),
            sorted(
                [
                    boundary.gate_scope_name("inj-1", part, 0),
                    boundary.scope_name("inj-1", part),
                    boundary.freeze_scope_name("inj-1", part),
                ]
            ),
        )

    def test_the_run_leaves_no_unit_of_its_own(self):
        self.assertEqual(self.a_run().units, {})

    def test_two_runs_of_one_request_id_in_two_records_locations_share_no_name(self):
        world = self.a_run()
        another_place(world, "/records-2", "/place-2")
        scenes.run_in(world)
        every = units_started(world)
        self.assertEqual(len(every), 6)
        self.assertEqual(len(set(every)), 6)


class ACheckOfTheSameDocument(unittest.TestCase):
    def test_makes_gate_scopes_that_a_run_of_the_document_does_not(self):
        doc = scenes.document(gates=[GATE])
        world = scenes.scene(doc)
        world.program("gate")
        scenes.run_in(world)
        run_names = set(units_started(world))
        world.log.clear()
        world.put_file(scenes.DOCUMENT, json.dumps({**doc, "request_id": "inj-1"}))
        another_place(world, "/records-2", "/place-2")
        check_form.check(scenes.DOCUMENT, io.StringIO(), io.StringIO(), world.operations)
        checked = units_started(world)
        self.assertEqual(len(checked), 1)
        self.assertTrue(checked[0].startswith("shuttle-gate-inj-1-"))
        self.assertNotIn(checked[0], run_names)
        self.assertEqual(world.units, {})


if __name__ == "__main__":
    unittest.main()
