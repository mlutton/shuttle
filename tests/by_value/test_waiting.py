"""By value, with no clock: why the wait ended and why the boundary ended, and what each gives.

The boundary owns the time limit, so nothing here keeps time. Covered: which of an exit or a
signal ends the wait (a stop record joins them when the stop form is built), the map from why the
boundary ended to a cause and then to an ending (including "cannot tell"), the limit the boundary's
timer can take, and the facts the wait and stop steps leave on the simulated world. The one real
wait is tests/boundary/test_end_to_end.py.
"""

import importlib
import os
import sys
import unittest

from shuttle.core import boundary, decisions
from shuttle.shell import run, stop_and_confirm_empty, wait_for_the_end

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
simulated = importlib.import_module("rehearsal.simulated_world")

TIMED_OUT = {"LoadState": "loaded", "ActiveState": "failed", "Result": "timeout"}
GONE = {"LoadState": "not-found", "ActiveState": "inactive", "Result": "success"}
STILL_THERE = {"LoadState": "loaded", "ActiveState": "active", "Result": "success"}


class WhichCauseEndsTheWait(unittest.TestCase):
    def test_rows(self):
        for exited, signal_name, expected in (
            (True, None, "exited"),
            (False, "SIGINT", "signal"),
            (True, "SIGINT", "exited"),
            (False, None, None),
        ):
            with self.subTest(exited=exited, signal=signal_name):
                self.assertEqual(boundary.wait_cause(exited, signal_name), expected)


class WhyTheBoundaryEnded(unittest.TestCase):
    def test_rows(self):
        for properties, expected in (
            (TIMED_OUT, "timed_out"),
            (GONE, "ended"),
            ({"LoadState": "loaded", "ActiveState": "inactive", "Result": "success"}, "ended"),
            ({"LoadState": "loaded", "ActiveState": "failed", "Result": "oom-kill"}, "ended"),
            ({"LoadState": "loaded", "ActiveState": "failed", "Result": "signal"}, "ended"),
            (STILL_THERE, "cannot_tell"),  # not ended
            (
                {"LoadState": "loaded", "ActiveState": "deactivating", "Result": "timeout"},
                "cannot_tell",
            ),
            (
                {"LoadState": "loaded", "ActiveState": "failed", "Result": "resources"},
                "cannot_tell",
            ),
            ({"ActiveState": "inactive"}, "cannot_tell"),  # no Result
            ({}, "cannot_tell"),
            (None, "cannot_tell"),  # could not be read
        ):
            with self.subTest(properties=properties):
                self.assertEqual(boundary.why_ended(properties), expected)

    def test_only_a_settled_scope_is_empty(self):
        for properties, expected in (
            (TIMED_OUT, True),
            (GONE, True),
            (STILL_THERE, False),
            ({"ActiveState": "deactivating"}, False),
            ({}, False),
            (None, False),
        ):
            with self.subTest(properties=properties):
                self.assertEqual(boundary.is_empty(properties), expected)


class FromTheCauseAndTheBoundaryToAnEnding(unittest.TestCase):
    def ending_for(self, wait, why):
        facts = {
            "id_claim": "ok",
            "launch": "ok",
            "stop": "confirmed",
            "closing_freeze": "ok",
            "delivery": "ok",
            "wait": boundary.cause_of_end(wait, why),
        }
        decision = decisions.decide_ending(facts)  # type: ignore[arg-type]
        return decision["ending"], decision["reason"], decision["failed_step"]

    def test_rows(self):
        for wait, why, expected in (
            ("exited", "timed_out", ("time_limit", "time_limit", "none")),
            ("exited", "ended", ("ended_by_itself", "none", "none")),
            ("exited", "cannot_tell", ("execution_failed", "execution_error", "cannot tell")),
            ("signal", "ended", ("stopped_from_outside", "signal", "none")),
            ("signal", "timed_out", ("stopped_from_outside", "signal", "none")),
            ("signal", "cannot_tell", ("stopped_from_outside", "signal", "none")),
            ("stop_record", "ended", ("stopped_from_outside", "stop_record", "none")),
            ("error", "ended", ("execution_failed", "stop_not_confirmed", "stop_not_confirmed")),
            (None, "ended", ("execution_failed", "execution_error", "cannot tell")),
        ):
            with self.subTest(wait=wait, why=why):
                self.assertEqual(self.ending_for(wait, why), expected)


class TheLimitTheTimerCanTake(unittest.TestCase):
    def test_rows(self):
        for value, usable in (
            (1, True),
            (0.5, True),
            (1e-6, True),
            (10**9, True),
            (9e-7, False),  # rounds to nothing: the timer reads zero as "no maximum"
            (0, False),
            (-1, False),
            (10**9 + 1, False),
            (float("inf"), False),
            (float("nan"), False),
            (True, False),
            ("5", False),
            (None, False),
            (10**400, False),
        ):
            with self.subTest(value=value):
                self.assertEqual(boundary.usable_time_limit(value), usable)

    def test_the_limit_goes_to_the_timer_in_whole_microseconds_and_never_as_zero(self):
        for seconds, expected in ((1, 1_000_000), (0.5, 500_000), (1e-6, 1), (10**9, 10**15)):
            with self.subTest(seconds=seconds):
                self.assertEqual(boundary.limit_microseconds(seconds), expected)

    def test_the_launch_command_carries_the_limit_the_grace_and_the_protected_paths(self):
        argv = boundary.launch_argv("shuttle-run-r-1", 2.5, ["tool", "--", "x"], ["HOME"], ["/rec"])
        self.assertIn("--unit=shuttle-run-r-1", argv)
        self.assertIn("RuntimeMaxSec=2500000us", argv)
        self.assertIn("TimeoutStopSec=3s", argv)
        self.assertEqual(
            argv[argv.index("--ro-bind") : argv.index("--ro-bind") + 3],
            ["--ro-bind", "/rec", "/rec"],
        )
        self.assertEqual(argv[-3:], ["tool", "--", "x"])  # the executor's own arguments untouched
        self.assertIn("--die-with-parent", argv)
        self.assertIn("--unshare-pid", argv)

    def test_the_variables_that_reach_systemd_are_taken_from_the_executor_unless_named(self):
        for names, unset in (
            ([], ["XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"]),
            (["XDG_RUNTIME_DIR"], ["DBUS_SESSION_BUS_ADDRESS"]),
        ):
            with self.subTest(names=names):
                argv = boundary.launch_argv("n", 1, ["tool"], names, [])
                found = [argv[i + 1] for i, part in enumerate(argv) if part == "--unsetenv"]
                self.assertEqual(found, unset)


def a_state(world, **program):
    world.program("tool", **program)
    process = world.operations.processes.start(
        ["systemd-run", "--unit=shuttle-run-w", "bwrap", "--", "tool"], {}
    )
    return {
        "world": world.operations,
        "facts": {},
        "problems": {},
        "stand_ins": {},
        "signal": None,
        "clock_start": 0.0,
        "boundary_name": "shuttle-run-w",
        "boundary_process": process,
    }


class TheWaitAndStopStepsGiveTheseFacts(unittest.TestCase):
    def test_an_executor_that_exited_gives_exited_and_a_stop_that_empties_the_boundary(self):
        world = simulated.SimulatedWorld()
        state = a_state(world)
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        self.assertEqual((state["facts"]["wait"], state["facts"]["stop"]), ("exited", "confirmed"))
        self.assertEqual(state["facts"]["exit_code"], 0)
        self.assertEqual(world.calls("boundary.stop")[0][0], ("shuttle-run-w.scope",))

    def test_a_scope_that_timed_out_gives_time_limit(self):
        world = simulated.SimulatedWorld()
        state = a_state(world, times_out=True)
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        self.assertEqual(
            (state["facts"]["wait"], state["facts"]["stop"]), ("time_limit", "confirmed")
        )
        self.assertEqual(state["facts"]["child_signal"], "SIGTERM")
        self.assertEqual(len(world.calls("boundary.forget")), 1)  # the failed unit is cleared

    def test_a_signal_gives_signal_and_the_boundary_is_stopped_by_name(self):
        world = simulated.SimulatedWorld()
        state = a_state(world, hangs=True)
        world.on_call("processes.poll", lambda: state.update(signal="SIGINT"), nth=2)
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        self.assertEqual((state["facts"]["wait"], state["facts"]["stop"]), ("signal", "confirmed"))
        self.assertEqual(len(world.calls("boundary.stop")), 1)

    def test_a_boundary_that_is_not_seen_empty_gives_stop_not_confirmed(self):
        world = simulated.SimulatedWorld()
        state = a_state(world, hangs=True, survives_stop=True)
        world.on_call("processes.poll", lambda: state.update(signal="SIGINT"), nth=2)
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        self.assertEqual(state["facts"]["stop"], "not_confirmed")
        self.assertIs(state["stand_ins"]["stop_confirmation"]["everything_stopped"], False)

    def test_a_scope_that_cannot_be_read_gives_stop_not_confirmed_and_a_cause_that_cannot_be_told(
        self,
    ):
        world = simulated.SimulatedWorld()
        state = a_state(world)
        world.will_raise("boundary.show", OSError("no bus"))
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        self.assertEqual(state["facts"]["stop"], "not_confirmed")
        self.assertEqual(state["facts"]["wait"], "cannot_tell")


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
                self.assertEqual(decisions.exit_facts(*given), expected)


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
