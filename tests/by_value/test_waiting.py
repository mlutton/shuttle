"""By value: the waiting logic, on the simulated world. No real time passes, no real process runs.

Covers which cause ends the wait, what is ended and in what order (ask, wait the grace, kill),
what facts each outcome gives, and that a later signal changes nothing. The one real wait is in
tests/command/test_time_limit.py; signals sent to the real command are in test_command.py.
"""

import importlib
import inspect
import os
import sys
import unittest

from shuttle.core import decisions as core
from shuttle.shell import run

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
simulated = importlib.import_module("rehearsal.simulated_world")

POLL = run._POLL_SECONDS
GRACE = run.END_GRACE_SECONDS


def a_child(world, exits_at=None, obeys=("ask_to_end", "kill")):
    """A running child on the world: it exits by itself `exits_at` seconds after it starts."""
    world.program("tool", exits_after=exits_at, obeys=obeys)
    return world.operations.processes.start(["tool"], {})


def signal_from(world, at):
    return lambda: "SIGINT" if at is not None and world.t >= at else None


def requests(world):
    """The asks and kills the world was given, in order, as (name, time on its clock)."""
    return [
        (op.split(".")[1], t)
        for op, _, t in world.log
        if op in ("processes.ask_to_end", "processes.kill")
    ]


class WhichCauseEndsTheWait(unittest.TestCase):
    def test_the_first_cause_seen_ends_the_wait(self):
        # (exits_at, signal_at, limit, expected cause)
        for exits_at, signal_at, limit, expected in (
            (1, None, 10, "exited"),
            (None, 1, 10, "signal"),
            (None, None, 2, "time_limit"),
            (1, 5, 10, "exited"),
            (5, 1, 10, "signal"),
            (None, 5, 2, "time_limit"),
            (None, 2, 5, "signal"),
        ):
            with self.subTest(exits_at=exits_at, signal_at=signal_at, limit=limit):
                world = simulated.SimulatedWorld()
                process = a_child(world, exits_at)
                cause = run.wait_for_the_cause(
                    world.operations, process, limit, signal_from(world, signal_at)
                )
                self.assertEqual(cause, expected)
                self.assertLessEqual(world.t, limit + POLL)
                self.assertEqual(requests(world), [])  # the wait only watches; ending is separate


class WhatIsEndedAndInWhatOrder(unittest.TestCase):
    def end(self, **child):
        world = simulated.SimulatedWorld()
        process = a_child(world, **child)
        return world, run.end_child(world.operations, process)

    def test_a_child_that_obeys_the_ask_is_asked_once_and_not_killed(self):
        world, result = self.end(obeys=("ask_to_end",))
        self.assertEqual(result, "ended")
        self.assertEqual([name for name, _ in requests(world)], ["ask_to_end"])

    def test_a_child_that_ignores_the_ask_is_killed_after_the_whole_grace(self):
        world, result = self.end(obeys=("kill",))
        self.assertEqual(result, "ended")
        (first, asked), (name, killed) = requests(world)
        self.assertEqual(first, "ask_to_end")
        self.assertEqual(name, "kill")
        self.assertGreaterEqual(killed - asked, GRACE)
        self.assertLessEqual(killed - asked, GRACE + POLL)

    def test_a_child_that_survives_the_kill_is_not_confirmed_after_a_second_grace(self):
        world, result = self.end(obeys=())
        self.assertEqual(result, "not_confirmed")
        self.assertEqual([name for name, _ in requests(world)], ["ask_to_end", "kill"])
        self.assertGreaterEqual(world.t, 2 * GRACE)

    def test_a_child_that_has_already_exited_is_not_asked_anything(self):
        world, result = self.end(exits_at=0)
        self.assertEqual(result, "ended")
        self.assertEqual(requests(world), [])

    def test_a_request_that_cannot_be_sent_is_not_an_error_and_the_child_is_still_ended(self):
        world = simulated.SimulatedWorld()
        process = a_child(world, obeys=("kill",))
        world.will_raise("processes.ask_to_end", ProcessLookupError("gone"))
        self.assertEqual(run.end_child(world.operations, process), "ended")

    def test_the_grace_is_a_fixed_policy_and_the_run_takes_no_seam_for_it(self):
        self.assertEqual(run.END_GRACE_SECONDS, 3)
        self.assertEqual(
            list(inspect.signature(run.run).parameters), ["document_path", "out", "err", "world"]
        )
        self.assertEqual(list(inspect.signature(run.end_child).parameters), ["world", "process"])
        self.assertNotIn("clock", inspect.signature(run.wait_for_the_cause).parameters)


class TheWaitStepGivesTheseFacts(unittest.TestCase):
    def step(self, limit, signal_at=None, exits_at=None, obeys=("ask_to_end", "kill")):
        """Run the wait step on the world. `signal_at` is when a signal arrives, on its clock."""
        world = simulated.SimulatedWorld()
        process = a_child(world, exits_at, obeys)
        state = {
            "signal": None,
            "facts": {},
            "raw": {"time_limit_seconds": limit},
            "world": world.operations,
            "stand_ins": {"boundary": {"process": process}},
            "clock_start": world.operations.clock.now(),
        }
        if signal_at is not None:
            world.at(signal_at, lambda: state.update(signal="SIGINT"))
        run.step_wait_for_the_end(state)
        return state["facts"], world

    def test_a_child_that_exits_by_itself_gives_exited_and_is_never_asked(self):
        facts, world = self.step(limit=10, exits_at=1)
        self.assertEqual((facts["wait"], facts["exit_code"]), ("exited", 0))
        self.assertEqual(requests(world), [])
        self.assertNotIn("stop", facts)

    def test_the_limit_gives_time_limit_and_the_child_is_ended(self):
        facts, world = self.step(limit=2)
        self.assertEqual(facts["wait"], "time_limit")
        self.assertEqual([name for name, _ in requests(world)], ["ask_to_end"])
        self.assertNotIn("stop", facts)

    def test_a_signal_gives_signal(self):
        facts, _ = self.step(limit=10, signal_at=1)
        self.assertEqual(facts["wait"], "signal")

    def test_a_signal_during_the_grace_after_the_limit_changes_nothing_and_the_child_is_killed(
        self,
    ):
        facts, world = self.step(limit=2, signal_at=2 + GRACE / 2, obeys=("kill",))
        self.assertEqual(facts["wait"], "time_limit")
        self.assertNotIn("stop", facts)
        self.assertEqual([name for name, _ in requests(world)], ["ask_to_end", "kill"])
        self.assertEqual((facts["exit_code"], facts["child_signal"]), (None, "SIGKILL"))

    def test_a_limit_passing_in_the_grace_after_a_signal_changes_nothing(self):
        facts, world = self.step(limit=2, signal_at=1, obeys=("kill",))
        self.assertEqual(facts["wait"], "signal")
        self.assertEqual([name for name, _ in requests(world)], ["ask_to_end", "kill"])

    def test_a_child_that_survives_the_kill_gives_stop_not_confirmed(self):
        facts, _ = self.step(limit=2, obeys=())
        self.assertEqual((facts["wait"], facts["stop"]), ("time_limit", "not_confirmed"))
        self.assertEqual((facts["exit_code"], facts["child_signal"]), (None, None))

    def test_the_duration_is_the_time_on_the_worlds_clock_from_the_start_to_the_end(self):
        world = simulated.SimulatedWorld()
        process = a_child(world, exits_at=1)
        state = {
            "signal": None,
            "facts": {},
            "raw": {"time_limit_seconds": 10},
            "world": world.operations,
            "stand_ins": {"boundary": {"process": process}},
            "clock_start": world.operations.clock.now(),
        }
        run.step_wait_for_the_end(state)
        self.assertAlmostEqual(state["executor_duration"], 1.0, delta=POLL * 2)
        self.assertEqual(state["ended_at"], world.operations.clock.timestamp())


class TheExitFacts(unittest.TestCase):
    def test_rows(self):
        for given, expected in (
            ((None, None), (None, None)),
            ((0, None), (0, None)),
            ((3, None), (3, None)),
            ((-9, "SIGKILL"), (None, "SIGKILL")),
            ((-15, "SIGTERM"), (None, "SIGTERM")),
            ((-99, None), (None, "signal 99")),
        ):
            with self.subTest(given):
                self.assertEqual(core.exit_facts(*given), expected)


class TheHandlersOnlyRecordTheFirstSignal(unittest.TestCase):
    def test_each_signal_is_recorded_by_name_and_a_later_one_changes_nothing(self):
        for first in ("SIGINT", "SIGTERM", "SIGHUP"):
            with self.subTest(signal=first):
                world = simulated.SimulatedWorld()
                state = {"signal": None, "world": world.operations}
                restore = run._install_handlers(state)
                world.deliver(first)
                world.deliver("SIGHUP" if first != "SIGHUP" else "SIGINT")
                self.assertEqual(state["signal"], first)
                restore()
                world.deliver("SIGTERM")  # nobody is listening now
                self.assertEqual(state["signal"], first)


if __name__ == "__main__":
    unittest.main()
