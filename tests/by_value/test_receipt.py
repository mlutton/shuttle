"""By value: building and checking the receipt."""

import unittest

from shuttle.core import decisions as core
from shuttle.core import fixed, pairs
from shuttle.core.drivers import command

NOTHING_SAVED = {"events": None, "last_message": None, "session_record": None}

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
        "executor_driver_observations": command.observe({}, NOTHING_SAVED)["group"],
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
        self.assertEqual(receipt["ending"]["reason_text"], pair("value", "unknown field: surprise"))

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
        self.assertEqual(receipt["execution"]["host"], pair("value", "none"))
        self.assertEqual(core.check_receipt(receipt), [])

    def test_fields_known_to_execution_hold_their_values(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        saw = receipt["execution"]
        self.assertEqual(receipt["ending"]["ending"], pair("value", "ended_by_itself"))
        self.assertEqual(receipt["ending"]["receipt_id"], pair("value", "r-1"))
        self.assertEqual(receipt["execution"]["host"], pair("value", "somehost"))
        self.assertEqual(saw["exit_code"], pair("value", 3))
        self.assertEqual(saw["input_hash"], pair("value", "abc123"))
        self.assertEqual(saw["duration_executor_seconds"], pair("value", 0.9))
        self.assertEqual(
            receipt["executor_driver"]["executor_driver_name"],
            pair("value", "command"),
        )

    def test_a_signal_that_cannot_be_told_says_cannot_tell_and_a_named_one_is_a_value(self):
        for given, expected in (
            (fixed.CANNOT_TELL, pair(fixed.CANNOT_TELL)),
            ("SIGTERM", pair("value", "SIGTERM")),
            (None, pair(fixed.NONE)),
        ):
            with self.subTest(given=given):
                receipt = core.build_receipt(ENDED, ran_facts(signal=given))
                self.assertEqual(receipt["execution"]["signal"], expected)
                self.assertEqual(core.check_receipt(receipt), [])

    def test_a_field_whose_source_is_a_stand_in_says_not_built_and_never_cannot_tell(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        saw = receipt["execution"]
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
        self.assertEqual(receipt["ending"]["everything_stopped"], pair(fixed.NOT_BUILT))
        self.assertEqual(receipt["executor"]["claim"], pair(fixed.NOT_BUILT))

    def test_not_built_and_cannot_tell_differ_in_one_receipt(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        self.assertEqual(receipt["execution"]["delivered"]["state"], fixed.NOT_BUILT)
        driver = receipt["executor_driver"]
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
        saw = receipt["execution"]
        self.assertEqual(saw["exit_code"], pair(fixed.NONE))
        self.assertEqual(saw["fingerprint_before"], pair(fixed.NONE))
        self.assertEqual(receipt["executor_driver"]["tokens_in"], pair("none"))

    def test_a_driver_that_could_not_be_observed_is_cannot_tell_once_launched(self):
        receipt = core.build_receipt(ENDED, ran_facts(executor_driver_observations=None))
        driver = receipt["executor_driver"]
        self.assertEqual({p["state"] for p in driver.values()}, {fixed.CANNOT_TELL})

    def test_the_observed_runtime_is_not_built_once_launched_and_none_before(self):
        ran = core.build_receipt(ENDED, ran_facts())
        self.assertEqual(ran["execution"]["observed_runtime"], pair(fixed.NOT_BUILT))
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
        self.assertEqual(never["execution"]["observed_runtime"], pair(fixed.NONE))

    def test_the_ending_group_copies_the_decision_unchanged(self):
        receipt = core.build_receipt(REFUSED, ran_facts())
        self.assertEqual(core.ending_conflicts(REFUSED, receipt), [])

    def test_a_reason_that_is_none_and_a_failed_step_that_cannot_be_told_are_states(self):
        decision = {"ending": "execution_failed", "reason": "lost", "failed_step": "cannot tell"}
        ending = core.build_receipt(decision, ran_facts())["ending"]
        self.assertEqual(ending["failed_step"], pair(fixed.CANNOT_TELL))
        self.assertEqual(core.build_receipt(ENDED, ran_facts())["ending"]["reason"], pair("none"))


# Every key that holds a quantity, with the unit in its name.
QUANTITY_KEYS = {
    "execution": (
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


class TheGroups(unittest.TestCase):
    def test_the_four_group_keys_are_short(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        self.assertEqual(
            sorted(receipt), sorted(["ending", "execution", "executor_driver", "executor"])
        )
        self.assertEqual(sorted(fixed.RECEIPT_GROUPS), sorted(receipt))

    def test_executor_driver_is_never_called_just_driver(self):
        self.assertNotIn("driver", fixed.RECEIPT_GROUPS)

    def test_the_versions_of_execution_and_the_host_are_what_execution_saw(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        for field in ("execution_version", "host"):
            with self.subTest(field):
                self.assertIn(field, receipt["execution"])
                self.assertNotIn(field, receipt["ending"])
        self.assertEqual(receipt["execution"]["execution_version"], pair("value", "9.9.9"))
        self.assertEqual(receipt["execution"]["host"], pair("value", "somehost"))


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
        saw = core.build_receipt(ENDED, ran_facts())["execution"]
        self.assertEqual(saw["duration_executor_seconds"], pair("value", 0.9))


class ARightFieldIsRefusedWhenItIsNotAPair(unittest.TestCase):
    def test_a_bare_string_where_a_pair_belongs_is_refused_by_the_builder(self):
        for bare in ("none", "cannot tell", "something", ""):
            observed = command.observe({}, NOTHING_SAVED)["group"]
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
            observed = command.observe({}, NOTHING_SAVED)["group"]
            observed["model"] = bad
            with self.subTest(bad=bad), self.assertRaises(core.ReceiptNotBuilt):
                core.build_receipt(ENDED, ran_facts(executor_driver_observations=observed))

    def test_a_receipt_cannot_be_built_with_a_field_left_out(self):
        for name in fixed.RECEIPT_GROUPS["executor_driver"]:
            observed = command.observe({}, NOTHING_SAVED)["group"]
            del observed[name]
            with self.subTest(name), self.assertRaises(core.ReceiptNotBuilt):
                core.build_receipt(ENDED, ran_facts(executor_driver_observations=observed))


class CheckReceipt(unittest.TestCase):
    def good(self):
        return core.build_receipt(ENDED, ran_facts())

    def test_a_missing_field_is_a_problem(self):
        receipt = self.good()
        del receipt["execution"]["exit_code"]
        self.assertNotEqual(core.check_receipt(receipt), [])

    def test_an_extra_field_is_a_problem(self):
        receipt = self.good()
        receipt["execution"]["invented"] = pair("value", 1)
        self.assertNotEqual(core.check_receipt(receipt), [])

    def test_a_field_that_is_not_a_pair_is_a_problem(self):
        for bad in (None, "", "none", [], {}, 3):
            with self.subTest(bad):
                receipt = self.good()
                receipt["execution"]["signal"] = bad
                self.assertNotEqual(core.check_receipt(receipt), [])

    def test_a_value_state_that_holds_nothing_is_a_problem(self):
        for bad in (None, "", [], {}):
            with self.subTest(bad):
                receipt = self.good()
                receipt["execution"]["signal"] = pair("value", bad)
                self.assertNotEqual(core.check_receipt(receipt), [])

    def test_an_ending_off_the_list_is_a_problem(self):
        receipt = self.good()
        receipt["ending"]["ending"] = pair("value", "record_failed")
        self.assertNotEqual(core.check_receipt(receipt), [])


# The state each field earns, one row for every field and no default: a field of the receipt
# with no row fails the test that reads these tables.
LAUNCHED_RUN = {
    "ending": {
        "ending": "value",
        "reason": "none",
        "failed_step": "none",
        "reason_text": "none",
        "receipt_id": "value",
        "everything_stopped": "not built",
    },
    "execution": {
        "execution_version": "value",
        "host": "value",
        "started_at": "value",
        "ended_at": "value",
        "observed_runtime": "not built",
        "duration_gates_seconds": "not built",
        "duration_opening_freeze_seconds": "not built",
        "duration_executor_seconds": "value",
        "duration_closing_freeze_seconds": "not built",
        "duration_delivery_seconds": "not built",
        "input_hash": "value",
        "reference_hashes": "none",
        "fingerprint_before": "not built",
        "fingerprint_after": "not built",
        "changed_nothing": "not built",
        "files_added": "not built",
        "files_changed": "not built",
        "files_deleted": "not built",
        "files_list_kept_file": "not built",
        "delivered": "not built",
        "delivery_branch": "not built",
        "delivery_branch_reason": "not built",
        "exit_code": "value",
        "signal": "none",
        "peak_memory_bytes": "not built",
        "processor_time_seconds": "not built",
        "session_file_kept_at": "not built",
        "teardown_failure": "not built",
        "stop_reason": "not built",
        "stop_asker": "not built",
    },
    "executor_driver": {
        "executor_driver_name": "value",
        "executor_driver_version": "value",
        "tool_version": "none",
        "model": "none",
        "effort": "none",
        "tokens_in": "none",
        "tokens_out": "none",
        "tokens_cached": "none",
        "activity": "none",
        "session_id": "none",
        "refused_actions": "none",
        "quota_level": "none",
        "vendor_limit_reached": "none",
        "vendor_limit_reset": "none",
        "tool_made_own_commits": "cannot tell",
        "load_lists_differ": "none",
        "load_lists_kept_file": "none",
        "changed_self_loaded_file": "none",
        "waiting_question": "none",
    },
    "executor": {
        "statement_state": "not built",
        "statement_hash": "not built",
        "statement_location": "not built",
        "claim": "not built",
    },
}

REFUSED_RUN = {
    "ending": {
        "ending": "value",
        "reason": "value",
        "failed_step": "value",
        "reason_text": "value",
        "receipt_id": "value",
        "everything_stopped": "none",
    },
    "execution": {
        "execution_version": "value",
        "host": "value",
        "started_at": "none",
        "ended_at": "none",
        "observed_runtime": "none",
        "duration_gates_seconds": "none",
        "duration_opening_freeze_seconds": "none",
        "duration_executor_seconds": "none",
        "duration_closing_freeze_seconds": "none",
        "duration_delivery_seconds": "none",
        "input_hash": "value",
        "reference_hashes": "none",
        "fingerprint_before": "none",
        "fingerprint_after": "none",
        "changed_nothing": "none",
        "files_added": "none",
        "files_changed": "none",
        "files_deleted": "none",
        "files_list_kept_file": "none",
        "delivered": "none",
        "delivery_branch": "none",
        "delivery_branch_reason": "none",
        "exit_code": "none",
        "signal": "none",
        "peak_memory_bytes": "none",
        "processor_time_seconds": "none",
        "session_file_kept_at": "none",
        "teardown_failure": "none",
        "stop_reason": "none",
        "stop_asker": "none",
    },
    "executor_driver": {
        "executor_driver_name": "none",
        "executor_driver_version": "none",
        "tool_version": "none",
        "model": "none",
        "effort": "none",
        "tokens_in": "none",
        "tokens_out": "none",
        "tokens_cached": "none",
        "activity": "none",
        "session_id": "none",
        "refused_actions": "none",
        "quota_level": "none",
        "vendor_limit_reached": "none",
        "vendor_limit_reset": "none",
        "tool_made_own_commits": "none",
        "load_lists_differ": "none",
        "load_lists_kept_file": "none",
        "changed_self_loaded_file": "none",
        "waiting_question": "none",
    },
    "executor": {
        "statement_state": "none",
        "statement_hash": "none",
        "statement_location": "none",
        "claim": "none",
    },
}


class EveryFieldHasTheStateTheRunEarnedIt(unittest.TestCase):
    """A table of field to state, over a launched run and a refused one. The states are read from
    the pairs, never through `flat`, which cannot tell the state "none" from the word "none"."""

    def states(self, receipt):
        return {
            group: {name: held["state"] for name, held in fields.items()}
            for group, fields in receipt.items()
        }

    def test_every_field_of_the_receipt_has_a_row_in_each_table(self):
        for table in (LAUNCHED_RUN, REFUSED_RUN):
            self.assertEqual(
                {g: sorted(rows) for g, rows in table.items()},
                {g: sorted(names) for g, names in fixed.RECEIPT_GROUPS.items()},
            )

    def test_a_launched_run_that_ended_by_itself(self):
        receipt = core.build_receipt(ENDED, ran_facts())
        self.assertEqual(self.states(receipt), LAUNCHED_RUN)

    def test_a_launched_run_whose_kept_files_step_is_real_but_builds_no_list(self):
        # The step looked at the statement and found nothing; no step builds the list of changed
        # files yet, so that field is "not built" ("cannot tell" is for a look that failed).
        kept = {
            "statement_state": "",
            "statement_hash": "",
            "statement_location": "",
            "claim": "",
            "session_file": "",
        }
        receipt = core.build_receipt(ENDED, ran_facts(stand_ins={**STAND_INS, "kept_files": kept}))
        states = self.states(receipt)
        self.assertEqual(states["execution"]["files_list_kept_file"], "not built")
        self.assertEqual(states["execution"]["session_file_kept_at"], "none")
        self.assertEqual(
            {name: states["executor"][name] for name in kept if name != "session_file"},
            {name: "none" for name in kept if name != "session_file"},
        )
        expected = {group: {**rows} for group, rows in LAUNCHED_RUN.items()}
        expected["execution"]["files_list_kept_file"] = "not built"
        expected["execution"]["session_file_kept_at"] = "none"
        expected["executor"].update({n: "none" for n in kept if n != "session_file"})
        self.assertEqual(states, expected)

    def test_a_run_that_was_refused_before_anything_started(self):
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
        self.assertEqual(self.states(receipt), REFUSED_RUN)

    def test_a_refused_run_whose_reason_text_is_not_known_says_cannot_tell_for_it(self):
        receipt = core.build_receipt(REFUSED, ran_facts(launched=False, reason_text=None))
        self.assertEqual(receipt["ending"]["reason_text"], pair(fixed.CANNOT_TELL))


class TheBuilderChecksWhatAPairHolds(unittest.TestCase):
    def test_a_value_that_json_cannot_hold_is_a_problem(self):
        for bad in (
            float("nan"),
            float("inf"),
            float("-inf"),
            b"x",
            object(),
            {1},
            (1, 2),
            {1: "a"},
            [float("nan")],
            {"a": object()},
        ):
            with self.subTest(repr(bad)):
                self.assertIsNotNone(pairs.problem_with(pair("value", bad)))

    def test_a_list_that_holds_itself_is_a_problem(self):
        loop = []
        loop.append(loop)
        self.assertIsNotNone(pairs.problem_with(pair("value", loop)))

    def test_plain_json_values_are_accepted(self):
        for good in ("text", 0, -3, 0.5, False, True, ["a", 1, [2.5]], {"a": {"b": ["c"]}}, "none"):
            with self.subTest(repr(good)):
                self.assertIsNone(pairs.problem_with(pair("value", good)))

    def test_a_word_for_a_state_held_as_a_value_in_the_ending_group_is_a_problem(self):
        for name in ("ending", "reason", "failed_step", "reason_text"):
            for word in (fixed.NONE, fixed.CANNOT_TELL, fixed.NOT_BUILT):
                with self.subTest(field=name, word=word):
                    receipt = core.build_receipt(ENDED, ran_facts())
                    receipt["ending"][name] = pair("value", word)
                    self.assertNotEqual(core.check_receipt(receipt), [])

    def test_the_word_none_is_still_a_value_in_a_field_with_its_own_text(self):
        receipt = core.build_receipt(ENDED, ran_facts(host="none"))
        self.assertEqual(core.check_receipt(receipt), [])


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
                "record_version": fixed.RECORD_VERSION,
            },
        )


if __name__ == "__main__":
    unittest.main()
