"""By value: the waiting logic, driven by a stand-in clock and stand-in processes. No real time passes.

Covers which cause ends the wait, what is ended and in what order (ask, wait the grace, kill),
what facts each outcome gives, and that a later signal changes nothing. The one test that waits
for real is in test_grace.py; signals sent to the real command are in test_command.py.
"""

import datetime
import signal
import unittest

from shuttle import core, run

POLL = run._POLL_SECONDS
GRACE = 3  # a stand-in clock makes the real default affordable here


class StandInClock:
    """Time that moves only when something sleeps. `at` is a list of (time, function) run once when reached."""

    def __init__(self, at=()):
        self.t = 0.0
        self.pending = sorted(at, key=lambda pair: pair[0])

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        while self.pending and self.pending[0][0] <= self.t:
            self.pending.pop(0)[1]()


class StandInProcess:
    """A child that exits by itself at `exits_at`, and obeys only the requests named in `obeys`."""

    def __init__(self, clock, exits_at=None, obeys=("terminate", "kill")):
        self.clock, self.exits_at, self.obeys = clock, exits_at, obeys
        self.returncode = None
        self.calls = []

    def poll(self):
        if self.returncode is None and self.exits_at is not None and self.clock.t >= self.exits_at:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.calls.append(("terminate", self.clock.t))
        if "terminate" in self.obeys:
            self.returncode = -signal.SIGTERM

    def kill(self):
        self.calls.append(("kill", self.clock.t))
        if "kill" in self.obeys:
            self.returncode = -signal.SIGKILL


def signal_from(clock, at):
    return lambda: "SIGINT" if at is not None and clock.t >= at else None


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
                clock = StandInClock()
                process = StandInProcess(clock, exits_at)
                cause = run.wait_for_the_cause(process, limit, signal_from(clock, signal_at), clock)
                self.assertEqual(cause, expected)
                self.assertLessEqual(clock.t, limit + POLL)
                self.assertEqual(
                    process.calls, []
                )  # the wait only watches; ending is a separate decision


class WhatIsEndedAndInWhatOrder(unittest.TestCase):
    def test_a_child_that_obeys_the_ask_is_asked_once_and_not_killed(self):
        clock = StandInClock()
        process = StandInProcess(clock, obeys=("terminate",))
        self.assertEqual(run.end_child(process, GRACE, clock), "ended")
        self.assertEqual([name for name, _ in process.calls], ["terminate"])

    def test_a_child_that_ignores_the_ask_is_killed_after_the_whole_grace(self):
        clock = StandInClock()
        process = StandInProcess(clock, obeys=("kill",))
        self.assertEqual(run.end_child(process, GRACE, clock), "ended")
        self.assertEqual([name for name, _ in process.calls], ["terminate", "kill"])
        asked, killed = process.calls[0][1], process.calls[1][1]
        self.assertGreaterEqual(killed - asked, GRACE)
        self.assertLessEqual(killed - asked, GRACE + POLL)

    def test_a_child_that_survives_the_kill_is_not_confirmed_after_a_second_grace(self):
        clock = StandInClock()
        process = StandInProcess(clock, obeys=())
        self.assertEqual(run.end_child(process, GRACE, clock), "not_confirmed")
        self.assertEqual([name for name, _ in process.calls], ["terminate", "kill"])
        self.assertGreaterEqual(clock.t, 2 * GRACE)

    def test_a_child_that_has_already_exited_is_not_asked_anything(self):
        clock = StandInClock()
        process = StandInProcess(clock, exits_at=0)
        self.assertEqual(run.end_child(process, GRACE, clock), "ended")
        self.assertEqual(process.calls, [])

    def test_the_defaults_are_the_documented_values(self):
        self.assertEqual(run.END_GRACE_SECONDS, 3)
        self.assertEqual(run.end_child.__defaults__, (3, run.REAL_CLOCK))
        self.assertEqual(run.run.__defaults__[-2:], (3, run.REAL_CLOCK))


class TheWaitStepGivesTheseFacts(unittest.TestCase):
    def step(self, limit, signal_at=None, exits_at=None, obeys=("terminate", "kill")):
        """Run the wait step on stand-ins. `signal_at` is when a signal arrives, on the stand-in clock."""
        state = {"signal": None, "facts": {}, "grace": GRACE, "raw": {"time_limit_seconds": limit}}
        arrives = (
            [(signal_at, lambda: state.update(signal="SIGINT"))] if signal_at is not None else []
        )
        clock = StandInClock(arrives)
        process = StandInProcess(clock, exits_at, obeys)
        state.update(
            clock=clock,
            stand_ins={"boundary": {"process": process}},
            clock_start=datetime.datetime.now(datetime.timezone.utc),
        )
        run.step_wait_for_the_end(state)
        return state["facts"], process

    def test_a_child_that_exits_by_itself_gives_exited_and_is_never_asked(self):
        facts, process = self.step(limit=10, exits_at=1)
        self.assertEqual((facts["wait"], facts["exit_code"], process.calls), ("exited", 0, []))
        self.assertNotIn("stop", facts)

    def test_the_limit_gives_time_limit_and_the_child_is_ended(self):
        facts, process = self.step(limit=2)
        self.assertEqual(facts["wait"], "time_limit")
        self.assertEqual([name for name, _ in process.calls], ["terminate"])
        self.assertNotIn("stop", facts)

    def test_a_signal_gives_signal(self):
        facts, _ = self.step(limit=10, signal_at=1)
        self.assertEqual(facts["wait"], "signal")

    def test_a_signal_during_the_grace_after_the_limit_changes_nothing_and_the_child_is_killed(
        self,
    ):
        facts, process = self.step(limit=2, signal_at=2 + GRACE / 2, obeys=("kill",))
        self.assertEqual(facts["wait"], "time_limit")
        self.assertNotIn("stop", facts)
        self.assertEqual([name for name, _ in process.calls], ["terminate", "kill"])
        self.assertEqual(
            (facts["exit_code"], facts["child_signal"]), core.exit_facts(-signal.SIGKILL)
        )

    def test_a_limit_passing_in_the_grace_after_a_signal_changes_nothing(self):
        facts, process = self.step(limit=2, signal_at=1, obeys=("kill",))
        self.assertEqual(facts["wait"], "signal")
        self.assertEqual([name for name, _ in process.calls], ["terminate", "kill"])

    def test_a_child_that_survives_the_kill_gives_stop_not_confirmed(self):
        facts, _ = self.step(limit=2, obeys=())
        self.assertEqual((facts["wait"], facts["stop"]), ("time_limit", "not_confirmed"))


class TheHandlersOnlyRecordTheFirstSignal(unittest.TestCase):
    def test_each_signal_is_recorded_by_name_and_a_later_one_changes_nothing(self):
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=number.name):
                state = {"signal": None}
                previous = run._install_handlers(state)
                self.addCleanup(
                    lambda previous=previous: [signal.signal(n, h) for n, h in previous.items()]
                )
                signal.raise_signal(number)
                other = signal.SIGHUP if number != signal.SIGHUP else signal.SIGINT
                signal.raise_signal(other)
                self.assertEqual(state["signal"], number.name)


if __name__ == "__main__":
    unittest.main()
