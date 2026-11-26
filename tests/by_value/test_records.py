"""By value: a record is whole or absent, whatever fails and wherever, on the simulated world.

No disk, no real limit, no process. The simulated world fails an operation, or stops it half
way (a record half written, or written and never flushed), at each point a record passes
through. The real disk is tested in tests/command/test_records.py (every fixed value written
and read back) and tests/command/test_command.py (one real file-size limit, one read-only
folder).
"""

import importlib
import json
import os
import sys
import unittest

from shuttle.core import decisions as core
from shuttle.shell import records

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
simulated = importlib.import_module("rehearsal.simulated_world")

FOLDER = "/records"


def claim(world, record=None):
    return records.claim_request_record(
        world.operations,
        FOLDER,
        "w-1",
        record or {"header": {"k": "request"}, "input": {"a": [1, 2]}},
    )


def outcome(world, record=None):
    return records.write_outcome_record(
        world.operations,
        FOLDER,
        "w-1",
        record or {"header": {"k": "outcome"}, "receipt": {"a": [1, 2]}},
    )


WRITERS = {
    "claim_request_record": ("w-1.request.json", claim),
    "write_outcome_record": ("w-1.outcome.json", outcome),
}

# One row per point a record passes through: how to make the simulated world fail there, and
# what the writer raises. The first four are the points the old `fault` argument named (build
# the text, write the temporary, flush it, put it in place); "stopped half way" is new.
POINTS = {
    "the text cannot be built": (None, records.RecordNotBuilt),
    "the temporary cannot be made": (
        lambda w: w.will_raise("files.write_new", OSError("injected")),
        OSError,
    ),
    "the write stops half way": (lambda w: w.will_stop_half_way(how="half"), OSError),
    "the write is not flushed": (lambda w: w.will_stop_half_way(how="unflushed"), OSError),
    "the put in place fails": (lambda w: w.will_raise("files.link", OSError("injected")), OSError),
}


# One case per writer and point.
CASES = [
    (name, filename, write, point, POINTS[point][1])
    for name, (filename, write) in WRITERS.items()
    for point in POINTS
]


def a_record_whose_text_cannot_be_built():
    loop = []
    loop.append(loop)
    return {"header": {}, "input": loop}


def fail(world, writer, point):
    make_it_fail, _ = POINTS[point]
    if make_it_fail is None:
        return writer(world, a_record_whose_text_cannot_be_built())
    make_it_fail(world)
    return writer(world)


def a_world():
    world = simulated.SimulatedWorld()
    world.make_folder(FOLDER)
    return world


class WholeOrAbsent(unittest.TestCase):
    def test_after_a_failure_at_each_point_nothing_is_under_any_name_and_no_temporary_is_left(self):
        for name, _, write, point, raises in CASES:
            with self.subTest(writer=name, point=point):
                world = a_world()
                self.assertRaises(raises, fail, world, write, point)
                self.assertEqual(world.names_in(FOLDER), [])

    def test_after_a_failure_at_each_point_the_id_is_still_free(self):
        for name, filename, write, point, raises in CASES:
            with self.subTest(writer=name, point=point):
                world = a_world()
                self.assertRaises(raises, fail, world, write, point)
                write(world)
                self.assertEqual(world.names_in(FOLDER), [filename])

    def test_a_write_stopped_half_way_really_left_half_a_temporary_until_it_was_removed(self):
        world = a_world()
        record = {"header": {"k": "request"}, "input": {"a": [1, 2]}}
        full = (json.dumps(record, indent=2) + "\n").encode()
        world.will_stop_half_way(how="half")
        seen = []
        world.on_call("files.remove", lambda: seen.append(list(world.files.values())))
        with self.assertRaises(OSError):
            claim(world, record)
        (during,) = seen  # the only file there then was the temporary
        (partial,) = during
        self.assertTrue(0 < len(partial) < len(full))
        self.assertEqual(bytes(partial), full[: len(partial)])
        self.assertEqual(world.files, {})

    def test_a_record_that_is_put_in_place_is_whole_and_read_back_equal(self):
        world = a_world()
        record = {"header": {"k": "request"}, "input": {"a": [1, 2], "é": "✓"}}
        path = claim(world, record)
        self.assertEqual(path, f"{FOLDER}/w-1.request.json")
        self.assertEqual(records.read_record(world.operations, path), record)
        self.assertEqual(world.names_in(FOLDER), ["w-1.request.json"])

    def test_the_outcome_record_is_created_only_if_none_exists(self):
        world = a_world()
        first = {"header": {"a": 1}, "receipt": {"first": True}}
        path = outcome(world, first)
        with self.assertRaises(FileExistsError):
            outcome(world, {"header": {}, "receipt": {"first": False}})
        self.assertEqual(records.read_record(world.operations, path), first)
        self.assertEqual(world.names_in(FOLDER), ["w-1.outcome.json"])

    def test_the_request_id_is_claimed_once(self):
        world = a_world()
        claim(world, {"header": {}, "input": {"n": 1}})
        with self.assertRaises(FileExistsError):
            claim(world, {"header": {}, "input": {"n": 2}})
        self.assertEqual(
            records.read_record(world.operations, f"{FOLDER}/w-1.request.json")["input"], {"n": 1}
        )

    def test_an_outcome_record_already_there_means_the_id_is_used_and_nothing_is_written(self):
        world = a_world()
        world.put_file(f"{FOLDER}/w-1.outcome.json", "earlier run")
        with self.assertRaises(FileExistsError):
            claim(world)
        self.assertEqual(world.names_in(FOLDER), ["w-1.outcome.json"])
        self.assertEqual(world.text_of(f"{FOLDER}/w-1.outcome.json"), "earlier run")

    def test_a_second_claim_that_gets_in_before_the_first_is_put_in_place_wins_and_no_temporary_is_left(
        self,
    ):
        world = a_world()

        def the_second_claim():
            world.pid += 1  # another process: its temporary name is its own
            claim(world, {"header": {}, "input": {"who": "second"}})

        world.on_call("files.link", the_second_claim)  # just before the first one's put in place
        with self.assertRaises(FileExistsError):
            claim(world, {"header": {}, "input": {"who": "first"}})
        self.assertEqual(world.names_in(FOLDER), ["w-1.request.json"])
        self.assertEqual(
            records.read_record(world.operations, f"{FOLDER}/w-1.request.json")["input"],
            {"who": "second"},
        )


class TheTemporaryNameKeepsItsOldForm(unittest.TestCase):
    """The temporary's name is the record's name, `.tmp-`, and the process number: as short as it
    was when the process number was read directly (a longer one refuses a run whose records
    location is near the limit on the length of a path, which the base ran)."""

    def temporary_name(self, writer, pid=31337):
        world = a_world()
        world.pid = pid
        names = []
        world.on_call("files.write_new", lambda: names.append(world.log[-1][1][0]))
        writer(world)
        (name,) = names
        return name

    def test_it_is_the_final_name_then_tmp_then_the_process_number(self):
        for filename, write in WRITERS.values():
            with self.subTest(filename):
                self.assertEqual(self.temporary_name(write), f"{FOLDER}/{filename}.tmp-31337")

    def test_it_is_no_longer_than_the_old_one_for_any_process_number_there_can_be(self):
        # the largest process number on a 64-bit system is under 2**22 (seven digits)
        for pid in (1, 99999, 4194304):
            with self.subTest(pid=pid):
                name = self.temporary_name(claim, pid)
                self.assertLessEqual(
                    len(name), len(f"{FOLDER}/w-1.request.json") + len(".tmp-") + 7
                )

    def test_the_process_number_is_asked_of_the_operations_not_of_an_id(self):
        world = a_world()
        claim(world)
        self.assertEqual(world.counts["identity.process_number"], 1)
        self.assertNotIn("identity.new_id", world.counts)


class JoinPath(unittest.TestCase):
    def test_a_name_in_a_folder_is_written_as_the_operating_system_joins_it(self):
        for folder in ("", "/", "a", "a/", "/a//", "a b", "..", "/tmp/x/", "é/"):
            with self.subTest(folder=folder):
                self.assertEqual(core.join_path(folder, "n.json"), os.path.join(folder, "n.json"))


if __name__ == "__main__":
    unittest.main()
