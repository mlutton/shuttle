"""By value: the table of cases for a run's ending.

Facts go in; (ending, reason, failed step) comes out. Reason, step and ending
must agree with the fixed list, and the core refuses a pairing the list does
not allow.
"""

import itertools
import unittest

from shuttle.core import decisions as core
from shuttle.core import fixed


def facts(**changes):
    """A run in which every step went well and the executor ended by itself."""
    base = {
        "id_claim": "ok",
        "input_check": None,
        "executor_driver_check": None,
        "gates": "ok",
        "setup": "ok",
        "opening_freeze": "ok",
        "launch": "ok",
        "wait": "exited",
        "stop": "confirmed",
        "closing_freeze": "ok",
        "delivery": "ok",
        "exit_code": 0,
        "child_signal": None,
    }
    base.update(changes)
    return base


def early(**changes):
    """A run that stopped before launch: later steps never ran, so their facts are absent."""
    base = {"id_claim": "ok", "input_check": None, "executor_driver_check": None}
    base.update(changes)
    return base


def d(ending, reason=fixed.NONE, failed_step=fixed.NONE):
    return {"ending": ending, "reason": reason, "failed_step": failed_step}


CNS = "could_not_start"
EF = "execution_failed"

# (name, facts, expected decision)
TABLE = [
    ("every step well, ended by itself", facts(), d("ended_by_itself")),
    (
        "stand-in steps reporting success",
        facts(
            gates="ok",
            setup="ok",
            opening_freeze="ok",
            stop="confirmed",
            closing_freeze="ok",
            delivery="ok",
        ),
        d("ended_by_itself"),
    ),
    # The order of a run, each step failing in turn.
    (
        "step 1/3: input check refuses",
        early(input_check="unknown_field"),
        d(CNS, "unknown_field", "input_check"),
    ),
    (
        "step 1/3: no time limit",
        early(input_check="no_time_limit"),
        d(CNS, "no_time_limit", "input_check"),
    ),
    ("step 2: request id used", {"id_claim": "used"}, d(CNS, "request_id_used", "id_claim")),
    (
        "step 2: records location unusable",
        {"id_claim": "unusable"},
        d(CNS, "records_location_unusable", "id_claim"),
    ),
    (
        "step 3: executor driver check refuses",
        early(executor_driver_check="tool_not_installed"),
        d(CNS, "tool_not_installed", "executor_driver_check"),
    ),
    (
        "step 3: a missing setting found by the executor driver check",
        early(executor_driver_check="missing_setting"),
        d(CNS, "missing_setting", "executor_driver_check"),
    ),
    ("step 4: a gate says no", early(gates="no"), d(CNS, "gate_said_no", "gates")),
    ("step 4: a gate fails", early(gates="failed"), d(CNS, "gate_failed", "gates")),
    ("step 5: setup fails", early(gates="ok", setup="failed"), d(CNS, "setup_failed", "setup")),
    (
        "step 6: opening freeze fails",
        early(gates="ok", setup="ok", opening_freeze="failed"),
        d(CNS, "freeze_failed", "opening_freeze"),
    ),
    (
        "step 7: launch fails",
        early(gates="ok", setup="ok", opening_freeze="ok", launch="failed"),
        d(CNS, "launch_failed", "launch"),
    ),
    (
        "step 7: launch raises an error of any kind (it is a failed launch)",
        early(gates="ok", setup="ok", opening_freeze="ok", launch="failed", exit_code=None),
        d(CNS, "launch_failed", "launch"),
    ),
    ("an interrupt before launch", early(launch="stopped_before"), d(CNS, "stopped")),
    (
        "step 8: the executor ends with exit code 0",
        facts(wait="exited", exit_code=0),
        d("ended_by_itself"),
    ),
    (
        "step 8: the executor exits non-zero",
        facts(wait="exited", exit_code=3),
        d("ended_by_itself"),
    ),
    (
        "step 8: the executor is killed by a signal",
        facts(wait="exited", exit_code=None, child_signal="SIGKILL"),
        d("ended_by_itself"),
    ),
    ("step 8: the time limit is reached", facts(wait="time_limit"), d("time_limit", "time_limit")),
    ("step 8: a stop record", facts(wait="stop_record"), d("stopped_from_outside", "stop_record")),
    (
        "step 8: an interrupt, terminate or hangup signal",
        facts(wait="signal"),
        d("stopped_from_outside", "signal"),
    ),
    (
        "step 8: waiting itself fails",
        facts(wait="error", stop=None, closing_freeze=None, delivery=None),
        d(EF, "stop_not_confirmed", "stop_not_confirmed"),
    ),
    (
        "step 9: stop not confirmed",
        facts(stop="not_confirmed", closing_freeze=None, delivery=None),
        d(EF, "stop_not_confirmed", "stop_not_confirmed"),
    ),
    (
        "step 9: stop not confirmed beats a time limit",
        facts(wait="time_limit", stop="not_confirmed", closing_freeze=None, delivery=None),
        d(EF, "stop_not_confirmed", "stop_not_confirmed"),
    ),
    (
        "step 9: stop not confirmed beats a cause that cannot be told",
        facts(wait="cannot_tell", stop="not_confirmed", closing_freeze=None, delivery=None),
        d(EF, "stop_not_confirmed", "stop_not_confirmed"),
    ),
    (
        "step 9: stop confirmed but why the scope ended cannot be read",
        facts(wait="cannot_tell", stop="confirmed", closing_freeze=None, delivery=None),
        d(EF, "execution_error", fixed.CANNOT_TELL),
    ),
    (
        "step 11: closing freeze fails",
        facts(closing_freeze="failed", delivery=None),
        d(EF, "closing_freeze_failed", "closing_freeze"),
    ),
    ("step 12: delivery fails", facts(delivery="failed"), d(EF, "delivery_failed", "delivery")),
    (
        "step 12: delivery fails after a time limit",
        facts(wait="time_limit", delivery="failed"),
        d(EF, "delivery_failed", "delivery"),
    ),
]


class DecideEndingTable(unittest.TestCase):
    def test_table(self):
        for name, given, expected in TABLE:
            with self.subTest(name):
                self.assertEqual(core.decide_ending(given), expected)

    def test_every_row_is_consistent_with_the_fixed_list(self):
        for name, _given, expected in TABLE:
            with self.subTest(name):
                self.assertEqual(core.check_decision(expected), [])

    def test_the_executor_exit_code_never_changes_the_ending(self):
        for name, given, expected in TABLE:
            for code in (0, 1, 2, 127, 255, None):
                with self.subTest(case=name, exit_code=code):
                    self.assertEqual(core.decide_ending(dict(given, exit_code=code)), expected)

    def test_a_failure_in_a_later_step_never_changes_an_ending_already_known(self):
        later = {
            "observe": "failed",
            "kept_files": "failed",
            "teardown": "failed",
            "record_written": False,
        }
        for name, given, expected in TABLE:
            with self.subTest(name):
                self.assertEqual(core.decide_ending(dict(given, **later)), expected)

    def test_a_reason_that_does_not_belong_to_the_step_that_names_it_is_an_execution_error(self):
        for given, step in (
            (early(input_check="launch_failed"), "input_check"),
            (early(input_check="tool_not_installed"), "input_check"),
            (early(executor_driver_check="unknown_field"), "executor_driver_check"),
            (early(input_check="time_limit"), "input_check"),
            (early(input_check="not a code"), "input_check"),
        ):
            with self.subTest(given):
                self.assertEqual(core.decide_ending(given), d(CNS, "execution_error", step))

    def test_facts_that_cannot_decide_are_an_execution_error_not_a_guess(self):
        for given, expected in (
            (
                early(gates="ok", setup="ok", opening_freeze="ok"),
                d(CNS, "execution_error", "launch"),
            ),
            (dict(facts(), wait=None), d(EF, "execution_error", fixed.CANNOT_TELL)),
            (dict(facts(), wait="vanished"), d(EF, "execution_error", fixed.CANNOT_TELL)),
            (dict(facts(), launch="maybe"), d(CNS, "execution_error", "launch")),
            (dict(facts(), stop=fixed.CANNOT_TELL), d(EF, "execution_error", fixed.CANNOT_TELL)),
            (dict(facts(), closing_freeze=None), d(EF, "execution_error", fixed.CANNOT_TELL)),
            (
                dict(facts(), delivery=fixed.CANNOT_TELL),
                d(EF, "execution_error", fixed.CANNOT_TELL),
            ),
            (dict(facts(), gates=fixed.CANNOT_TELL), d(CNS, "execution_error", "gates")),
            ("not a dict", d(EF, "execution_error", fixed.CANNOT_TELL)),
        ):
            with self.subTest(given):
                self.assertEqual(core.decide_ending(given), expected)

    def test_the_decision_is_total_over_every_combination_of_fact_values(self):
        missing = object()
        domain = {
            "id_claim": ("ok", "used", missing, fixed.CANNOT_TELL),
            "input_check": (None, "unknown_field", fixed.CANNOT_TELL),
            "executor_driver_check": (None, "tool_not_installed", fixed.CANNOT_TELL),
            "gates": ("ok", "no", fixed.CANNOT_TELL),
            "setup": ("ok", "failed", fixed.CANNOT_TELL),
            "opening_freeze": ("ok", "failed", fixed.CANNOT_TELL),
            "launch": ("ok", "failed", "stopped_before", fixed.CANNOT_TELL),
            "wait": ("exited", "time_limit", "signal", "error", fixed.CANNOT_TELL),
            "stop": ("confirmed", "not_confirmed", fixed.CANNOT_TELL),
            "closing_freeze": ("ok", "failed", fixed.CANNOT_TELL),
            "delivery": ("ok", "failed", fixed.CANNOT_TELL),
        }
        names = list(domain)
        count = 0
        for values in itertools.product(*(domain[n] for n in names)):
            given = {n: v for n, v in zip(names, values, strict=True) if v is not missing}
            got = core.decide_ending(given)
            if core.check_decision(got):
                self.fail(f"{given!r} gave {got!r}, which the list does not allow")
            count += 1
        self.assertGreater(count, 100000)


class PairingsTheListForbids(unittest.TestCase):
    def test_forbidden_pairings_are_refused(self):
        for decision in (
            d(CNS, "launch_failed", "gates"),
            d(CNS, "launch_failed"),
            d(CNS, "stopped", "launch"),
            d(CNS),
            d(EF, "delivery_failed", "closing_freeze"),
            d(EF, "stop_not_confirmed"),
            d(EF, "lost", "delivery"),
            d("time_limit", "time_limit", "launch"),
            d("time_limit", "launch_failed", "launch"),
            d("ended_by_itself", fixed.NONE, "launch"),
            d("ended_by_itself", "lost"),
            d("record_failed"),
            d(CNS, "launch_failed", "record"),
            d("time_limit", "execution_error"),
            d(CNS, "execution_error", "delivery"),
            d(EF, "execution_error", "gates"),
            d(CNS, "execution_error", fixed.CANNOT_TELL),
            d(CNS, "execution_error"),
        ):
            with self.subTest(decision):
                self.assertNotEqual(core.check_decision(decision), [])

    def test_allowed_pairings_are_accepted(self):
        for decision in (
            d(EF, "lost", fixed.CANNOT_TELL),
            d(CNS, "missing_setting", "input_check"),
            d(CNS, "missing_setting", "executor_driver_check"),
            d(CNS, "records_location_unusable", "id_claim"),
            d("stopped_from_outside", "signal"),
            d(CNS, "execution_error", "input_check"),
            d(CNS, "execution_error", "launch"),
            d(EF, "execution_error", fixed.CANNOT_TELL),
            d(EF, "execution_error", "delivery"),
        ):
            with self.subTest(decision):
                self.assertEqual(core.check_decision(decision), [])


class ReceiptEndingConflicts(unittest.TestCase):
    def test_a_receipt_that_keeps_the_known_ending_is_accepted(self):
        known = d("time_limit", "time_limit")
        self.assertEqual(core.ending_conflicts(known, {"ending": dict(known)}), [])

    def test_a_receipt_whose_ending_changed_after_a_later_failure_is_rejected(self):
        known = d("ended_by_itself")
        for changed in (
            d(EF, "delivery_failed", "delivery"),
            d("ended_by_itself", "lost"),
            d("ended_by_itself", fixed.NONE, "launch"),
        ):
            with self.subTest(changed):
                self.assertNotEqual(core.ending_conflicts(known, {"ending": dict(changed)}), [])


if __name__ == "__main__":
    unittest.main()
