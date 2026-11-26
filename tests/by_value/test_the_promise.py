"""By value: a claimed run always ends with an outcome record, or, before a claim, with a one-line refusal.

Each case here is one place that used to sit outside the run's guards. The run is on the
simulated world (tests/rehearsal/): no real disk, process or time. The sweep in
test_injection.py fails every operation call in turn; these cases name the places it found, and
the ones it cannot reach (a signal, a stream).
"""

import importlib
import io
import os
import sys
import unittest

from shuttle.shell import run
from shuttle.world import signals

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

REQUEST = f"{scenes.RECORDS}/inj-1.request.json"
OUTCOME = f"{scenes.RECORDS}/inj-1.outcome.json"


def ending_of(world):
    return flat(scenes.outcome(world)["receipt"])["ending"]["ending"]


def run_with(world, out, err=None):
    err = err or io.StringIO()
    code = run.run(scenes.DOCUMENT, out, err, world.operations)
    return code, err.getvalue()


class AFailureInstallingTheHandlers(unittest.TestCase):
    def test_is_a_one_line_refusal_and_nothing_is_claimed_or_started(self):
        world = scenes.scene()
        world.will_raise("signals.install", RuntimeError("injected"))
        code, lines, err = scenes.run_in(world)
        self.assertNotEqual(code, 0)
        self.assertEqual(lines, ["none"])
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn("nothing was done", err)
        self.assertEqual(world.names_in(scenes.RECORDS), [])
        self.assertEqual(world.started, [])


class AFailureInTheLastLookAtTheChild(unittest.TestCase):
    def test_still_writes_the_outcome_record(self):
        baseline = scenes.scene()
        scenes.run_in(baseline)
        world = scenes.scene()
        world.will_raise(
            "processes.poll", RuntimeError("injected"), nth=baseline.counts["processes.poll"]
        )
        code, lines, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        self.assertEqual(lines[-1], ending_of(world))
        self.assertIn("inj-1.outcome.json", world.names_in(scenes.RECORDS))


class ATemporaryNameThatCannotBeRemovedAfterTheLink(unittest.TestCase):
    def test_leaves_the_claim_valid_and_the_run_going_with_a_note_on_standard_error(self):
        world = scenes.scene()
        world.will_raise("files.remove", OSError("injected"), nth=1)  # the request record's
        code, lines, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertIn("could not be removed", err)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn(REQUEST, [f"{scenes.RECORDS}/{n}" for n in world.names_in(scenes.RECORDS)])

    def test_leaves_the_outcome_reported_as_written_with_a_note_on_standard_error(self):
        world = scenes.scene()
        world.will_raise("files.remove", OSError("injected"), nth=2)  # the outcome record's
        code, lines, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        self.assertEqual(lines[-2:], [OUTCOME, "ended_by_itself"])
        self.assertIn("could not be removed", err)
        self.assertNotIn("not written", err)


class ASignalDuringTheFinalPrint(unittest.TestCase):
    def test_is_still_caught_by_the_run_and_the_whole_conclusion_is_printed(self):
        world = scenes.scene()
        caught = []

        class Out(io.StringIO):
            def write(self, text):
                if text.startswith(scenes.RECORDS):  # the first line of the conclusion
                    caught.append(world.deliver("SIGTERM"))
                return super().write(text)

        out = Out()
        code, err = run_with(world, out)
        self.assertEqual(code, 0, err)
        self.assertEqual(caught, [True], "the signal's default action would have applied")
        self.assertEqual(out.getvalue().splitlines(), ["inj-1", OUTCOME, "ended_by_itself"])


class TheReaderOfStandardOutputGoingAway(unittest.TestCase):
    """Settled from the spec: "The exit code is zero when an outcome record was written"
    (The command), so a print that fails after the record is written changes neither the
    ending nor the exit code; one line on standard error says the print failed."""

    def test_before_the_end_leaves_the_record_written_and_the_exit_code_zero(self):
        world = scenes.scene()

        class Gone(io.StringIO):
            def write(self, text):
                if text.startswith(scenes.RECORDS):
                    raise BrokenPipeError("injected")
                return super().write(text)

        code, err = run_with(world, Gone())
        self.assertEqual(code, 0, err)
        self.assertEqual(ending_of(world), "ended_by_itself")
        self.assertIn("could not be printed", err)


class TheOtherSignalsTheCommandCanCatch(unittest.TestCase):
    """Settled from the spec: "Wait for the exit, the time limit, a stop record, or a signal",
    and "stopped from outside: stop record, signal". Any signal the command can catch is a signal,
    so each is a stop from outside, like SIGINT, SIGTERM and SIGHUP."""

    def test_each_ends_the_run_as_stopped_from_outside_and_ends_the_child(self):
        for name in ("SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGALRM"):
            with self.subTest(name):
                world = scenes.scene(exits_after=None)
                caught = []
                self.assertIn(name, [s.name for s in signals.HANDLED])  # the real command's own set
                world.on_call(
                    "processes.poll",
                    lambda world=world, caught=caught, name=name: caught.append(
                        world.deliver(name)
                    ),
                    nth=2,
                )
                code, lines, err = scenes.run_in(world)
                self.assertEqual(caught, [True], "the signal's default action would have applied")
                self.assertEqual(code, 0, err)
                receipt = flat(scenes.outcome(world)["receipt"])
                self.assertEqual(
                    (receipt["ending"]["ending"], receipt["ending"]["reason"]),
                    ("stopped_from_outside", "signal"),
                )
                self.assertTrue(world.every_child_has_ended())


if __name__ == "__main__":
    unittest.main()
