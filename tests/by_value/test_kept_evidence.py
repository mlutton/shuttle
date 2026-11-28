"""By value: what a run keeps of the executor's own output, and what the receipt says of it.

The names and the reading of a failure are by value; the run is on the simulated world, through
the command driver and, for a final message, a driver that has one. The real command and the real
boundary are in tests/boundary/test_kept_evidence.py.
"""

import hashlib
import importlib
import os
import sys
import unittest

from shuttle.core import decisions, evidence, fixed, run_area
from shuttle.core.shapes import NotARegularFile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")

AREA = "/tmp/shuttle-run-area-" + f"{1:032x}"  # the first run's area: named for its run part
OUT, ERR = run_area.standard_output_path(AREA), run_area.standard_error_path(AREA)
KEPT_OUT = "/records/inj-1.standard-output.kept"
KEPT_ERR = "/records/inj-1.standard-error.kept"
KEPT_MESSAGE = "/records/inj-1.final-message.kept"
FIELDS = ("standard_output_kept", "standard_error_kept", "final_message_kept")
NOTHING = {"state": "none", "value": None}
CANNOT = {"state": "cannot tell", "value": None}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def held(path, text):
    return {"state": "value", "value": {"kept_at": path, "hash": sha(text)}}


class TheNamesAndTheReading(unittest.TestCase):
    def test_a_kept_name_follows_the_statements_and_is_never_the_name_of_a_record(self):
        names = [evidence.kept_name("req-1", kind) for kind in evidence.KINDS]
        self.assertEqual(
            names,
            [
                "req-1.standard-output.kept",
                "req-1.standard-error.kept",
                "req-1.final-message.kept",
            ],
        )
        for name in names:
            for kind in fixed.RECORD_KINDS:
                self.assertNotEqual(name, f"req-1.{kind}.json")

    def test_each_kept_file_has_one_field_of_the_receipt_in_the_execution_group(self):
        self.assertEqual([evidence.field_name(kind) for kind in evidence.KINDS], list(FIELDS))
        for name in FIELDS:
            self.assertIn(name, fixed.RECEIPT_GROUPS["execution"])

    def test_a_file_that_is_not_a_regular_file_reads_none_and_any_other_failure_cannot_tell(self):
        for error, reading in (
            (
                FileNotFoundError("gone"),
                "cannot_tell",
            ),  # the area was there, so this is not "absent"
            (IsADirectoryError("a folder"), "none"),
            (NotARegularFile("a link"), "none"),
            (PermissionError("no"), "cannot_tell"),
            (FileExistsError("taken"), "cannot_tell"),
            (OSError("disk"), "cannot_tell"),
        ):
            with self.subTest(type(error).__name__):
                self.assertEqual(evidence.reading_after(error), reading)

    def test_the_record_version_is_five(self):
        self.assertEqual(fixed.RECORD_VERSION, 5)


class TheRunKeepsWhatTheExecutorPrinted(unittest.TestCase):
    def run_with(self, program=None, doc=None, before=None):
        world = scenes.scene(doc, **(program or {}))
        if before:
            before(world)
        code, _, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        return world, scenes.outcome(world)["receipt"]

    def test_standard_output_and_standard_error_are_kept_whole_beside_the_statement_by_name(self):
        out, err = "line one\r\nno final newline", "warning \x00 \xff stays\n"
        world, receipt = self.run_with({"output": out, "error": err})
        self.assertEqual(world.text_of(KEPT_OUT), out)
        self.assertEqual(world.text_of(KEPT_ERR), err)
        got = receipt["execution"]
        self.assertEqual(got["standard_output_kept"], held(KEPT_OUT, out))
        self.assertEqual(got["standard_error_kept"], held(KEPT_ERR, err))
        self.assertEqual(decisions.check_receipt(receipt), [])

    def test_a_kept_file_is_readable_and_writable_by_its_owner_only(self):
        world, _ = self.run_with({"output": "x", "error": "y"})
        self.assertEqual((world.mode_of(KEPT_OUT), world.mode_of(KEPT_ERR)), (0o600, 0o600))

    def test_a_command_has_no_final_message_and_that_reads_none(self):
        world, receipt = self.run_with({"output": "x"})
        self.assertEqual(receipt["execution"]["final_message_kept"], NOTHING)
        self.assertNotIn("/records/inj-1.final-message.kept", world.files)

    def test_a_stream_the_executor_never_wrote_is_kept_empty_and_hashes_as_nothing(self):
        world, receipt = self.run_with({})
        self.assertEqual(world.text_of(KEPT_OUT), "")
        self.assertEqual(receipt["execution"]["standard_output_kept"], held(KEPT_OUT, ""))

    def test_the_files_are_kept_whatever_the_ending_the_command_lives_to_see(self):
        for label, program, ending in (
            ("a time limit", {"times_out": True}, "time_limit"),
            ("a memory limit", {"oom_kills": True}, "memory_limit"),
            ("a program that exits non-zero", {"exit_code": 3}, "ended_by_itself"),
        ):
            with self.subTest(label):
                doc = (
                    scenes.document(memory_limit_bytes=1 << 30)
                    if ending == "memory_limit"
                    else None
                )
                world, receipt = self.run_with(
                    {"output": "so far", "error": "oops", **program}, doc
                )
                self.assertEqual(receipt["ending"]["ending"]["value"], ending)
                self.assertEqual(world.text_of(KEPT_OUT), "so far")
                self.assertEqual(world.text_of(KEPT_ERR), "oops")

    def test_a_stop_from_outside_keeps_them_too(self):
        def stop(world):
            world.on_call("processes.poll", lambda: world.deliver("SIGINT"), nth=2)

        world, receipt = self.run_with(
            {"output": "so far", "error": "oops", "hangs": True}, before=stop
        )
        self.assertEqual(receipt["ending"]["ending"]["value"], "stopped_from_outside")
        self.assertEqual(world.text_of(KEPT_OUT), "so far")
        self.assertEqual(world.text_of(KEPT_ERR), "oops")

    def test_a_run_that_never_started_the_executor_keeps_nothing_and_every_field_reads_none(self):
        doc = scenes.document(command="absent")
        world = scenes.scene(doc)
        scenes.run_in(world)
        receipt = scenes.outcome(world)["receipt"]
        for name in FIELDS:
            self.assertEqual(receipt["execution"][name], NOTHING, name)
        self.assertEqual(world.names_in("/records"), ["inj-1.outcome.json", "inj-1.request.json"])

    def test_the_run_area_files_are_not_in_the_records_and_the_area_is_still_removed_whole(self):
        world, _ = self.run_with({"output": "x", "error": "y"})
        self.assertFalse(any(name.startswith(AREA) for name in world.files))
        self.assertEqual(
            world.names_in("/records"),
            [
                "inj-1.outcome.json",
                "inj-1.request.json",
                "inj-1.standard-error.kept",
                "inj-1.standard-output.kept",
            ],
        )


class WhatCannotBeKeptIsSaidAndChangesNoEnding(unittest.TestCase):
    def run_with(self, program, before):
        world = scenes.scene(None, **program)
        before(world)
        code, _, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        return world, scenes.outcome(world)["receipt"]

    def test_a_file_that_is_not_there_when_the_files_are_kept_reads_none(self):
        def removes(world):
            world.on_call("boundary.stop", lambda: world.files.pop(OUT, None))

        world, receipt = self.run_with({"output": "x", "error": "y"}, removes)
        got = receipt["execution"]
        self.assertEqual(got["standard_output_kept"], NOTHING)
        self.assertEqual(got["standard_error_kept"], held(KEPT_ERR, "y"))
        self.assertNotIn(KEPT_OUT, world.files)

    def test_a_link_a_pipe_or_a_folder_in_its_place_is_not_followed_and_reads_none(self):
        things = {
            "a link to a file": lambda w: (
                w.put_file("/elsewhere", "secret"),
                w.put_link(OUT, "/elsewhere"),
            ),
            "a link to nothing": lambda w: w.put_link(OUT, "/absent"),
            "a named pipe": lambda w: w.put_pipe(OUT),
            "a folder": lambda w: w.make_folder(OUT),
        }
        for label, put in things.items():
            with self.subTest(label):

                def swaps(world, put=put):
                    def swap():
                        world.files.pop(OUT, None)
                        put(world)

                    world.on_call("boundary.stop", swap)

                world, receipt = self.run_with({"output": "x"}, swaps)
                self.assertEqual(receipt["execution"]["standard_output_kept"], NOTHING)
                self.assertNotIn(KEPT_OUT, world.files)
                self.assertNotIn(
                    "secret",
                    "".join(world.text_of(n) for n in world.files if n.startswith("/records")),
                )
                self.assertEqual(receipt["ending"]["ending"]["value"], "ended_by_itself")

    def test_a_move_that_fails_reads_cannot_tell_for_that_file_alone_and_the_ending_stands(self):
        for nth, failed in ((1, "standard_output_kept"), (2, "standard_error_kept")):
            with self.subTest(failed):
                world, receipt = self.run_with(
                    {"output": "x", "error": "y"},
                    lambda w, nth=nth: w.will_raise(
                        "files.copy_private", PermissionError("no"), nth=nth
                    ),
                )
                got = receipt["execution"]
                self.assertEqual(got[failed], CANNOT)
                other = next(n for n in FIELDS[:2] if n != failed)
                self.assertEqual(got[other]["state"], "value")
                self.assertEqual(receipt["ending"]["ending"]["value"], "ended_by_itself")
                self.assertEqual(decisions.check_receipt(receipt), [])

    def test_a_hash_that_fails_reads_cannot_tell_and_the_ending_stands(self):
        world, receipt = self.run_with(
            {"output": "x", "error": "y"},
            lambda w: w.will_raise("files.hash", OSError("disk"), nth=1),
        )
        got = receipt["execution"]
        self.assertEqual(got["standard_output_kept"], CANNOT)
        self.assertEqual(got["standard_error_kept"], held(KEPT_ERR, "y"))
        self.assertEqual(receipt["ending"]["ending"]["value"], "ended_by_itself")

    def test_a_records_folder_that_cannot_take_the_files_reads_cannot_tell_for_each(self):
        world, receipt = self.run_with(
            {"output": "x", "error": "y"},
            lambda w: w.will_raise("files.copy_private", OSError("full"), nth=None),
        )
        for name in FIELDS[:2]:
            self.assertEqual(receipt["execution"][name], CANNOT, name)
        self.assertEqual(receipt["ending"]["ending"]["value"], "ended_by_itself")


if __name__ == "__main__":
    unittest.main()
