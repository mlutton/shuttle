"""By value: the ending is a pure function of facts."""
import unittest

from shuttle import core, fixed


def facts(**changes):
    base = {
        "refusal": None,
        "launch": "ok",
        "wait": "exited",
        "stop": "confirmed",
        "closing_freeze": "ok",
        "delivery": "ok",
        "exit_code": 0,
    }
    base.update(changes)
    return base


def decision(ending, reason=fixed.NONE, failed_step=fixed.NONE):
    return {"ending": ending, "reason": reason, "failed_step": failed_step}


class DecideEndingTable(unittest.TestCase):
    CASES = [
        ("ended by itself", facts(), decision("ended_by_itself")),
        ("time limit", facts(wait="time_limit"), decision("time_limit", "time_limit")),
        ("stop record", facts(wait="stop_record"), decision("stopped_from_outside", "stop_record")),
        ("signal to execution", facts(wait="signal"), decision("stopped_from_outside", "signal")),
        ("launch failed", facts(launch="failed", wait=None, stop=None, closing_freeze=None, delivery=None),
         decision("could_not_start", "launch_failed", "launch")),
        ("stop record before launch", facts(launch="stopped_before", wait=None, stop=None, closing_freeze=None, delivery=None),
         decision("could_not_start", "stopped")),
        ("refused by a check", facts(refusal={"reason": "unknown_field", "step": "input_check"}, launch=None, wait=None, stop=None, closing_freeze=None, delivery=None),
         decision("could_not_start", "unknown_field", "input_check")),
        ("stop not confirmed", facts(stop="not_confirmed"), decision("execution_failed", "stop_not_confirmed", "stop_not_confirmed")),
        ("closing freeze failed", facts(closing_freeze="failed"), decision("execution_failed", "closing_freeze_failed", "closing_freeze")),
        ("delivery failed", facts(delivery="failed"), decision("execution_failed", "delivery_failed", "delivery")),
        ("stop not confirmed beats a time limit", facts(wait="time_limit", stop="not_confirmed"),
         decision("execution_failed", "stop_not_confirmed", "stop_not_confirmed")),
        ("time limit with failed delivery is execution failed", facts(wait="time_limit", delivery="failed"),
         decision("execution_failed", "delivery_failed", "delivery")),
    ]

    def test_table(self):
        for name, given, expected in self.CASES:
            with self.subTest(name):
                self.assertEqual(core.decide_ending(given), expected)

    def test_executor_exit_code_never_changes_the_ending(self):
        for name, given, expected in self.CASES:
            for code in (0, 1, 2, 127, 255, -9, None):
                with self.subTest(case=name, exit_code=code):
                    self.assertEqual(core.decide_ending(dict(given, exit_code=code)), expected)

    def test_a_failure_after_the_ending_is_known_changes_nothing(self):
        later = {
            "observation": "failed",
            "kept_files": "failed",
            "teardown": "failed",
            "record_written": False,
        }
        for name, given, expected in self.CASES:
            with self.subTest(name):
                self.assertEqual(core.decide_ending(dict(given, **later)), expected)

    def test_every_decision_uses_listed_values(self):
        for name, given, expected in self.CASES:
            with self.subTest(name):
                self.assertEqual(core.check_decision(expected), [])

    def test_a_decision_with_a_value_off_the_list_is_rejected(self):
        self.assertNotEqual(core.check_decision(decision("record_failed")), [])
        self.assertNotEqual(core.check_decision(decision("could_not_start", "mystery", "launch")), [])
        self.assertNotEqual(core.check_decision(decision("could_not_start", "launch_failed", "record")), [])
        self.assertNotEqual(core.check_decision(decision("time_limit", "launch_failed")), [])


class ReceiptEndingConflicts(unittest.TestCase):
    def test_a_receipt_that_keeps_the_known_ending_is_accepted(self):
        known = decision("time_limit", "time_limit")
        receipt = {"the_ending": dict(known)}
        self.assertEqual(core.ending_conflicts(known, receipt), [])

    def test_a_receipt_whose_ending_changed_after_a_later_failure_is_rejected(self):
        known = decision("ended_by_itself")
        for changed in (
            decision("execution_failed", "delivery_failed", "delivery"),
            decision("ended_by_itself", "lost"),
            decision("ended_by_itself", fixed.NONE, "launch"),
        ):
            with self.subTest(changed):
                receipt = {"the_ending": dict(changed)}
                self.assertNotEqual(core.ending_conflicts(known, receipt), [])


if __name__ == "__main__":
    unittest.main()
