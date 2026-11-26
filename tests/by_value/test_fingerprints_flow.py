"""By value, through the whole run on the simulated world: the two fingerprints and the place.

The decisions are tested in test_place.py; here the order of a run is looked at: the place is
refused before anything starts (in a run and in the check form alike), the opening fingerprint
is taken after the gates and before the executor, the closing freeze only when the boundary was
seen empty, and each leaves the receipt's fields as the spec says.
"""

import importlib
import io
import json
import os
import sys
import unittest

from shuttle.core import boundary, place
from shuttle.shell import check_form

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

CNS, EF = "could_not_start", "execution_failed"
PLACE = scenes.PLACE
CAUGHT = {"README": "the place\n", "keep.txt": "kept\n", "old.txt": "old\n"}


def ending_of(world):
    ending = flat(scenes.outcome(world)["receipt"])["ending"]
    return ending["ending"], ending["reason"], ending["failed_step"]


def execution_of(world):
    return flat(scenes.outcome(world)["receipt"])["execution"]


def a_world(doc=None, files=CAUGHT, **program):
    world = scenes.scene(doc, **program)
    world.make_place(PLACE, files)
    return world


def check(world):
    out, err = io.StringIO(), io.StringIO()
    code = check_form.check(scenes.DOCUMENT, out, err, world.operations)
    return code, out.getvalue().splitlines(), err.getvalue()


def refusals_in_the_place():
    """(label, how to make the world so, reason): each refusal the place can give."""

    def not_there(world):
        world.folders.discard(PLACE)

    def not_a_checkout(world):
        del world.places[PLACE]

    def uncommitted(world):
        world.put_file(f"{PLACE}/README", "changed")

    def new_file(world):
        world.put_file(f"{PLACE}/new.txt", "new")

    def a_file_removed(world):
        del world.files[f"{PLACE}/old.txt"]

    def nested(world):
        world.places[PLACE]["nested"] = ["inner"]

    return [
        ("the place is not there", not_there, "place_missing"),
        ("the place is not a git checkout", not_a_checkout, "place_not_a_git_checkout"),
        ("a committed file was changed", uncommitted, "place_has_uncommitted_changes"),
        ("a new file is there", new_file, "place_has_uncommitted_changes"),
        ("a committed file was removed", a_file_removed, "place_has_uncommitted_changes"),
        ("a repository is nested", nested, "place_has_nested_repository"),
    ]


class ThePlaceIsRefusedBeforeAnythingStarts(unittest.TestCase):
    def test_each_refusal_is_a_could_not_start_at_the_input_check_and_nothing_runs(self):
        for label, prepare, reason in refusals_in_the_place():
            with self.subTest(label):
                world = a_world()
                prepare(world)
                code, lines, err = scenes.run_in(world)
                self.assertEqual((code, err, lines[-1]), (0, "", CNS))
                self.assertEqual(ending_of(world), (CNS, reason, "input_check"))
                self.assertEqual(world.started, [])
                self.assertEqual(world.counts.get("git.freeze", 0), 0)
                fields = execution_of(world)
                self.assertEqual(fields["fingerprint_before"], "none")  # a refusal carries none

    def test_a_document_with_no_place_is_refused_as_a_missing_place(self):
        doc = {k: v for k, v in scenes.document().items() if k != "place"}
        world = a_world(doc)
        scenes.run_in(world)
        self.assertEqual(ending_of(world), (CNS, "place_missing", "input_check"))

    def test_a_place_that_is_not_text_is_refused_as_a_missing_setting(self):
        for bad in (3, ["x"], None, True):
            with self.subTest(place=bad):
                world = a_world(scenes.document(place=bad))
                scenes.run_in(world)
                self.assertEqual(ending_of(world), (CNS, "missing_setting", "input_check"))

    def test_the_problem_line_names_the_place_and_what_to_do(self):
        world = a_world()
        world.put_file(f"{PLACE}/new.txt", "new")
        scenes.run_in(world)
        text = flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
        self.assertIn(PLACE, text)
        self.assertIn("new.txt", text)

    def test_the_check_form_gives_the_same_verdict_for_each_refusal_and_changes_nothing(self):
        for label, prepare, reason in refusals_in_the_place():
            with self.subTest(label):
                world = a_world()
                prepare(world)
                before = {n: bytes(b) for n, b in world.files.items()}
                code, lines, err = check(world)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(lines[2], f"check: refused: {reason}")
                record = json.loads(lines[1])
                receipt = flat(record["receipt"])["ending"]
                self.assertEqual(
                    (receipt["ending"], receipt["reason"], receipt["failed_step"]),
                    (CNS, reason, "input_check"),
                )
                self.assertEqual(before, {n: bytes(b) for n, b in world.files.items()})
                self.assertEqual(world.started, [])
                self.assertEqual(world.counts.get("git.freeze", 0), 0)

    def test_the_check_form_passes_a_clean_place(self):
        _, lines, _ = check(a_world())
        self.assertEqual(lines[1], "check: no refusal found")

    def test_the_place_is_looked_at_with_the_environment_the_core_builds_and_nothing_of_the_callers(
        self,
    ):
        world = a_world()
        world.variables.update(
            {"PATH": "/bin", "GIT_DIR": "/elsewhere", "HOME": "/home/x", "GIT_AUTHOR_NAME": "Me"}
        )
        scenes.run_in(world)
        looks = world.calls("git.look_at_place")
        self.assertEqual(len(looks), 2)  # the input check, then the opening fingerprint
        for (where, environment), _ in looks:
            self.assertEqual(where, PLACE)
            self.assertEqual(environment, place.git_environment("/bin"))
            self.assertNotIn("GIT_DIR", environment)
            self.assertNotIn("HOME", environment)


class TheOpeningFingerprint(unittest.TestCase):
    def test_it_is_the_places_own_commit_taken_after_the_gates_and_before_the_executor(self):
        doc = scenes.document(
            gates=[{"name": "g", "command": "gate", "arguments": [], "limit_seconds": 5}]
        )
        world = a_world(doc)
        world.program("gate")
        head = world.places[PLACE]["head"]
        scenes.run_in(world)
        self.assertEqual(execution_of(world)["fingerprint_before"], head)
        names = [op for op, _, _ in world.log]
        looks = [i for i, op in enumerate(names) if op == "git.look_at_place"]
        gate = names.index("processes.start")
        executor = len(names) - 1 - names[::-1].index("processes.start")
        self.assertLess(looks[0], gate)  # the input check
        self.assertTrue(
            gate < looks[1] < executor
        )  # the fingerprint: after the gate, before the executor

    def test_it_makes_no_commit_and_no_reference(self):
        world = a_world()
        scenes.run_in(world)
        self.assertEqual(world.refs, {})

    def test_a_place_made_unclean_after_the_input_check_is_a_failed_opening_freeze(self):
        doc = scenes.document(
            gates=[{"name": "g", "command": "gate", "arguments": [], "limit_seconds": 5}]
        )
        world = a_world(doc)
        world.program("gate", creates=[f"{PLACE}/left-by-the-gate.txt"])
        code, lines, err = scenes.run_in(world)
        self.assertEqual((code, lines[-1]), (0, CNS))
        self.assertEqual(ending_of(world), (CNS, "freeze_failed", "opening_freeze"))
        text = flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
        self.assertIn("left-by-the-gate.txt", text)
        self.assertEqual(execution_of(world)["fingerprint_before"], "cannot tell")
        self.assertEqual(
            [c.argv[0] for c in world.children], ["gate"]
        )  # the executor never started


class TheClosingFreeze(unittest.TestCase):
    def change_the_place(self, world, creates=(), changes=(), removes=()):
        def do():
            for name in creates:
                world.put_file(f"{PLACE}/{name}", "created")
            for name in changes:
                world.put_file(f"{PLACE}/{name}", "changed")
            for name in removes:
                del world.files[f"{PLACE}/{name}"]

        world.on_call("processes.wait", do, nth=1)

    def test_a_run_that_changes_nothing_has_equal_fingerprints_and_says_it_changed_nothing(self):
        world = a_world()
        head = world.places[PLACE]["head"]
        scenes.run_in(world)
        saw = execution_of(world)
        self.assertEqual((saw["fingerprint_before"], saw["fingerprint_after"]), (head, head))
        self.assertIs(saw["changed_nothing"], True)
        self.assertEqual(
            (saw["files_added"], saw["files_changed"], saw["files_deleted"]), (0, 0, 0)
        )
        self.assertEqual(world.refs, {})  # equal files: nothing was made

    def test_a_run_that_adds_changes_and_deletes_gives_matching_counts_and_one_commit(self):
        world = a_world(hangs=True)
        self.change_the_place(
            world, creates=("a", "b new"), changes=("README",), removes=("old.txt", "keep.txt")
        )
        world.on_call("processes.poll", lambda: world.deliver("SIGINT"), nth=2)
        scenes.run_in(world)
        saw = execution_of(world)
        self.assertEqual(
            (saw["files_added"], saw["files_changed"], saw["files_deleted"]), (2, 1, 2)
        )
        self.assertIs(saw["changed_nothing"], False)
        self.assertNotEqual(saw["fingerprint_after"], saw["fingerprint_before"])
        self.assertEqual(list(world.refs), ["refs/shuttle/freeze/inj-1"])
        self.assertEqual(world.refs["refs/shuttle/freeze/inj-1"], saw["fingerprint_after"])

    def test_the_freeze_runs_in_a_scope_of_its_own_named_for_the_run_with_the_runs_limit(self):
        world = a_world(scenes.document(limit=7))
        scenes.run_in(world)
        (command, _), _ = world.calls("git.freeze")[0]
        self.assertIn(f"--unit={boundary.freeze_scope_name('inj-1')}", command)
        self.assertIn("RuntimeMaxSec=7000000us", command)

    def test_the_freeze_has_the_limit_the_document_gives_it_and_the_runs_when_it_gives_none(self):
        world = a_world(scenes.document(limit=7, freeze_limit_seconds=2.5))
        scenes.run_in(world)
        (command, _), _ = world.calls("git.freeze")[0]
        self.assertIn("RuntimeMaxSec=2500000us", command)

    def test_a_freeze_limit_that_is_not_a_usable_number_is_refused(self):
        for bad in (0, -1, "5", None, True, float("inf"), 10**12):
            with self.subTest(bad=bad):
                world = a_world(scenes.document(freeze_limit_seconds=bad))
                scenes.run_in(world)
                self.assertEqual(ending_of(world), (CNS, "missing_setting", "input_check"))

    def test_the_freeze_scope_is_stopped_by_name_and_seen_empty_after_it(self):
        world = a_world()
        scenes.run_in(world)
        unit = boundary.unit_of(boundary.freeze_scope_name("inj-1"))
        order = [
            (op, args[0]) for op, args, _ in world.log if op in ("git.freeze", "boundary.stop")
        ]
        self.assertEqual(order[-2][0], "git.freeze")
        self.assertEqual(order[-1], ("boundary.stop", unit))
        self.assertNotIn(unit, world.units)

    def test_the_freeze_is_given_the_neutral_environment_and_nothing_of_the_callers(self):
        world = a_world()
        world.variables.update(
            {
                "PATH": "/bin",
                "GIT_DIR": "/elsewhere",
                "GIT_INDEX_FILE": "/callers-index",
                "HOME": "/home/x",
                "GIT_COMMITTER_NAME": "Me",
                "XDG_RUNTIME_DIR": "/run/user/1",
            }
        )
        scenes.run_in(world)
        (_, environment), _ = world.calls("git.freeze")[0]
        self.assertEqual(
            environment, {**place.git_environment("/bin"), "XDG_RUNTIME_DIR": "/run/user/1"}
        )
        self.assertEqual(environment["GIT_COMMITTER_NAME"], "Shuttle")

    def test_a_freeze_that_fails_is_execution_failed_with_the_opening_fingerprint_only(self):
        world = a_world()
        world.the_freeze = "fails"
        head = world.places[PLACE]["head"]
        code, lines, err = scenes.run_in(world)
        self.assertEqual((code, lines[-1]), (0, EF))
        self.assertEqual(ending_of(world), (EF, "closing_freeze_failed", "closing_freeze"))
        saw = execution_of(world)
        self.assertEqual(saw["fingerprint_before"], head)
        for field in (
            "fingerprint_after",
            "changed_nothing",
            "files_added",
            "files_changed",
            "files_deleted",
        ):
            self.assertEqual(saw[field], "cannot tell", field)
        text = flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
        self.assertIn("closing freeze failed", text)
        self.assertEqual(world.refs, {})

    def test_a_freeze_that_runs_out_of_its_limit_is_a_failed_freeze_and_its_scope_is_gone(self):
        world = a_world()
        world.the_freeze = "times_out"
        scenes.run_in(world)
        self.assertEqual(ending_of(world), (EF, "closing_freeze_failed", "closing_freeze"))
        text = flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
        self.assertIn("limit", text)
        self.assertNotIn(boundary.unit_of(boundary.freeze_scope_name("inj-1")), world.units)

    def test_a_freeze_whose_command_cannot_be_started_is_a_failed_freeze(self):
        world = a_world()
        world.will_raise("git.freeze", OSError("injected"))
        scenes.run_in(world)
        self.assertEqual(ending_of(world), (EF, "closing_freeze_failed", "closing_freeze"))

    def test_no_freeze_is_taken_when_the_stop_was_not_confirmed(self):
        world = scenes.scene(hangs=True, survives_stop=True)
        world.on_call("processes.poll", lambda: world.deliver("SIGINT"), nth=2)
        scenes.run_in(world)
        self.assertEqual(ending_of(world), (EF, "stop_not_confirmed", "stop_not_confirmed"))
        self.assertEqual(world.counts.get("git.freeze", 0), 0)
        self.assertEqual(execution_of(world)["fingerprint_after"], "none")

    def test_nothing_in_the_place_is_touched_by_the_run_itself(self):
        world = a_world()
        before = world._in_place(PLACE)
        scenes.run_in(world)
        self.assertEqual(world._in_place(PLACE), before)


if __name__ == "__main__":
    unittest.main()
