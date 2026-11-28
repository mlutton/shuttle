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

from shuttle.core import boundary, decisions, fixed
from shuttle.shell import run, stop_and_confirm_empty, wait_for_the_end

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
simulated = importlib.import_module("rehearsal.simulated_world")

REACH: boundary.Reach = {
    "place": "/place",
    "area": "/area",
    "home": "/area/home",
    "tmp": "/area/tmp",
    "references": [],
    "visible": [],
    "git_folders": [],
    "place_writable": True,
    "resolver": None,
    "records": "/rec",
}

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
                self.assertEqual(boundary.scope_is_empty(properties), expected)


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


STARTED = '{"child-pid": 2, "namespace": 1}\n'
STARTED_AND_ENDED = STARTED + '{"exit-code": 0}\n'


class WhetherTheExecutorEverStarted(unittest.TestCase):
    """bubblewrap says "child-pid" once the box is made and the executor forked, before the program
    is executed. A run that ended with no such line never started the executor, whatever the exit
    code of what was launched."""

    def test_the_report_rows(self):
        for report, expected in (
            (STARTED, True),
            (STARTED_AND_ENDED, True),
            ('{"other": 1}\n' + STARTED, True),  # other objects and members are ignored
            ("", False),
            ('{"exit-code": 1}\n', False),
            ("bwrap: no permission\n", False),  # text that is not a JSON object
            ('["child-pid"]\n', False),
            ('{"child-pid": 0}\n', False),
            ('{"child-pid": true}\n', False),
            ('{"child-pid": "7"}\n', False),
            ("{" * 100_000, False),
        ):
            with self.subTest(report=report[:40]):
                self.assertEqual(boundary.executor_started(report), expected)

    def test_a_launch_failed_when_the_scope_ended_with_no_start_reported(self):
        for cause, report, expected in (
            ("exited", "", True),
            ("exited", '{"exit-code": 1}\n', True),
            ("exited", STARTED_AND_ENDED, False),
            ("time_limit", "", False),  # the timer may end it before it reports
            ("signal", "", False),  # a signal is a stop, not a failed launch
            ("cannot_tell", "", False),  # never a guess
            ("stop_record", "", False),
        ):
            with self.subTest(cause=cause, report=report):
                self.assertEqual(boundary.launch_failed(cause, report), expected)


class WhetherTheProgramWasEverStarted(unittest.TestCase):
    """bubblewrap writes the executor's end only for a program it executed, whatever the program's
    own exit code; it ends with status 1 itself, with no such line, when it could not execute the
    program or failed making the box after the fork."""

    def test_the_end_of_the_executor_in_the_report_rows(self):
        for report, expected in (
            (STARTED_AND_ENDED, True),
            (STARTED + '{"exit-code": 1}\n', True),
            (STARTED + '{"exit-code": 126}\n', True),
            (STARTED + '{"exit-code": 127}\n', True),
            (STARTED + '{"exit-code": 137}\n', True),
            (STARTED, False),
            ("", False),
            (STARTED + '{"exit-code": "1"}\n', False),
            (STARTED + '{"exit-code": true}\n', False),
            (STARTED + '{"exit-code": null}\n', False),
            (STARTED + "exit-code 1\n", False),
            (STARTED + '["exit-code", 1]\n', False),
        ):
            with self.subTest(report=report[-30:]):
                self.assertEqual(boundary.executor_ended(report), expected)

    def test_the_program_did_not_start_rows(self):
        for label, given, expected in (
            ("forked, no end reported, bubblewrap failed", ("exited", STARTED, 1), True),
            (
                "the executor's own exit 1 is reported as its end",
                ("exited", STARTED_AND_ENDED, 1),
                False,
            ),
            ("exit 126 reported", ("exited", STARTED + '{"exit-code": 126}\n', 1), False),
            ("exit 127 reported", ("exited", STARTED + '{"exit-code": 127}\n', 1), False),
            (
                "exit 127 reported, bubblewrap exit 127",
                ("exited", STARTED + '{"exit-code": 127}\n', 127),
                False,
            ),
            ("never forked is a failed launch, not this", ("exited", "", 1), False),
            ("bubblewrap ended by a signal says nothing", ("exited", STARTED, -9), False),
            ("bubblewrap ended with another status", ("exited", STARTED, 2), False),
            ("bubblewrap ended with status 0 and no end", ("exited", STARTED, 0), False),
            ("status not read", ("exited", STARTED, None), False),
            ("time limit", ("time_limit", STARTED, 1), False),
            ("signal", ("signal", STARTED, 1), False),
            ("stop record", ("stop_record", STARTED, 1), False),
            ("cause not told", ("cannot_tell", STARTED, 1), False),
        ):
            with self.subTest(label):
                self.assertEqual(boundary.program_not_started(*given), expected)

    def test_the_line_names_the_program_as_data_and_says_what_to_look_at(self):
        line = boundary.program_not_started_line("a\nb 'c")
        self.assertNotIn("\n", line)
        self.assertIn(repr("a\nb 'c"), line)
        self.assertIn("reach.visible", line)
        self.assertIn("interpreter", line)
        self.assertNotIn("program None", boundary.program_not_started_line(None))
        # Two causes give the same report, so the line claims neither: not that the box was made,
        # not that the program is at fault.
        self.assertNotIn("was made", line)
        self.assertIn("could not be made", line)
        self.assertIn("the place", line)

    def test_a_program_that_could_not_be_executed_ends_as_a_launch_that_did_not_start_it(self):
        world = simulated.SimulatedWorld()
        state = a_state(world, cannot_exec=True)
        state["program"] = "the-tool"
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        facts = state["facts"]
        self.assertEqual(
            (facts["launch"], facts["stop"], facts["exit_code"], facts["child_signal"]),
            ("program_not_started", "confirmed", None, None),
        )
        self.assertEqual(
            decisions.decide_ending(facts),
            {"ending": "could_not_start", "reason": "program_not_started", "failed_step": "launch"},
        )
        self.assertIn(
            "'the-tool'", decisions.reason_text(decisions.decide_ending(facts), state["problems"])
        )

    def test_a_program_that_started_and_exited_with_any_code_is_its_own_exit(self):
        for code in (0, 1, 2, 126, 127, 255):
            with self.subTest(code=code):
                world = simulated.SimulatedWorld()
                state = a_state(world, exit_code=code)
                wait_for_the_end.step(state)
                stop_and_confirm_empty.step(state)
                facts = state["facts"]
                self.assertEqual(facts["exit_code"], code)
                self.assertNotIn(facts.get("launch"), ("failed", "program_not_started"))
                ran = {**facts, "launch": "ok", "closing_freeze": "ok", "delivery": "ok"}
                self.assertEqual(decisions.decide_ending(ran)["ending"], "ended_by_itself")


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

    def test_the_launch_command_carries_the_limit_the_grace_and_the_reach(self):
        argv = boundary.launch_argv("shuttle-run-r-1", 2.5, ["tool", "--", "x"], ["HOME"], REACH, 7)
        self.assertIn("--unit=shuttle-run-r-1", argv)
        self.assertIn("RuntimeMaxSec=2500000us", argv)
        self.assertIn("TimeoutStopSec=3s", argv)
        self.assertEqual(
            argv[argv.index("--ro-bind") : argv.index("--ro-bind") + 3],
            ["--ro-bind", "/usr", "/usr"],
        )
        self.assertEqual(argv[-3:], ["tool", "--", "x"])  # the executor's own arguments untouched
        self.assertIn("--die-with-parent", argv)
        self.assertIn("--unshare-pid", argv)
        at = argv.index("--json-status-fd")  # the report of the start goes where it was told to
        self.assertEqual(argv[at + 1], "7")
        self.assertLess(at, len(argv) - 3)  # before the executor, which is last

    def test_the_variables_that_reach_systemd_are_taken_from_the_executor_unless_named(self):
        for names, unset in (
            ([], ["XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"]),
            (["XDG_RUNTIME_DIR"], ["DBUS_SESSION_BUS_ADDRESS"]),
        ):
            with self.subTest(names=names):
                argv = boundary.launch_argv("n", 1, ["tool"], names, REACH, 3)
                found = [argv[i + 1] for i, part in enumerate(argv) if part == "--unsetenv"]
                self.assertEqual(found, unset)


def a_state(world, **program):
    world.program("tool", **program)
    processes = world.operations.processes
    process = processes.start(
        ["systemd-run", "--unit=shuttle-run-w", "bwrap", "--", "tool"], {}, processes.open_report()
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


class AGatesAnswerFromHowItsScopeEnded(unittest.TestCase):
    def test_rows(self):
        started = boundary.GATE_STARTED + "\n"
        ended, timed_out, cannot_tell = boundary.ENDED, boundary.TIMED_OUT, boundary.CANNOT_TELL
        for label, given, answer in (
            ("exit 0 is yes", (started, ended, 0), "yes"),
            ("exit 1 is no", (started, ended, 1), "no"),
            ("another exit code is failed", (started, ended, 2), "failed"),
            ("a command that could not be run is failed", (started, ended, 127), "failed"),
            ("killed by a signal is failed", (started, ended, -9), "failed"),
            ("no exit status is failed", (started, ended, None), "failed"),
            ("the limit passed is failed even with exit 0", (started, timed_out, 0), "failed"),
            ("the limit passed is failed even with exit 1", (started, timed_out, 1), "failed"),
            ("a scope that cannot be read is failed", (started, cannot_tell, 0), "failed"),
            ("no start reported is failed, exit 1 or not", ("", ended, 1), "failed"),
            ("a start nobody reported is not a yes", ("", ended, 0), "failed"),
            ("a report that is not the start is not a start", ("nope\n", ended, 0), "failed"),
        ):
            with self.subTest(label):
                self.assertEqual(boundary.gate_answer(*given), answer)

    def test_a_gate_runs_in_its_own_scope_with_its_limit_and_without_the_variables_for_systemd(
        self,
    ):
        argv = boundary.gate_argv("shuttle-gate-r-0", 2.5, ["check", "--fast"], 7)
        self.assertEqual(argv[:4], ["systemd-run", "--user", "--scope", "--quiet"])
        self.assertIn("--unit=shuttle-gate-r-0", argv)
        self.assertIn("RuntimeMaxSec=2500000us", argv)
        self.assertIn("TimeoutStopSec=3s", argv)
        self.assertNotIn("bwrap", argv)
        script = argv[argv.index("-c") + 1]
        for variable in boundary.BUS_VARIABLES:
            self.assertIn(variable, script.split("unset")[1].split(";")[0])
        self.assertEqual(argv[argv.index("-c") + 2 :], ["sh", "7", "check", "--fast"])

    def test_a_gate_scope_is_named_from_the_request_the_run_and_its_place(self):
        self.assertEqual(boundary.gate_scope_name("r-1", "abc", 2), "shuttle-gate-r-1-abc-2")


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
        # What ended is the scope's process; the executor's own signal is not told.
        self.assertEqual(state["facts"]["child_signal"], fixed.CANNOT_TELL)
        self.assertEqual(len(world.calls("boundary.forget")), 1)  # the failed unit is cleared

    def test_an_executor_that_never_started_gives_a_failed_launch_and_no_exit_code(self):
        world = simulated.SimulatedWorld()
        state = a_state(world, exit_code=1, fails_to_start=True)
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        facts = state["facts"]
        self.assertEqual(
            (facts["launch"], facts["stop"], facts["exit_code"], facts["child_signal"]),
            ("failed", "confirmed", None, None),
        )
        self.assertEqual(
            decisions.decide_ending(facts),
            {"ending": "could_not_start", "reason": "launch_failed", "failed_step": "launch"},
        )

    def test_a_scope_that_timed_out_before_the_start_was_reported_is_still_a_time_limit(self):
        world = simulated.SimulatedWorld()
        state = a_state(world, times_out=True, fails_to_start=True)
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        self.assertNotEqual(state["facts"].get("launch"), "failed")
        self.assertEqual(state["facts"]["wait"], "time_limit")

    def test_an_executor_that_started_gives_a_signal_that_cannot_be_told_and_its_exit_code(self):
        world = simulated.SimulatedWorld()
        state = a_state(world, exit_code=137)
        wait_for_the_end.step(state)
        stop_and_confirm_empty.step(state)
        facts = state["facts"]
        self.assertEqual((facts["exit_code"], facts["child_signal"]), (137, fixed.CANNOT_TELL))

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
