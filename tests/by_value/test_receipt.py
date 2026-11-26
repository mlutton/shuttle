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
        "signal": None,
        "executor_driver_observations": command.observe(),
        "stand_ins": dict(STAND_INS),
        "reason_text": None,
    }
    facts.update(changes)
    return facts


ENDED = {"ending": "ended_by_itself", "reason": fixed.NONE, "failed_step": fixed.NONE}
REFUSED = {"ending": "could_not_start", "reason": "unknown_field", "failed_step": "input_check"}


def pair(state, value=None):
    return {"state": state, "value": value}


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
        self.assertEqual(
            receipt["the_ending"]["reason_text"], pair("value", "unknown field: surprise")
        )

    def test_the_four_states_are_in_the_one_list(self):
        self.assertEqual(fixed.STATES, ("value", "none", "cannot tell", "not built"))

    def test_every_field_of_every_group_is_a_pair_in_a_state_on_the_list(self):
        receipts = {
            "a run": core.build_receipt(ENDED, ran_facts()),
            "a refusal": core.build_receipt(
                REFUSED, ran_facts(launched=False, executor_driver_observations=None, stand_ins={})
            ),
            "a minimal receipt": core.minimal_receipt(ENDED),
        }
        fields = [
            (what, group, name, receipt[group][name])
            for what, receipt in receipts.items()
            for group, names in fixed.RECEIPT_GROUPS.items()
            for name in names
        ]
        for what, group, name, held in fields:
            with self.subTest(what=what, field=f"{group}.{name}"):
                self.assertEqual(set(held), {"state", "value"})
                self.assertIn(held["state"], fixed.STATES)
                if held["state"] != fixed.VALUE:
                    self.assertIsNone(held["value"])

    def test_a_value_that_is_the_word_none_is_not_mistaken_for_the_state(self):
        receipt = core.build_receipt(ENDED, ran_facts(host="none"))
        self.assertEqual(receipt["the_ending"]["host"], pair("value", "none"))
        self.assertEqual(core.check_receipt(receipt), [])

    def test_fields_known_to_execution_hold_their_values(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        saw = receipt["what_execution_saw"]
        self.assertEqual(receipt["the_ending"]["ending"], pair("value", "ended_by_itself"))
        self.assertEqual(receipt["the_ending"]["receipt_id"], pair("value", "r-1"))
        self.assertEqual(receipt["the_ending"]["host"], pair("value", "somehost"))
        self.assertEqual(saw["exit_code"], pair("value", 3))
        self.assertEqual(saw["input_hash"], pair("value", "abc123"))
        self.assertEqual(saw["duration_executor_seconds"], pair("value", 0.9))
        self.assertEqual(
            receipt["what_the_executor_driver_observed"]["executor_driver_name"],
            pair("value", "command"),
        )

    def test_a_field_whose_source_is_a_stand_in_says_not_built_and_never_cannot_tell(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        saw = receipt["what_execution_saw"]
        for field in (
            "fingerprint_before",
            "fingerprint_after",
            "changed_nothing",
            "delivered",
            "duration_gates_seconds",
            "teardown_failure",
            "peak_memory_bytes",
            "observed_runtime",
        ):
            with self.subTest(field):
                self.assertEqual(saw[field], pair(fixed.NOT_BUILT))
        self.assertEqual(receipt["the_ending"]["everything_stopped"], pair(fixed.NOT_BUILT))
        self.assertEqual(receipt["what_the_executor_said"]["claim"], pair(fixed.NOT_BUILT))

    def test_not_built_and_cannot_tell_differ_in_one_receipt(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        self.assertEqual(receipt["what_execution_saw"]["delivered"]["state"], fixed.NOT_BUILT)
        driver = receipt["what_the_executor_driver_observed"]
        self.assertEqual(driver["tool_made_own_commits"]["state"], fixed.CANNOT_TELL)

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
        self.assertEqual(saw["exit_code"], pair(fixed.NONE))
        self.assertEqual(saw["fingerprint_before"], pair(fixed.NONE))
        self.assertEqual(receipt["what_the_executor_driver_observed"]["tokens_in"], pair("none"))

    def test_a_driver_that_could_not_be_observed_is_cannot_tell_once_launched(self):
        receipt = core.build_receipt(ENDED, ran_facts(executor_driver_observations=None))
        driver = receipt["what_the_executor_driver_observed"]
        self.assertEqual({p["state"] for p in driver.values()}, {fixed.CANNOT_TELL})

    def test_the_observed_runtime_is_not_built_once_launched_and_none_before(self):
        ran = core.build_receipt(ENDED, ran_facts())
        self.assertEqual(ran["what_execution_saw"]["observed_runtime"], pair(fixed.NOT_BUILT))
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
        self.assertEqual(never["what_execution_saw"]["observed_runtime"], pair(fixed.NONE))

    def test_the_ending_group_copies_the_decision_unchanged(self):
        receipt = core.build_receipt(REFUSED, ran_facts())
        self.assertEqual(core.ending_conflicts(REFUSED, receipt), [])

    def test_a_reason_that_is_none_and_a_failed_step_that_cannot_be_told_are_states(self):
        decision = {"ending": "execution_failed", "reason": "lost", "failed_step": "cannot tell"}
        ending = core.build_receipt(decision, ran_facts())["the_ending"]
        self.assertEqual(ending["failed_step"], pair(fixed.CANNOT_TELL))
        self.assertEqual(
            core.build_receipt(ENDED, ran_facts())["the_ending"]["reason"], pair("none")
        )


# Every key that holds a quantity, with the unit in its name.
QUANTITY_KEYS = {
    "what_execution_saw": (
        "duration_gates_seconds",
        "duration_opening_freeze_seconds",
        "duration_executor_seconds",
        "duration_closing_freeze_seconds",
        "duration_delivery_seconds",
        "peak_memory_bytes",
        "processor_time_seconds",
    ),
}
UNITS = ("_seconds", "_bytes")
# Words in a key that say it holds an amount of time or memory.
AMOUNT_WORDS = ("duration", "memory", "processor_time")


class UnitsAreInTheKeyNames(unittest.TestCase):
    def test_each_key_that_holds_a_quantity_is_on_the_list_with_its_unit(self):
        for group, names in QUANTITY_KEYS.items():
            for name in names:
                with self.subTest(name):
                    self.assertIn(name, fixed.RECEIPT_GROUPS[group])
                    self.assertTrue(name.endswith(UNITS), name)

    def test_no_key_that_names_an_amount_of_time_or_memory_lacks_its_unit(self):
        every = [n for names in fixed.RECEIPT_GROUPS.values() for n in names]
        for name in every:
            if any(word in name for word in AMOUNT_WORDS):
                with self.subTest(name):
                    self.assertTrue(name.endswith(UNITS), f"{name} has no unit in its name")

    def test_the_old_names_without_a_unit_are_gone(self):
        every = {n for names in fixed.RECEIPT_GROUPS.values() for n in names}
        for old in (
            "duration_gates",
            "duration_opening_freeze",
            "duration_executor",
            "duration_closing_freeze",
            "duration_delivery",
            "peak_memory",
            "processor_time",
        ):
            with self.subTest(old):
                self.assertNotIn(old, every)

    def test_the_executor_duration_is_a_value_in_seconds(self):
        saw = core.build_receipt(ENDED, ran_facts())["what_execution_saw"]
        self.assertEqual(saw["duration_executor_seconds"], pair("value", 0.9))


class ARightFieldIsRefusedWhenItIsNotAPair(unittest.TestCase):
    def test_a_bare_string_where_a_pair_belongs_is_refused_by_the_builder(self):
        for bare in ("none", "cannot tell", "something", ""):
            observed = command.observe()
            observed["model"] = bare
            with self.subTest(bare=bare), self.assertRaises(core.ReceiptNotBuilt):
                core.build_receipt(ENDED, ran_facts(executor_driver_observations=observed))

    def test_a_pair_with_a_state_off_the_list_or_a_value_in_the_wrong_state_is_refused(self):
        for bad in (
            pair("invented"),
            pair("none", "but a value"),
            pair("value"),
            {"state": "value"},
            {"state": "value", "value": 1, "extra": 2},
        ):
            observed = command.observe()
            observed["model"] = bad
            with self.subTest(bad=bad), self.assertRaises(core.ReceiptNotBuilt):
                core.build_receipt(ENDED, ran_facts(executor_driver_observations=observed))

    def test_a_receipt_cannot_be_built_with_a_field_left_out(self):
        for name in fixed.RECEIPT_GROUPS["what_the_executor_driver_observed"]:
            observed = command.observe()
            del observed[name]
            with self.subTest(name), self.assertRaises(core.ReceiptNotBuilt):
                core.build_receipt(ENDED, ran_facts(executor_driver_observations=observed))


class CheckReceipt(unittest.TestCase):
    def good(self):
        return core.build_receipt(ENDED, ran_facts())

    def test_a_missing_field_is_a_problem(self):
        receipt = self.good()
        del receipt["what_execution_saw"]["exit_code"]
        self.assertNotEqual(core.check_receipt(receipt), [])

    def test_an_extra_field_is_a_problem(self):
        receipt = self.good()
        receipt["what_execution_saw"]["invented"] = pair("value", 1)
        self.assertNotEqual(core.check_receipt(receipt), [])

    def test_a_field_that_is_not_a_pair_is_a_problem(self):
        for bad in (None, "", "none", [], {}, 3):
            with self.subTest(bad):
                receipt = self.good()
                receipt["what_execution_saw"]["signal"] = bad
                self.assertNotEqual(core.check_receipt(receipt), [])

    def test_a_value_state_that_holds_nothing_is_a_problem(self):
        for bad in (None, "", [], {}):
            with self.subTest(bad):
                receipt = self.good()
                receipt["what_execution_saw"]["signal"] = pair("value", bad)
                self.assertNotEqual(core.check_receipt(receipt), [])

    def test_an_ending_off_the_list_is_a_problem(self):
        receipt = self.good()
        receipt["the_ending"]["ending"] = pair("value", "record_failed")
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
