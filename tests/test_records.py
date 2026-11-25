"""Every fixed value, written to a real records folder and read back."""
import json
import os
import tempfile
import unittest

from shuttle import core, fixed, records

HEADER_SOURCE = {"request_id": "req-1", "records_location": None, "executor_name": "command"}


def facts():
    return {
        "receipt_id": "r-1", "execution_version": "1", "host": "h", "input_hash": "x",
        "launched": False, "started_at": None, "ended_at": None, "observed_runtime": None,
        "executor_duration": None, "exit_code": None, "signal": None,
        "driver_observations": None, "stand_ins": {}, "reason_text": None,
    }


class RecordsFolder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def write_and_read(self, decision, request_id):
        receipt = core.build_receipt(decision, facts())
        header = core.build_header("outcome", dict(HEADER_SOURCE, request_id=request_id), "rec", "t")
        path = records.write_outcome_record(self.root, request_id, {"header": header, "receipt": receipt})
        return receipt, records.read_record(path)

    def test_every_ending_can_be_written_and_read_back(self):
        for i, ending in enumerate(fixed.ENDINGS):
            with self.subTest(ending):
                reasons = fixed.REASONS_BY_ENDING[ending]
                decision = {"ending": ending, "reason": reasons[0] if reasons else fixed.NONE,
                            "failed_step": fixed.NONE}
                receipt, back = self.write_and_read(decision, "e%d" % i)
                self.assertEqual(back["receipt"], receipt)
                self.assertEqual(back["receipt"]["the_ending"]["ending"], ending)
                self.assertEqual(core.check_receipt(back["receipt"]), [])

    def test_every_reason_can_be_written_and_read_back_with_its_ending(self):
        for ending, reasons in fixed.REASONS_BY_ENDING.items():
            for reason in reasons:
                with self.subTest(ending=ending, reason=reason):
                    decision = {"ending": ending, "reason": reason, "failed_step": fixed.NONE}
                    _, back = self.write_and_read(decision, "r-%s" % reason.replace("_", "-"))
                    self.assertEqual(back["receipt"]["the_ending"]["reason"], reason)
                    self.assertEqual(core.check_receipt(back["receipt"]), [])

    def test_every_step_name_can_be_written_and_read_back_with_its_ending(self):
        for ending, steps in fixed.STEPS_BY_ENDING.items():
            for step in steps:
                with self.subTest(ending=ending, step=step):
                    reason = fixed.REASONS_BY_ENDING[ending][0]
                    decision = {"ending": ending, "reason": reason, "failed_step": step}
                    _, back = self.write_and_read(decision, "s-%s" % step.replace("_", "-"))
                    self.assertEqual(back["receipt"]["the_ending"]["failed_step"], step)
                    self.assertEqual(core.check_receipt(back["receipt"]), [])

    def test_the_list_holds_what_the_amended_spec_says(self):
        self.assertIn("gates", fixed.STEPS_BY_ENDING["could_not_start"])
        self.assertNotIn("record", fixed.STEPS)
        self.assertNotIn("record_failed", fixed.REASONS)
        self.assertEqual(len(fixed.ENDINGS), 6)

    def test_the_outcome_record_is_created_only_if_none_exists(self):
        first = {"header": {"a": 1}, "receipt": {"first": True}}
        path = records.write_outcome_record(self.root, "same", first)
        with self.assertRaises(FileExistsError):
            records.write_outcome_record(self.root, "same", {"header": {}, "receipt": {"first": False}})
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
