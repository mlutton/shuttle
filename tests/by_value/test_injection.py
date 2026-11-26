"""Injection tables: make one thing fail, or a signal arrive, and see what the run records.

The run is on the simulated world (tests/rehearsal/), which can fail any operation at any call
and deliver a signal at any call: no real disk, process or time. Whatever happens after the
request id is claimed, an outcome record exists.

Where an operation is the way into a step (a step that looks at the environment, starts a
process, polls it), the failure is made in the operation. Ten of the steps of a run are
placeholders that touch nothing (gates, set-up, fingerprints, stop confirmation, observing,
closing freeze, delivery, tidying, tear-down, and the write step itself raising outside its own
guard); no operation can be made to fail inside them, so those points are reached by passing
`run_steps` a table with one step replaced. When a placeholder becomes a real step that uses the
operations, its row moves from STEP_TABLE_ONLY to an operation and the table is no longer needed.
"""

import importlib
import json
import os
import sys
import unittest

from shuttle.core import decisions as core
from shuttle.shell import run

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")

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

# The operation that is the way into a step, and which call of it: the failure (or the signal)
# is made there. A step not in this table is a placeholder: it is reached through the table.
WAY_IN = {
    "run_input_checks_and_executor_driver_check": "processes.find_program",
    "launch_executor": "processes.start",
    "wait_for_the_end": "processes.poll",
}
STEP_TABLE_ONLY = [name for name in AFTER_THE_CLAIM if name not in WAY_IN]
NEEDS_A_LIVE_PROCESS = ("launch_executor", "wait_for_the_end")


def boom(state):
    raise RuntimeError("injected")


def replaced(name, function):
    return [(n, function if n == name else f) for n, f in run.STEPS]


def a_scene(name=None):
    """A child that ends at once, except where a case needs a live process: there it stays
    until the run ends it (the run asks it to end as soon as it sees what it is waiting for)."""
    if name in NEEDS_A_LIVE_PROCESS:
        return scenes.scene(exits_after=None)
    return scenes.scene()


# Three runs to fail in turn: a child that ends at once, one that runs until the time limit and
# obeys the ask, and one that ignores the ask and has to be killed.
RUNS = {
    "ends at once": lambda: scenes.scene(),
    "ends when asked, at the limit": lambda: scenes.scene(
        scenes.document(limit=1), exits_after=None
    ),
    "has to be killed, at the limit": lambda: scenes.scene(
        scenes.document(limit=1), exits_after=None, obeys=("kill",)
    ),
}

# A call that, failing, still leaves something the run promises not to. Each is a finding about
# the code, not about the simulated world; the test fails when one stops being true, so a mark
# cannot go stale. Key: (operation, "first" or "last" call of it in a run).
KNOWN_GAPS = {
    (
        "files.remove",
        "first",
    ): "the request record is in place but the temporary's name could not be removed: the claim says the id is unusable although it was claimed, and the temporary stays",
    (
        "files.remove",
        "last",
    ): "the outcome record is in place but the temporary's name could not be removed: the receipt is printed as not written although it was, and the temporary stays",
    (
        "processes.poll",
        "last",
    ): "the last look at the child, in the run's own finally, is outside every guard: an error there ends the run with no outcome record",
    (
        "signals.install",
        "first",
    ): "the handlers are installed before the guard: an error there ends the run before anything was claimed (nothing is left behind)",
}


def gap_for(operation, number, calls):
    """The known gap a failure of this call is, or None."""
    for place, hit in (("first", number == 1), ("last", number == calls)):
        if hit and (operation, place) in KNOWN_GAPS:
            return KNOWN_GAPS[(operation, place)]
    return None


def what_a_failed_call_left_behind(world, code):
    """What is wrong after a run in which one call failed, as a list; empty when nothing is."""
    names = world.names_in(scenes.RECORDS)
    wrong = []
    if any(".tmp-" in name for name in names):
        wrong.append("a temporary is left")
    outcomes = [n for n in names if n.endswith(".outcome.json")]
    if code == 0 and not outcomes:
        wrong.append("exit 0 and no outcome record")
    if outcomes and core.check_receipt(scenes.outcome(world)["receipt"]):
        wrong.append("an outcome record that fails the receipt check")
    if outcomes and "inj-1.request.json" not in names:
        wrong.append("an outcome record with no request record")
    if not world.every_child_has_ended():
        wrong.append("a child is still running")
    return wrong


def every_call():
    """(run, operation, number of the call, calls of it in the run) for each call each run makes."""
    found = []
    for run_name, make in RUNS.items():
        baseline = make()
        scenes.run_in(baseline)
        found += [
            (run_name, operation, number, calls)
            for operation, calls in sorted(baseline.counts.items())
            for number in range(1, calls + 1)
        ]
    return found


def run_with_a_failure(run_name, operation, number):
    """What is wrong after the run in which this call raised; a list, empty when nothing is."""
    world = RUNS[run_name]()
    world.will_raise(operation, RuntimeError("injected"), nth=number)
    try:
        code, _, _ = scenes.run_in(world)
    except RuntimeError:
        return ["the error escaped the run"]
    return what_a_failed_call_left_behind(world, code)


class EveryOperationFailingInTurn(unittest.TestCase):
    def test_a_failure_in_any_call_of_any_operation_leaves_a_whole_trace_and_no_child_running(self):
        for run_name, operation, number, calls in every_call():
            with self.subTest(run=run_name, operation=operation, call=number):
                wrong = run_with_a_failure(run_name, operation, number)
                gap = gap_for(operation, number, calls)
                if gap:
                    self.assertTrue(wrong, f"no longer a gap, remove the mark: {gap}")
                else:
                    self.assertEqual(wrong, [])

    def test_the_runs_make_enough_calls_for_the_sweep_to_mean_something(self):
        for run_name, make in RUNS.items():
            world = make()
            scenes.run_in(world)
            self.assertGreater(sum(world.counts.values()), 25, run_name)
            self.assertGreaterEqual(len(world.counts), 14, run_name)

    def test_every_known_gap_names_an_operation_that_a_run_calls(self):
        for operation, _ in KNOWN_GAPS:
            with self.subTest(operation):
                world = scenes.scene()
                scenes.run_in(world)
                self.assertIn(operation, world.counts)


class Injection(unittest.TestCase):
    def ending_of(self, world):
        ending = scenes.outcome(world)["receipt"]["the_ending"]
        return ending["ending"], ending["reason"], ending["failed_step"]

    def assert_outcome(self, world, expected):
        self.assertTrue(
            world.files.get(f"{scenes.RECORDS}/inj-1.outcome.json") is not None,
            f"no outcome record; files: {world.names_in(scenes.RECORDS)}",
        )
        self.assertEqual(self.ending_of(world), expected)
        self.assertEqual(core.check_receipt(scenes.outcome(world)["receipt"]), [])

    def test_a_step_after_the_claim_that_raises_still_gives_an_outcome_record_and_the_ending_the_table_says(
        self,
    ):
        for name in AFTER_THE_CLAIM:
            with self.subTest(name):
                world = a_scene(name)
                steps = None
                if name in WAY_IN:
                    world.will_raise(WAY_IN[name], RuntimeError("injected"))
                else:
                    steps = replaced(name, boom)
                code, lines, err = scenes.run_in(world, steps)
                self.assertEqual(code, 0, err)
                self.assert_outcome(world, IF_IT_RAISES[name])
                self.assertEqual(lines[-1], IF_IT_RAISES[name][0])

    def test_the_last_step_itself_raising_still_gives_an_outcome_record(self):
        world = scenes.scene()
        code, lines, err = scenes.run_in(world, replaced("write_outcome_record", boom))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.ending_of(world)[0], "ended_by_itself")
        self.assertEqual(lines[-1], "ended_by_itself")

    def test_a_signal_arriving_during_any_step_after_the_claim_still_gives_an_outcome_record(self):
        for name in AFTER_THE_CLAIM:
            with self.subTest(name):
                world = a_scene(name)
                steps = None
                if name in WAY_IN:
                    world.on_call(WAY_IN[name], lambda world=world: world.deliver("SIGINT"))
                else:
                    real = dict(run.STEPS)[name]

                    def signalled(state, real=real):
                        state["signal"] = state["signal"] or "SIGINT"
                        real(state)

                    steps = replaced(name, signalled)
                code, lines, err = scenes.run_in(world, steps)
                self.assertEqual(code, 0, err)
                self.assertEqual(self.ending_of(world), IF_SIGNALLED[name])

    def test_building_the_receipt_failing_writes_a_minimal_receipt_with_the_same_ending(self):
        world = scenes.scene()
        world.will_raise("identity.host_name", RuntimeError("injected"))
        code, lines, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        receipt = scenes.outcome(world)["receipt"]
        self.assertEqual(receipt["the_ending"]["ending"], "ended_by_itself")
        self.assertEqual(receipt["what_execution_saw"]["exit_code"], "cannot tell")
        self.assertEqual(lines[-1], "ended_by_itself")

    def test_writing_the_record_failing_prints_the_receipt_then_the_ending_and_exits_non_zero(self):
        world = scenes.scene()
        world.will_raise(
            "files.link", RuntimeError("injected"), nth=2
        )  # the outcome; the first was the claim
        code, lines, err = scenes.run_in(world)
        self.assertNotEqual(code, 0)
        self.assertEqual(lines[0], "inj-1")
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertEqual(
            json.loads("\n".join(lines[1:-1]))["the_ending"]["ending"],
            "ended_by_itself",
        )
        self.assertIn("not written", err)
        self.assertEqual(world.names_in(scenes.RECORDS), ["inj-1.request.json"])

    def test_an_error_in_the_claim_step_prints_the_refusal_then_could_not_start_and_writes_nothing(
        self,
    ):
        world = scenes.scene()
        world.will_raise("files.write_new", RuntimeError("injected"))
        code, lines, err = scenes.run_in(world)
        self.assertNotEqual(code, 0)
        self.assertEqual(lines, ["inj-1", CNS])
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertEqual(world.names_in(scenes.RECORDS), [])

    def test_a_document_that_cannot_be_built_into_a_request_record_spends_no_id_and_writes_nothing(
        self,
    ):
        # By value: JSON read from a file can be built into text on this Python, so the step
        # that claims the id is given a document with a loop in it (the real command's test of
        # this, test_command.py, skips where the Python can write the nesting it uses).
        real = dict(run.STEPS)["claim_request_id"]

        def with_a_loop(state):
            loop = []
            loop.append(loop)
            state["raw"] = dict(state["raw"], loop=loop)
            real(state)

        world = scenes.scene()
        code, lines, err = scenes.run_in(world, replaced("claim_request_id", with_a_loop))
        self.assertNotEqual(code, 0)
        self.assertEqual(lines, ["inj-1", CNS])
        self.assertIn("NOT spent", err)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertEqual(world.names_in(scenes.RECORDS), [])
        code, lines, err = scenes.run_in(world)  # the id is free: the same document now runs
        self.assertEqual((code, lines[-1]), (0, "ended_by_itself"))

    def test_no_message_says_the_run_ended_without_a_conclusion(self):
        with open(run.__file__) as f:
            self.assertNotIn("without a conclusion", f.read())


if __name__ == "__main__":
    unittest.main()
