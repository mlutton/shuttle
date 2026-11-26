"""Injection tables: replace one step with one that fails, or sets the signal fact.

The run takes its steps as a table, so a test replaces any one of them. Whatever
happens after the request id is claimed, an outcome record exists.
"""

import io
import json
import os
import sys
import tempfile
import unittest

from shuttle.core import decisions as core
from shuttle.shell import run
from shuttle.world import real


class QuickClock(run.Clock):
    """Real time, but each poll waits a thousandth of a second, so a child that exits at once is seen at once."""

    def sleep(self, seconds):
        super().sleep(0.001)


AFTER_THE_CLAIM = [name for name, _ in run.STEPS][2:14]  # steps 3 to 14
CNS, EF = "could_not_start", "execution_failed"

# Step that raises -> (ending, reason, failed step), from the table of cases.
IF_IT_RAISES = {
    "run_input_checks_and_executor_driver_check": (CNS, "execution_error", "executor_driver_check"),
    "run_gates": (CNS, "gate_failed", "gates"),
    "set_up_run_area": (CNS, "setup_failed", "setup"),
    "take_opening_fingerprint": (CNS, "freeze_failed", "opening_freeze"),
    "launch_executor": (CNS, "launch_failed", "launch"),
    "wait_for_the_end": (EF, "stop_not_confirmed", "stop_not_confirmed"),
    "stop_everything_and_confirm_empty": (EF, "stop_not_confirmed", "stop_not_confirmed"),
    "observe": ("ended_by_itself", "none", "none"),
    "take_closing_freeze": (EF, "closing_freeze_failed", "closing_freeze"),
    "deliver": (EF, "delivery_failed", "delivery"),
    "move_kept_files": ("ended_by_itself", "none", "none"),
    "tear_down": ("ended_by_itself", "none", "none"),
}

# Signal fact set during a step -> ending.
IF_SIGNALLED = {name: (CNS, "stopped", "none") for name in AFTER_THE_CLAIM[:4]}  # steps 3 to 6
IF_SIGNALLED.update(
    {
        name: ("stopped_from_outside", "signal", "none")
        for name in ("launch_executor", "wait_for_the_end")
    }
)
IF_SIGNALLED.update({name: ("ended_by_itself", "none", "none") for name in AFTER_THE_CLAIM[6:]})


# The child ends at once, except where a case needs a live process: there it sleeps until the run
# ends it (the run asks it to end as soon as the signal fact is seen, so nothing waits out the sleep).
ENDS_AT_ONCE = "pass"
STAYS_ALIVE = "import time; time.sleep(60)"
NEEDS_A_LIVE_PROCESS = ("launch_executor", "wait_for_the_end")


def boom(state):
    raise RuntimeError("injected")


class InjectionTables(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.records = os.path.join(self.root, "records")
        os.mkdir(self.records)
        self.doc = os.path.join(self.root, "input.json")
        with open(self.doc, "w") as f:
            json.dump(
                {
                    "format_version": 1,
                    "request_id": "inj-1",
                    "records_location": self.records,
                    "thread": "t",
                    "round": 1,
                    "kind": "plain",
                    "time_limit_seconds": 30,
                    "executor": {
                        "name": "command",
                        "settings": {"command": sys.executable, "arguments": ["-c", ENDS_AT_ONCE]},
                    },
                },
                f,
            )

    def run_it(self, steps=None, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        code = run.run(
            self.doc, out, err, real.OPERATIONS, steps=steps, clock=QuickClock(), **kwargs
        )
        return code, out.getvalue().splitlines(), err.getvalue()

    def use_script(self, code):
        with open(self.doc) as f:
            document = json.load(f)
        document["executor"]["settings"]["arguments"] = ["-c", code]
        with open(self.doc, "w") as f:
            json.dump(document, f)

    def replaced(self, name, function):
        return [(n, function if n == name else f) for n, f in run.STEPS]

    def outcome(self):
        path = os.path.join(self.records, "inj-1.outcome.json")
        self.assertTrue(
            os.path.exists(path), f"no outcome record; files: {os.listdir(self.records)}"
        )
        with open(path) as f:
            return json.load(f)

    def clean(self):
        for name in os.listdir(self.records):
            os.remove(os.path.join(self.records, name))

    def test_a_step_after_the_claim_that_raises_still_gives_an_outcome_record_and_the_ending_the_table_says(
        self,
    ):
        for name in AFTER_THE_CLAIM:
            with self.subTest(name):
                self.clean()
                code, lines, err = self.run_it(self.replaced(name, boom))
                self.assertEqual(code, 0, err)
                ending = self.outcome()["receipt"]["the_ending"]
                self.assertEqual(
                    (ending["ending"], ending["reason"], ending["failed_step"]), IF_IT_RAISES[name]
                )
                self.assertEqual(lines[-1], IF_IT_RAISES[name][0])
                self.assertEqual(core.check_receipt(self.outcome()["receipt"]), [])

    def test_the_last_step_itself_raising_still_gives_an_outcome_record(self):
        code, lines, err = self.run_it(self.replaced("write_outcome_record", boom))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.outcome()["receipt"]["the_ending"]["ending"], "ended_by_itself")
        self.assertEqual(lines[-1], "ended_by_itself")

    def test_a_signal_fact_set_during_any_step_after_the_claim_still_gives_an_outcome_record(self):
        for name in AFTER_THE_CLAIM:
            with self.subTest(name):
                self.clean()
                self.use_script(STAYS_ALIVE if name in NEEDS_A_LIVE_PROCESS else ENDS_AT_ONCE)
                real = dict(run.STEPS)[name]

                def signalled(state, real=real):
                    state["signal"] = state["signal"] or "SIGINT"
                    real(state)

                code, lines, err = self.run_it(self.replaced(name, signalled))
                self.assertEqual(code, 0, err)
                ending = self.outcome()["receipt"]["the_ending"]
                self.assertEqual(
                    (ending["ending"], ending["reason"], ending["failed_step"]), IF_SIGNALLED[name]
                )

    def test_building_the_receipt_failing_writes_a_minimal_receipt_with_the_same_ending(self):
        def broken(decision, facts):
            raise RuntimeError("injected")

        code, lines, err = self.run_it(build_receipt=broken)
        self.assertEqual(code, 0, err)
        receipt = self.outcome()["receipt"]
        self.assertEqual(receipt["the_ending"]["ending"], "ended_by_itself")
        self.assertEqual(receipt["what_execution_saw"]["exit_code"], "cannot tell")
        self.assertEqual(lines[-1], "ended_by_itself")

    def test_writing_the_record_failing_prints_the_receipt_then_the_ending_and_exits_non_zero(self):
        def broken(location, request_id, record):
            raise RuntimeError("injected")

        code, lines, err = self.run_it(write_record=broken)
        self.assertNotEqual(code, 0)
        self.assertEqual(lines[0], "inj-1")
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertEqual(
            json.loads("\n".join(lines[1:-1]))["the_ending"]["ending"], "ended_by_itself"
        )
        self.assertIn("not written", err)
        self.assertFalse(os.path.exists(os.path.join(self.records, "inj-1.outcome.json")))

    def test_an_error_in_the_claim_step_prints_the_refusal_then_could_not_start_and_writes_nothing(
        self,
    ):
        code, lines, err = self.run_it(self.replaced("claim_request_id", boom))
        self.assertNotEqual(code, 0)
        self.assertEqual(lines, ["inj-1", CNS])
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertEqual(os.listdir(self.records), [])

    def test_no_message_says_the_run_ended_without_a_conclusion(self):
        with open(run.__file__) as f:
            self.assertNotIn("without a conclusion", f.read())


if __name__ == "__main__":
    unittest.main()
