"""By value: building and checking the receipt."""

import unittest

from shuttle.core import decisions as core
from shuttle.core import fixed
from shuttle.core.drivers import command

STAND_INS = {
    name: {fixed.STAND_IN_KEY: name}
    for name in (
        "boundary",
        "gates",
        "setup",
        "opening_fingerprint",
        "stop_confirmation",
        "closing_freeze",
        "delivery",
        "kept_files",
        "teardown",
    )
}


def ran_facts(**changes):
    facts = {
        "receipt_id": "r-1",
        "execution_version": "9.9.9",
        "host": "somehost",
        "input_hash": "abc123",
        "launched": True,
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:00:01Z",
        "executor_duration": 0.9,
        "exit_code": 3,
        "signal": fixed.NONE,
        "executor_driver_observations": command.observe(fixed.NONE, fixed.CANNOT_TELL),
        "stand_ins": dict(STAND_INS),
        "reason_text": None,
    }
    facts.update(changes)
    return facts


ENDED = {"ending": "ended_by_itself", "reason": fixed.NONE, "failed_step": fixed.NONE}
REFUSED = {"ending": "could_not_start", "reason": "unknown_field", "failed_step": "input_check"}


class BuildReceipt(unittest.TestCase):
    def test_every_field_of_every_group_is_present_for_a_run(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        self.assertEqual(
            {g: set(f) for g, f in receipt.items()},
            {g: set(f) for g, f in fixed.RECEIPT_GROUPS.items()},
        )
        self.assertEqual(core.check_receipt(receipt), [])

    def test_every_field_of_every_group_is_present_for_a_refusal(self):
        facts = ran_facts(
            launched=False,
            exit_code=None,
            signal=None,
            started_at=None,
            ended_at=None,
            executor_duration=None,
            executor_driver_observations=None,
            stand_ins={},
            reason_text="unknown field: surprise",
        )
        receipt = core.build_receipt(REFUSED, facts)
        self.assertEqual(core.check_receipt(receipt), [])
        self.assertEqual(receipt["the_ending"]["reason_text"], "unknown field: surprise")

    def test_fields_known_to_execution_hold_their_values(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        saw = receipt["what_execution_saw"]
        self.assertEqual(receipt["the_ending"]["ending"], "ended_by_itself")
        self.assertEqual(receipt["the_ending"]["receipt_id"], "r-1")
        self.assertEqual(receipt["the_ending"]["host"], "somehost")
        self.assertEqual(saw["exit_code"], 3)
        self.assertEqual(saw["input_hash"], "abc123")
        self.assertEqual(saw["duration_executor"], 0.9)
        self.assertEqual(
            receipt["what_the_executor_driver_observed"]["executor_driver_name"], "command"
        )

    def test_a_field_whose_source_is_a_stand_in_says_cannot_tell(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        saw = receipt["what_execution_saw"]
        for field in (
            "fingerprint_before",
            "fingerprint_after",
            "changed_nothing",
            "delivered",
            "duration_gates",
            "teardown_failure",
            "peak_memory",
        ):
            with self.subTest(field):
                self.assertEqual(saw[field], fixed.CANNOT_TELL)
        self.assertEqual(receipt["the_ending"]["everything_stopped"], fixed.CANNOT_TELL)
        self.assertEqual(receipt["what_the_executor_said"]["claim"], fixed.CANNOT_TELL)

    def test_what_a_run_never_reached_is_none_not_invented(self):
        facts = ran_facts(
            launched=False,
            exit_code=None,
            signal=None,
            executor_driver_observations=None,
            stand_ins={},
        )
        receipt = core.build_receipt(REFUSED, facts)
        saw = receipt["what_execution_saw"]
        self.assertEqual(saw["exit_code"], fixed.NONE)
        self.assertEqual(saw["fingerprint_before"], fixed.NONE)
        self.assertEqual(receipt["what_the_executor_driver_observed"]["tokens_in"], fixed.NONE)

    def test_the_observed_runtime_is_cannot_tell_once_launched_and_none_before(self):
        ran = core.build_receipt(ENDED, ran_facts())
        self.assertEqual(ran["what_execution_saw"]["observed_runtime"], fixed.CANNOT_TELL)
        never = core.build_receipt(
            REFUSED,
            ran_facts(
                launched=False,
                exit_code=None,
                signal=None,
                executor_driver_observations=None,
                stand_ins={},
            ),
        )
        self.assertEqual(never["what_execution_saw"]["observed_runtime"], fixed.NONE)

    def test_the_ending_group_copies_the_decision_unchanged(self):
        receipt = core.build_receipt(REFUSED, ran_facts())
        self.assertEqual(core.ending_conflicts(REFUSED, receipt), [])


class CheckReceipt(unittest.TestCase):
    def good(self):
        return core.build_receipt(ENDED, ran_facts())

    def test_a_missing_field_is_a_problem(self):
        receipt = self.good()
        del receipt["what_execution_saw"]["exit_code"]
        self.assertNotEqual(core.check_receipt(receipt), [])

    def test_an_extra_field_is_a_problem(self):
        receipt = self.good()
        receipt["what_execution_saw"]["invented"] = 1
        self.assertNotEqual(core.check_receipt(receipt), [])

    def test_an_empty_or_null_value_is_a_problem(self):
        for bad in (None, "", [], {}):
            with self.subTest(bad):
                receipt = self.good()
                receipt["what_execution_saw"]["signal"] = bad
                self.assertNotEqual(core.check_receipt(receipt), [])

    def test_an_ending_off_the_list_is_a_problem(self):
        receipt = self.good()
        receipt["the_ending"]["ending"] = "record_failed"
        self.assertNotEqual(core.check_receipt(receipt), [])


class Header(unittest.TestCase):
    def test_header_carries_the_identifying_facts(self):
        source = {
            "request_id": "req-1",
            "records_location": "/x",
            "executor_name": "command",
            "thread": "t",
            "round": 4,
            "kind": "plain",
            "parent_session": "none",
            "asked_by": "none",
        }
        header = core.build_header("request", source, "rec-1", "2026-01-01T00:00:00Z")
        self.assertEqual(
            header,
            {
                "record_id": "rec-1",
                "record_type": "request",
                "time": "2026-01-01T00:00:00Z",
                "request_id": "req-1",
                "thread": "t",
                "round": 4,
                "parent_session": "none",
                "asked_by": "none",
                "kind": "plain",
                "executor_name": "command",
                "format_version": fixed.FORMAT_VERSION,
            },
        )


if __name__ == "__main__":
    unittest.main()
