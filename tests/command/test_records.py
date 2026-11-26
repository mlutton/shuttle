"""Every fixed value, written to a real records folder and read back."""

import json
import os
import shutil
import tempfile
import unittest

from shuttle.core import decisions as core
from shuttle.core import fixed
from shuttle.shell import records

HEADER_SOURCE = {
    "request_id": "req-1",
    "records_location": None,
    "executor_name": "command",
    "thread": "t",
    "round": 1,
    "kind": "plain",
    "parent_session": "none",
    "asked_by": "none",
}


def facts():
    return {
        "receipt_id": "r-1",
        "execution_version": "1",
        "host": "h",
        "input_hash": "x",
        "launched": False,
        "started_at": None,
        "ended_at": None,
        "executor_duration": None,
        "exit_code": None,
        "signal": None,
        "executor_driver_observations": None,
        "stand_ins": {},
        "reason_text": None,
    }


class RecordsFolder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def write_and_read(self, decision, request_id):
        receipt = core.build_receipt(decision, facts())
        header = core.build_header(
            "outcome", dict(HEADER_SOURCE, request_id=request_id), "rec", "t"
        )
        path = records.write_outcome_record(
            self.root, request_id, {"header": header, "receipt": receipt}
        )
        return receipt, records.read_record(path)

    def test_every_ending_can_be_written_and_read_back(self):
        for i, ending in enumerate(fixed.ENDINGS):
            with self.subTest(ending):
                reasons = fixed.REASONS_BY_ENDING[ending]
                reason = reasons[0] if reasons else fixed.NONE
                step = (
                    next(x for x in fixed.STEPS_FOR_REASON[reason] if x != fixed.CANNOT_TELL)
                    if reason != fixed.NONE
                    else fixed.NONE
                )
                decision = {"ending": ending, "reason": reason, "failed_step": step}
                receipt, back = self.write_and_read(decision, f"e{i}")
                self.assertEqual(back["receipt"], receipt)
                self.assertEqual(back["receipt"]["the_ending"]["ending"], ending)
                self.assertEqual(core.check_receipt(back["receipt"]), [])

    def test_every_reason_can_be_written_and_read_back_with_its_ending(self):
        for ending, reasons in fixed.REASONS_BY_ENDING.items():
            for reason in reasons:
                with self.subTest(ending=ending, reason=reason):
                    step = next(
                        x
                        for x in fixed.STEPS_FOR_REASON[reason]
                        if x
                        in (fixed.NONE, fixed.CANNOT_TELL) + fixed.STEPS_BY_ENDING.get(ending, ())
                        and not (x == fixed.CANNOT_TELL and ending == "could_not_start")
                    )
                    decision = {"ending": ending, "reason": reason, "failed_step": step}
                    _, back = self.write_and_read(
                        decision, "r-{}-{}".format(ending, reason.replace("_", "-"))
                    )
                    self.assertEqual(back["receipt"]["the_ending"]["reason"], reason)
                    self.assertEqual(core.check_receipt(back["receipt"]), [])

    def test_every_step_name_can_be_written_and_read_back_with_its_ending(self):
        for ending, steps in fixed.STEPS_BY_ENDING.items():
            for step in steps:
                with self.subTest(ending=ending, step=step):
                    reason = next(
                        r
                        for r in fixed.REASONS_BY_ENDING[ending]
                        if step in fixed.STEPS_FOR_REASON[r]
                    )
                    decision = {"ending": ending, "reason": reason, "failed_step": step}
                    _, back = self.write_and_read(decision, "s-{}".format(step.replace("_", "-")))
                    self.assertEqual(back["receipt"]["the_ending"]["failed_step"], step)
                    self.assertEqual(core.check_receipt(back["receipt"]), [])

    def test_the_list_holds_what_the_amended_spec_says(self):
        self.assertIn("gates", fixed.STEPS_BY_ENDING["could_not_start"])
        self.assertNotIn("record", fixed.STEPS)
        self.assertNotIn("record_failed", fixed.REASONS)
        self.assertEqual(len(fixed.ENDINGS), 6)
        self.assertIn("records_location_unusable", fixed.REASONS_BY_ENDING["could_not_start"])

    def test_the_outcome_record_is_created_only_if_none_exists(self):
        first = {"header": {"a": 1}, "receipt": {"first": True}}
        path = records.write_outcome_record(self.root, "same", first)
        with self.assertRaises(FileExistsError):
            records.write_outcome_record(
                self.root, "same", {"header": {}, "receipt": {"first": False}}
            )
        self.assertEqual(records.read_record(path), first)
        self.assertEqual(sorted(os.listdir(self.root)), [os.path.basename(path)])

    def test_the_request_id_is_claimed_once(self):
        records.claim_request_record(self.root, "once", {"header": {}, "input": {"n": 1}})
        with self.assertRaises(FileExistsError):
            records.claim_request_record(self.root, "once", {"header": {}, "input": {"n": 2}})
        with open(records.request_path(self.root, "once")) as f:
            self.assertEqual(json.load(f)["input"], {"n": 1})


if __name__ == "__main__":
    unittest.main()


POINTS = ("build_text", "write_temporary", "flush", "put_in_place")
RAISES = {
    "build_text": records.RecordNotBuilt,
    "write_temporary": OSError,
    "flush": OSError,
    "put_in_place": OSError,
}


def claim_a_request_record(root, fault):
    return records.claim_request_record(
        root, "w-1", {"header": {"k": "request"}, "input": {"a": [1, 2]}}, fault=fault
    )


def write_an_outcome_record(root, fault):
    return records.write_outcome_record(
        root, "w-1", {"header": {"k": "outcome"}, "receipt": {"a": [1, 2]}}, fault=fault
    )


WRITERS = {
    "claim_request_record": ("w-1.request.json", claim_a_request_record),
    "write_outcome_record": ("w-1.outcome.json", write_an_outcome_record),
}
# One row per writer and point: (writer, file it writes, write function, point, exception the fault raises).
CASES = [
    (name, filename, write, point, RAISES[point])
    for name, (filename, write) in WRITERS.items()
    for point in POINTS
]


def fail_at(point):
    def fault(reached):
        if reached == point:
            raise OSError(f"injected at {point}")

    return fault


def under_a_real_name(root):
    return sorted(f for f in os.listdir(root) if f.endswith((".request.json", ".outcome.json")))


class WholeOrAbsent(unittest.TestCase):
    def fresh_root(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        return root

    def test_a_write_cut_short_part_way_leaves_no_file_under_the_real_name_and_no_temporary_file(
        self,
    ):
        root = self.fresh_root()
        for name, (_filename, write) in WRITERS.items():
            with self.subTest(name):
                self.assertRaises(
                    OSError, write, root, fail_at("flush")
                )  # the text is already written
                self.assertEqual(os.listdir(root), [])

    def test_after_a_failure_at_each_point_nothing_is_under_a_real_name_and_no_temporary_file_is_left(
        self,
    ):
        for name, _filename, write, point, raises in CASES:
            with self.subTest(writer=name, point=point):
                root = self.fresh_root()
                self.assertRaises(raises, write, root, fail_at(point))
                self.assertEqual(under_a_real_name(root), [])
                self.assertEqual(os.listdir(root), [])

    def test_after_a_failure_at_each_point_the_id_is_still_free(self):
        for name, filename, write, point, raises in CASES:
            with self.subTest(writer=name, point=point):
                root = self.fresh_root()
                self.assertRaises(raises, write, root, fail_at(point))
                write(root, None)
                self.assertEqual(os.listdir(root), [filename])

    def test_a_record_whose_text_cannot_be_built_is_not_built_and_leaves_nothing_and_the_id_stays_free(
        self,
    ):
        root = self.fresh_root()
        loop = []
        loop.append(loop)
        with self.assertRaises(records.RecordNotBuilt):
            records.claim_request_record(root, "w-1", {"header": {}, "input": loop})
        self.assertEqual(os.listdir(root), [])
        records.claim_request_record(root, "w-1", {"header": {}, "input": {}})
        self.assertEqual(os.listdir(root), ["w-1.request.json"])
