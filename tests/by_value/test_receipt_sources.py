"""By value: an odd value from any one source costs that one field and no other.

The builder stays strict and refuses a bad pair. The code that turns what execution saw into pairs
never hands it one: an empty text is "none" (execution looked and there was nothing), and
anything JSON cannot hold, or a number that is not finite, is "cannot tell" for that field alone.
"""

import copy
import importlib
import os
import sys
import unittest

from shuttle.core import decisions as core
from shuttle.core import fixed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

ENDED = {"ending": "ended_by_itself", "reason": fixed.NONE, "failed_step": fixed.NONE}


def a_loop():
    loop = []
    loop.append(loop)
    return loop


# Values a source might hand over: an empty text and odd things, each with the state it must get.
ODD = {
    # A fact that is None looked and found nothing; a step that returns None, or leaves its key
    # out, could not say, so for a step's key None is "cannot tell". False is a value.
    "a missing value (None)": (None, fixed.NONE),
    "false": (False, fixed.VALUE),
    "empty text": ("", fixed.NONE),
    "empty list": ([], fixed.NONE),
    "empty dictionary": ({}, fixed.NONE),
    "not a number": (float("nan"), fixed.CANNOT_TELL),
    "infinity": (float("inf"), fixed.CANNOT_TELL),
    "bytes": (b"x", fixed.CANNOT_TELL),
    "an object": (object(), fixed.CANNOT_TELL),
    "a set": ({1}, fixed.CANNOT_TELL),
    "a tuple": ((1, 2), fixed.CANNOT_TELL),
    "a dictionary with a number for a key": ({1: "a"}, fixed.CANNOT_TELL),
    "a list that holds itself": (a_loop(), fixed.CANNOT_TELL),
}

# Every step a run has, as a real (not a stand-in) step would return it.
REAL_STEPS = {
    "gates": {"duration_seconds": 1.5},
    "opening_fingerprint": {"fingerprint": "f1", "duration_seconds": 0.25},
    "closing_freeze": {
        "fingerprint": "f2",
        "duration_seconds": 0.5,
        "files_added": 3,
        "files_changed": 1,
        "files_deleted": 2,
    },
    "delivery": {
        "duration_seconds": 0.75,
        "delivered": True,
        "branch": "b",
        "branch_reason": "r",
    },
    "kept_files": {
        "files_list": "list",
        "session_file": "session",
        "statement_state": "written",
        "statement_hash": "h",
        "statement_location": "where",
        "claim": "done",
    },
    "teardown": {"failure": "none"},
    "stop_confirmation": {"everything_stopped": True, "stop_reason": "r", "stop_asker": "a"},
    "boundary": {"peak_memory_bytes": 1000, "processor_time_seconds": 2.5},
}


def facts(**changes):
    base = {
        "receipt_id": "r-1",
        "execution_version": "9.9.9",
        "host": "somehost",
        "input_hash": "abc123",
        "launched": True,
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:00:01Z",
        "executor_duration": 0.9,
        "exit_code": 7,
        "signal": "SIGTERM",
        "executor_driver_observations": None,
        "stand_ins": copy.deepcopy(REAL_STEPS),
        "reason_text": "a reason",
    }
    base.update(changes)
    return base


def with_step_value(step, key, held):
    steps = copy.deepcopy(REAL_STEPS)
    steps[step][key] = held
    return facts(stand_ins=steps)


# (the source, how to hand it an odd value, the one field it feeds)
SOURCES = [
    ("the host name", lambda v: facts(host=v), ("execution", "host")),
    ("the receipt id", lambda v: facts(receipt_id=v), ("ending", "receipt_id")),
    (
        "execution's version",
        lambda v: facts(execution_version=v),
        ("execution", "execution_version"),
    ),
    ("the input hash", lambda v: facts(input_hash=v), ("execution", "input_hash")),
    ("the start time", lambda v: facts(started_at=v), ("execution", "started_at")),
    ("the end time", lambda v: facts(ended_at=v), ("execution", "ended_at")),
    (
        "the executor's duration",
        lambda v: facts(executor_duration=v),
        ("execution", "duration_executor_seconds"),
    ),
    ("the exit code", lambda v: facts(exit_code=v), ("execution", "exit_code")),
    ("the signal", lambda v: facts(signal=v), ("execution", "signal")),
    ("the reason text", lambda v: facts(reason_text=v), ("ending", "reason_text")),
    *[
        (
            f"the {key} the {step} step returns",
            lambda v, step=step, key=key: with_step_value(step, key, v),
            field,
        )
        for step, key, field in [
            ("gates", "duration_seconds", ("execution", "duration_gates_seconds")),
            (
                "opening_fingerprint",
                "duration_seconds",
                ("execution", "duration_opening_freeze_seconds"),
            ),
            ("opening_fingerprint", "fingerprint", ("execution", "fingerprint_before")),
            (
                "closing_freeze",
                "duration_seconds",
                ("execution", "duration_closing_freeze_seconds"),
            ),
            ("closing_freeze", "fingerprint", ("execution", "fingerprint_after")),
            ("closing_freeze", "files_added", ("execution", "files_added")),
            ("closing_freeze", "files_changed", ("execution", "files_changed")),
            ("closing_freeze", "files_deleted", ("execution", "files_deleted")),
            ("delivery", "duration_seconds", ("execution", "duration_delivery_seconds")),
            ("delivery", "delivered", ("execution", "delivered")),
            ("delivery", "branch", ("execution", "delivery_branch")),
            ("delivery", "branch_reason", ("execution", "delivery_branch_reason")),
            ("kept_files", "files_list", ("execution", "files_list_kept_file")),
            ("kept_files", "session_file", ("execution", "session_file_kept_at")),
            ("kept_files", "statement_state", ("executor", "statement_state")),
            ("kept_files", "statement_hash", ("executor", "statement_hash")),
            ("kept_files", "statement_location", ("executor", "statement_location")),
            ("kept_files", "claim", ("executor", "claim")),
            ("teardown", "failure", ("execution", "teardown_failure")),
            ("stop_confirmation", "everything_stopped", ("ending", "everything_stopped")),
            ("stop_confirmation", "stop_reason", ("execution", "stop_reason")),
            ("stop_confirmation", "stop_asker", ("execution", "stop_asker")),
            ("boundary", "peak_memory_bytes", ("execution", "peak_memory_bytes")),
            ("boundary", "processor_time_seconds", ("execution", "processor_time_seconds")),
        ]
    ],
]


REAL_STEP_OF = {}
for _source, _, _field in SOURCES:
    if "step returns" in _source:
        _key, _step = (
            _source[len("the ") :].split(" the ")[0],
            _source.split(" the ")[1].split(" step")[0],
        )
        REAL_STEP_OF[_source] = (_step, _key)


def every_field(receipt):
    return {
        (group, name): held for group, fields in receipt.items() for name, held in fields.items()
    }


class AnOddValueCostsOnlyItsOwnField(unittest.TestCase):
    def test_every_other_field_keeps_its_observed_value(self):
        baseline = every_field(core.build_receipt(ENDED, facts()))
        for source, make, field in SOURCES:
            for what, (odd, _) in ODD.items():
                with self.subTest(source=source, odd=what):
                    receipt = core.build_receipt(ENDED, make(odd))  # the builder does not refuse
                    self.assertEqual(core.check_receipt(receipt), [])
                    others = {k: v for k, v in every_field(receipt).items() if k != field}
                    self.assertEqual(others, {k: v for k, v in baseline.items() if k != field})

    def test_the_one_field_says_none_for_nothing_and_cannot_tell_for_what_cannot_be_held(self):
        for source, make, field in SOURCES:
            for what, (odd, state) in ODD.items():
                if odd is None and ("step returns" in source or source == "the input hash"):
                    state = fixed.CANNOT_TELL
                expected = {"state": state, "value": odd if state == fixed.VALUE else None}
                with self.subTest(source=source, odd=what):
                    held = every_field(core.build_receipt(ENDED, make(odd)))[field]
                    self.assertEqual(held, expected)

    def test_a_step_that_leaves_its_key_out_says_cannot_tell_for_that_field_only(self):
        baseline = every_field(core.build_receipt(ENDED, facts()))
        for source, _, field in SOURCES:
            if "step returns" not in source:
                continue
            step, key = REAL_STEP_OF[source]
            steps = copy.deepcopy(REAL_STEPS)
            del steps[step][key]
            receipt = every_field(core.build_receipt(ENDED, facts(stand_ins=steps)))
            with self.subTest(source):
                self.assertEqual(receipt[field], {"state": fixed.CANNOT_TELL, "value": None})
                self.assertEqual(
                    {k: v for k, v in receipt.items() if k != field},
                    {k: v for k, v in baseline.items() if k != field},
                )

    def test_the_baseline_has_every_source_as_a_value(self):
        baseline = every_field(core.build_receipt(ENDED, facts()))
        for source, _, field in SOURCES:
            with self.subTest(source):
                self.assertEqual(baseline[field]["state"], fixed.VALUE)

    def test_a_driver_group_that_cannot_be_held_is_still_refused_by_the_builder(self):
        from shuttle.core.drivers import command

        observed = command.observe()
        observed["model"] = "bare"
        with self.assertRaises(core.ReceiptNotBuilt) as raised:
            core.build_receipt(ENDED, facts(executor_driver_observations=observed))
        self.assertTrue(any("model" in problem for problem in raised.exception.problems))


class AnEmptyHostNameInARealRun(unittest.TestCase):
    """A host name that is empty (a container whose name was set empty) costs the host field only."""

    def test_the_exit_code_is_in_the_receipt_and_the_host_is_none(self):
        world = scenes.scene(exit_code=7)
        world.host = ""
        code, lines, err = scenes.run_in(world)
        self.assertEqual((code, lines[-1], err), (0, "ended_by_itself", ""))
        receipt = scenes.outcome(world)["receipt"]
        self.assertEqual(receipt["execution"]["host"], {"state": "none", "value": None})
        self.assertEqual(flat(receipt)["execution"]["exit_code"], 7)
        self.assertEqual(receipt["ending"]["receipt_id"]["state"], "value")


class TheMinimalReceiptIsNeverSilent(unittest.TestCase):
    """If the builder still refuses (a bug), the run says so on standard error, in one line."""

    def test_a_refused_field_is_named_in_one_line_and_the_record_is_the_minimal_one(self):
        run = importlib.import_module("shuttle.shell.run")

        def a_driver_with_a_bare_string(state):
            from shuttle.core.drivers import command

            observed = command.observe()
            observed["model"] = "bare"
            state["executor_driver_observations"] = observed

        steps = [(n, a_driver_with_a_bare_string if n == "observe" else f) for n, f in run.STEPS]
        world = scenes.scene(exit_code=7)
        code, lines, err = scenes.run_in(world, steps)
        self.assertEqual((code, lines[-1]), (0, "ended_by_itself"))
        (line,) = err.splitlines()
        self.assertIn("executor_driver", line)
        self.assertIn("model", line)
        receipt = scenes.outcome(world)["receipt"]
        self.assertEqual(receipt["execution"]["exit_code"]["state"], fixed.CANNOT_TELL)
        self.assertEqual(flat(receipt)["ending"]["ending"], "ended_by_itself")

    def test_any_other_failure_to_build_it_is_named_in_one_line_too(self):
        world = scenes.scene()
        world.will_raise("identity.host_name", RuntimeError("injected"))
        code, _, err = scenes.run_in(world)
        self.assertEqual(code, 0)
        (line,) = err.splitlines()
        self.assertIn("RuntimeError", line)


if __name__ == "__main__":
    unittest.main()
