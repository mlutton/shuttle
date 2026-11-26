"""By value: which steps run, what an error in a step means, and what is printed."""

import unittest

from shuttle.core import decisions as core
from shuttle.shell import run

ORDER = [
    "read_and_validate_document",
    "claim_request_id",
    "run_input_checks_and_executor_driver_check",
    "run_gates",
    "set_up_run_area",
    "take_opening_fingerprint",
    "launch_executor",
    "wait_for_the_end",
    "stop_everything_and_confirm_empty",
    "observe",
    "take_closing_freeze",
    "deliver",
    "move_kept_files",
    "tear_down",
    "write_outcome_record",
]

LAUNCHED = {"header_source": {}, "launch": "ok", "wait": "exited", "stop": "confirmed"}


def runs(facts):
    return [name for name in ORDER if core.step_runs(name, facts)]


class StepsRun(unittest.TestCase):
    def test_the_fifteen_steps_are_in_the_order_of_a_run(self):
        self.assertEqual(list(core.STEP_ORDER), ORDER)
        self.assertEqual([name for name, _ in run.STEPS], ORDER)

    def test_a_good_run_runs_every_step_once_the_document_is_read(self):
        self.assertEqual(runs({}), ORDER[:1] + ["write_outcome_record"])
        self.assertEqual(runs(LAUNCHED), ORDER[1:])

    def test_an_unreadable_document_runs_only_the_last_step(self):
        self.assertEqual(runs({"unreadable": "x"}), ["write_outcome_record"])

    def test_a_used_request_id_or_unusable_records_location_runs_only_the_last_step(self):
        for claim in ("used", "unusable"):
            with self.subTest(claim):
                self.assertEqual(
                    runs({"header_source": {}, "id_claim": claim}), ["write_outcome_record"]
                )

    def test_a_refusal_before_launch_still_claims_the_id_and_writes_the_record(self):
        for facts in (
            {"header_source": {}, "input_check": "unknown_field"},
            {"header_source": {}, "id_claim": "ok", "executor_driver_check": "tool_not_installed"},
            {"header_source": {}, "id_claim": "ok", "gates": "failed"},
            {"header_source": {}, "id_claim": "ok", "setup": "failed"},
            {"header_source": {}, "id_claim": "ok", "opening_freeze": "failed"},
            {"header_source": {}, "id_claim": "ok", "launch": "failed"},
            {"header_source": {}, "id_claim": "ok", "launch": "stopped_before"},
        ):
            with self.subTest(facts):
                self.assertEqual(runs(facts), ["claim_request_id", "write_outcome_record"])

    def test_a_failed_stop_confirmation_takes_no_closing_freeze_and_delivers_nothing(self):
        got = runs(dict(LAUNCHED, stop="not_confirmed"))
        self.assertNotIn("take_closing_freeze", got)
        self.assertNotIn("deliver", got)
        self.assertIn("write_outcome_record", got)
        self.assertIn("tear_down", got)

    def test_the_closing_freeze_and_delivery_run_only_when_the_stop_is_confirmed(self):
        # A fingerprint taken before everything has stopped would be rejected by construction:
        # the step that takes it does not run unless the stop is confirmed.
        for stop in (None, "not_confirmed", "unknown"):
            with self.subTest(stop=stop):
                facts = dict(LAUNCHED)
                if stop is None:
                    del facts["stop"]
                else:
                    facts["stop"] = stop
                got = runs(facts)
                self.assertNotIn("take_closing_freeze", got)
                self.assertNotIn("deliver", got)
        self.assertIn("take_closing_freeze", runs(LAUNCHED))
        self.assertIn("deliver", runs(LAUNCHED))

    def test_a_failed_wait_counts_as_a_stop_not_confirmed(self):
        got = runs(dict(LAUNCHED, wait="error"))
        self.assertNotIn("take_closing_freeze", got)

    def test_a_failed_closing_freeze_delivers_nothing(self):
        got = runs(dict(LAUNCHED, closing_freeze="failed"))
        self.assertNotIn("deliver", got)
        self.assertIn("move_kept_files", got)


class ErrorsAndInterrupts(unittest.TestCase):
    def test_an_error_in_a_step_becomes_the_fact_that_step_reports(self):
        expected = {
            "claim_request_id": {"id_claim": "unusable"},
            "run_input_checks_and_executor_driver_check": {
                "executor_driver_check": "execution_error"
            },
            "run_gates": {"gates": "failed"},
            "set_up_run_area": {"setup": "failed"},
            "take_opening_fingerprint": {"opening_freeze": "failed"},
            "launch_executor": {"launch": "failed"},
            "wait_for_the_end": {"wait": "error"},
            "stop_everything_and_confirm_empty": {"stop": "not_confirmed"},
            "take_closing_freeze": {"closing_freeze": "failed"},
            "deliver": {"delivery": "failed"},
            "read_and_validate_document": {"unreadable": True},
        }
        for name in ORDER:
            with self.subTest(name):
                self.assertEqual(core.facts_after_error(name), expected.get(name, {}))

    def test_a_signal_before_launch_is_a_stop_before_launch(self):
        self.assertEqual(
            core.facts_after_signal({"header_source": {}}, "SIGINT"), {"launch": "stopped_before"}
        )

    def test_a_signal_after_launch_adds_no_fact_here_the_wait_sees_it(self):
        self.assertEqual(core.facts_after_signal(LAUNCHED, "SIGINT"), {})

    def test_no_signal_adds_no_fact(self):
        self.assertEqual(core.facts_after_signal({"header_source": {}}, None), {})


class MinimalReceipt(unittest.TestCase):
    def test_it_holds_the_decision_and_cannot_tell_for_every_other_field(self):
        decision = {"ending": "time_limit", "reason": "time_limit", "failed_step": "none"}
        receipt = core.minimal_receipt(decision)
        self.assertEqual(core.check_receipt(receipt), [])
        self.assertEqual(core.ending_conflicts(decision, receipt), [])
        self.assertEqual(receipt["execution"]["exit_code"], {"state": "cannot tell", "value": None})


class WhatIsPrinted(unittest.TestCase):
    ENDED = {"ending": "ended_by_itself", "reason": "none", "failed_step": "none"}
    USED = {"ending": "could_not_start", "reason": "request_id_used", "failed_step": "id_claim"}

    def test_rows(self):
        cases = [
            (
                "record written",
                {"kind": "written", "decision": self.ENDED, "path": "/r/x.outcome.json"},
                {"stdout": ["/r/x.outcome.json", "ended_by_itself"], "stderr": [], "exit": 0},
            ),
            (
                "unreadable document",
                {"kind": "unreadable", "problem": "bad"},
                {"stdout": ["none"], "stderr": ["shuttle: bad"], "exit": 1},
            ),
            (
                "refused with nothing written",
                {"kind": "not_recorded", "decision": self.USED, "problem": "used"},
                {"stdout": ["could_not_start"], "stderr": ["shuttle: used"], "exit": 1},
            ),
            (
                "record could not be written",
                {
                    "kind": "write_failed",
                    "decision": self.ENDED,
                    "receipt_text": "{}",
                    "problem": "OSError",
                },
                {
                    "stdout": ["{}", "ended_by_itself"],
                    "stderr": [
                        "shuttle: the outcome record was not written (OSError); the receipt is printed below and the ending stands"
                    ],
                    "exit": 1,
                },
            ),
        ]
        for name, given, expected in cases:
            with self.subTest(name):
                self.assertEqual(core.conclude(given), expected)

    def test_exit_zero_only_when_a_record_was_written(self):
        for kind in ("unreadable", "not_recorded", "write_failed"):
            got = core.conclude(
                {"kind": kind, "decision": self.ENDED, "problem": "p", "receipt_text": "{}"}
            )
            self.assertNotEqual(got["exit"], 0)


class Environment(unittest.TestCase):
    def test_a_missing_variable_has_its_own_reason_text(self):
        reason, text = core.executor_driver_check(
            "tool", ["NAMED", "OTHER"], {"PATH": "/bin"}, tool_found=True
        )
        self.assertEqual(reason, "missing_setting")
        self.assertIn("NAMED", text)
        self.assertIn("OTHER", text)
        self.assertNotIn("not found", text)

    def test_a_missing_tool_has_its_own_reason_text(self):
        reason, text = core.executor_driver_check("tool", [], {"PATH": "/bin"}, tool_found=False)
        self.assertEqual(reason, "tool_not_installed")
        self.assertIn("tool", text)

    def test_nothing_missing_is_no_refusal(self):
        self.assertEqual(
            core.executor_driver_check("tool", ["A"], {"A": "1"}, tool_found=True), (None, None)
        )

    def test_the_executor_gets_path_and_the_named_variables_only(self):
        caller = {"PATH": "/bin", "HOME": "/h", "TOKEN": "s3", "NAMED": "v"}
        self.assertEqual(core.build_environment(["NAMED"], caller), {"PATH": "/bin", "NAMED": "v"})
        self.assertEqual(core.build_environment([], caller), {"PATH": "/bin"})

    def test_a_name_missing_from_the_callers_environment_is_refused(self):
        self.assertEqual(core.check_environment(["NAMED"], {"PATH": "/bin"}), "missing_setting")
        self.assertIsNone(core.check_environment(["NAMED"], {"NAMED": ""}))


if __name__ == "__main__":
    unittest.main()
