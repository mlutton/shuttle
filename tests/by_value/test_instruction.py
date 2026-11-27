"""By value, through the whole run on the simulated world: how the instruction reaches the
executor. It is put in a file in the run area and given as the executor's standard input, with the
notice after it; it is never on the command line. A kind that expects a statement must have one.
"""

import hashlib
import importlib
import os
import sys
import unittest

from shuttle.core import fixed, run_area

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

TEXT = "Do the thing; $HOME 'quoted' \"and\" `ticks`\nsecond line\n"
LOCATION = "/out/statement.json"


def given(world):
    """What the executor was given on its standard input, as text."""
    return world.children[-1].input.decode("utf-8")


class TheInstruction(unittest.TestCase):
    def test_a_plain_kind_with_an_instruction_gets_it_and_the_notice_without_a_statement_part(self):
        doc = scenes.document(
            instruction=TEXT, instruction_hash=hashlib.sha256(TEXT.encode()).hexdigest()
        )
        world = scenes.scene(doc)
        code, _, err = scenes.run_in(world)
        self.assertEqual((code, err), (0, ""))
        got = given(world)
        self.assertTrue(got.startswith(TEXT + "\n"))
        self.assertIn(f"Shuttle notice, version {fixed.NOTICE_VERSION}", got)
        self.assertIn("cannot commit in the place", got)
        self.assertNotIn("Write your statement", got)

    def test_a_plain_kind_with_no_instruction_gets_the_notice_alone(self):
        world = scenes.scene()
        scenes.run_in(world)
        self.assertTrue(given(world).startswith("Shuttle notice"))

    def test_a_kind_that_expects_a_statement_gets_its_part_with_the_location(self):
        world = scenes.scene(scenes.document(kind="judge", statement_location=LOCATION))
        scenes.run_in(world)
        got = given(world)
        self.assertTrue(got.startswith("Do the task.\n\nShuttle notice"))
        self.assertIn(f"Write your statement as one JSON file at this exact path: {LOCATION}", got)

    def test_references_are_named_in_the_notice_of_every_kind(self):
        text = "the runbook"
        reference = {
            "name": "runbook",
            "path": "/refs/runbook.md",
            "hash": hashlib.sha256(text.encode()).hexdigest(),
            "size": len(text),
            "hash_source": "caller",
        }
        world = scenes.scene(scenes.document(references=[reference]))
        world.put_file("/refs/runbook.md", text)
        scenes.run_in(world)
        self.assertIn("- runbook: /refs/runbook.md", given(world))

    def test_it_is_given_by_a_file_in_the_run_area_and_never_on_the_command_line(self):
        doc = scenes.document(
            instruction=TEXT, instruction_hash=hashlib.sha256(TEXT.encode()).hexdigest()
        )
        world = scenes.scene(doc)
        scenes.run_in(world)
        ((argv, _),) = world.started[-1:]
        self.assertFalse(any("Do the thing" in part or "Shuttle notice" in part for part in argv))
        ((arguments, _),) = world.calls("processes.start")[-1:]
        area = world.calls("files.make_temporary_folder")
        self.assertEqual(len(area), 1)
        self.assertTrue(arguments[2].endswith("/" + run_area.INSTRUCTION_NAME))
        self.assertTrue(arguments[2].startswith("/tmp/" + run_area.AREA_PREFIX))
        self.assertFalse(world.files.get(arguments[2]))  # removed with the area

    def test_a_kind_that_expects_a_statement_with_no_instruction_is_refused_before_anything_runs(
        self,
    ):
        doc = scenes.document(kind="judge", statement_location=LOCATION)
        for field in ("instruction", "instruction_hash"):
            del doc[field]
        world = scenes.scene(doc)
        scenes.run_in(world)
        ending = flat(scenes.outcome(world)["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "missing_setting", "input_check"),
        )
        self.assertEqual(world.children, [])

    def test_an_instruction_given_without_its_hash_is_refused_for_either_kind(self):
        for kind in ("plain", "judge"):
            with self.subTest(kind):
                doc = scenes.document(kind=kind, instruction="x")
                doc.pop("instruction_hash", None)
                if kind == "judge":
                    doc["statement_location"] = LOCATION
                world = scenes.scene(doc)
                scenes.run_in(world)
                ending = flat(scenes.outcome(world)["receipt"])["ending"]
                self.assertEqual(ending["reason"], "instruction_hash_mismatch")


if __name__ == "__main__":
    unittest.main()
