"""By value: which run areas a run's start removes, and what it leaves.

The decision (shuttle.core.sweep) is tested over plain data; the sweep (shuttle.shell.
sweep_run_areas) and the runs around it on the simulated world. The same sweep against the real
files, and the whole thing against a killed Shuttle, are in tests/command and tests/boundary.
"""

import fnmatch
import importlib
import io
import itertools
import os
import sys
import unittest

from shuttle.core import boundary, run_area, sweep
from shuttle.shell import check_form, set_up_run_area, sweep_run_areas

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
simulated = importlib.import_module("rehearsal.simulated_world")
flat = importlib.import_module("rehearsal.receipts").flat

# Names that break careless code (the table in tests/hostile/ holds the whole set): a line end,
# an escape sequence, a quote, a space, a backslash and bytes that are not UTF-8.
AWKWARD = ["a\nb", "a\x1b[31mb", 'it\'s "q"', "a b", "a\\b", "bad\udcff\udc80name", "\u202eevil"]

TMP = "/tmp"


def part(number):
    return f"{number:032x}"


def area_of(number):
    return f"{TMP}/{run_area.area_name(part(number))}"


def stale(world, number):
    """What a Shuttle killed hard leaves: the area, with something in it, and its free lock."""
    area = area_of(number)
    world.make_folder(f"{area}/home")
    world.put_file(f"{area}/home/login", "a copy of a login")
    world.put_file(run_area.lock_path(area), "")
    return area


def sweeping(world):
    """The sweep, as a run's set-up calls it: what it printed."""
    err = io.StringIO()
    sweep_run_areas.sweep_before_the_run_makes_its_area(
        {"world": world.operations, "err": err, "out": io.StringIO()}
    )
    return err.getvalue()


def remains(world):
    """The names of Shuttle's areas and locks in the temporary folder."""
    held = [*world.files, *world.folders, *world.links, *world.dangling, *world.special]
    return sorted(
        {
            n[len(TMP) + 1 :].split("/")[0]
            for n in held
            if n.startswith(f"{TMP}/{run_area.AREA_PREFIX}")
        }
    )


def everything(world):
    return (
        dict(world.files),
        set(world.folders),
        dict(world.links),
        set(world.dangling),
        set(world.special),
    )


class WhichNamesAreAnAreasOrALocks(unittest.TestCase):
    def test_only_a_name_that_is_exactly_an_area_or_a_lock_has_a_run_part(self):
        right, other = part(1), part(2)
        area = run_area.area_name(right)
        self.assertEqual(
            sweep.run_parts([area + ".lock", area, run_area.area_name(other), "unrelated"]),
            sorted([right, other]),
        )

    def test_a_name_that_only_looks_like_one_has_none(self):
        area = run_area.area_name(part(1))
        looks_like = [
            area + "\n",
            area + ".lock\n",
            area + ".lock.lock",
            area + ".locks",
            area + "x",
            area[:-1],
            run_area.area_name(part(0xABC).upper()),
            run_area.area_name("z" * 32),
            run_area.area_name(part(1) + "0"),
            run_area.AREA_PREFIX,
            run_area.AREA_PREFIX + ".lock",
            "x" + area,
            " " + area,
            area.replace("shuttle", "shuttl3"),
            run_area.AREA_PREFIX + "abc12345",  # an area from before the name held the run part
            "./" + area,
            "/" + area,
        ]
        for name in AWKWARD:
            looks_like.append(name)
            looks_like.append(name + run_area.AREA_PREFIX)
            looks_like.append(run_area.AREA_PREFIX + name)
        self.assertEqual(sweep.run_parts(looks_like), [])

    def test_a_part_is_found_once_whether_its_area_its_lock_or_both_are_listed(self):
        area = run_area.area_name(part(3))
        for names in ([area], [area + ".lock"], [area, area + ".lock"], [area + ".lock", area]):
            self.assertEqual(sweep.run_parts(names), [part(3)])

    def test_the_pattern_fits_every_scope_of_the_run_and_no_other_runs(self):
        pattern = sweep.unit_pattern(part(5))
        for name in (
            boundary.scope_name("req-1", part(5)),
            boundary.gate_scope_name("req-1", part(5), 0),
            boundary.gate_scope_name("req-1", part(5), 12),
            boundary.freeze_scope_name("req-1", part(5)),
        ):
            self.assertTrue(fnmatch.fnmatchcase(boundary.unit_of(name), pattern), name)
        for name in (
            boundary.scope_name("req-1", part(6)),
            boundary.gate_scope_name("req-1", part(6), 0),
            boundary.freeze_scope_name("req-1", part(6)),
        ):
            self.assertFalse(fnmatch.fnmatchcase(boundary.unit_of(name), pattern), name)


KINDS = ["missing", "file", "folder", "link", "other"]


class TheDecisionOverFacts(unittest.TestCase):
    QUIET = {"u.scope": "inactive", "v.scope": "failed"}

    def test_an_area_that_is_ours_with_a_free_lock_and_no_active_scope_is_removed_after_asking(
        self,
    ):
        folder, lock = ("folder", True), ("file", True)
        self.assertEqual(sweep.next_step(folder, lock, None, None), "take_lock")
        self.assertEqual(sweep.next_step(folder, lock, "taken", None), "ask_scopes")
        self.assertEqual(sweep.next_step(folder, lock, "taken", {}), "remove_area")
        self.assertEqual(sweep.next_step(folder, lock, "taken", self.QUIET), "remove_area")

    def test_a_held_lock_is_in_use_whatever_else_is_true(self):
        for area in (("folder", True), ("missing", False)):
            self.assertEqual(
                sweep.next_step(area, ("file", True), "held", {"u.scope": "inactive"}), "in_use"
            )

    def test_an_active_scope_or_one_that_cannot_be_seen_leaves_the_area(self):
        folder, lock = ("folder", True), ("file", True)
        for state in ("active", "activating", "deactivating", "reloading", "anything else"):
            self.assertEqual(
                sweep.next_step(folder, lock, "taken", {"a.scope": "inactive", "b.scope": state}),
                "scope_active",
            )
        self.assertEqual(sweep.next_step(folder, lock, "taken", "unknown"), "scopes_unknown")

    def test_a_lock_file_with_no_area_is_removed_once_taken_and_asks_nothing_of_scopes(self):
        lock = ("file", True)
        self.assertEqual(sweep.next_step(("missing", False), lock, None, None), "take_lock")
        self.assertEqual(sweep.next_step(("missing", False), lock, "taken", None), "remove_lock")

    def test_a_lock_that_is_gone_when_taken_is_ignored(self):
        self.assertEqual(sweep.next_step(("folder", True), ("file", True), "gone", None), "ignore")

    def test_a_removal_is_chosen_only_when_every_fact_allows_it_over_every_combination(self):
        looks = [(kind, owned) for kind in KINDS for owned in (True, False)]
        scopes = [None, "unknown", {}, self.QUIET, {"a.scope": "active"}]
        for area, lock, taken, seen in itertools.product(
            looks, looks, (None, "taken", "held", "gone"), scopes
        ):
            step = sweep.next_step(area, lock, taken, seen)
            if step in ("remove_area", "remove_lock", "ask_scopes", "scope_active"):
                self.assertEqual(lock, ("file", True))
                self.assertEqual(taken, "taken")
            if step in ("remove_area", "ask_scopes", "scope_active", "scopes_unknown"):
                self.assertEqual(area, ("folder", True))
            if step == "remove_area":
                self.assertIsInstance(seen, dict)
                self.assertTrue(all(v in ("inactive", "failed") for v in seen.values()))
            if step == "remove_lock":
                self.assertEqual(area[0], "missing")
            if lock != ("file", True) or area[0] not in ("folder", "missing"):
                self.assertEqual(step, "ignore")  # not Shuttle's: nothing else is said of it

    def test_the_line_says_how_many_were_removed_and_each_one_left_and_why(self):
        self.assertIsNone(sweep.summary(0, 0, []))
        self.assertEqual(
            sweep.summary(1, 0, []), "shuttle: removed 1 stale run area of runs that are gone"
        )
        line = sweep.summary(
            2, 1, [("shuttle-run-area-a", "why a"), ("shuttle-run-area-b", "why b")]
        )
        self.assertEqual(
            line,
            "shuttle: removed 2 stale run areas of runs that are gone and 1 lock file with no area beside it and a free lock; "
            "left: 'shuttle-run-area-a' (why a), 'shuttle-run-area-b' (why b)",
        )
        self.assertEqual(
            sweep.summary(0, 0, [("n", "w")]),
            "shuttle: removed 0 stale run areas of runs that are gone; left: 'n' (w)",
        )

    def test_a_name_in_the_line_is_shown_escaped_on_one_line(self):
        for name in AWKWARD:
            line = sweep.summary(0, 0, [(name, "why")])
            self.assertIsNotNone(line)
            self.assertEqual(len(line.splitlines()), 1)
            self.assertTrue(line.isprintable())

    def test_a_sweep_that_could_not_be_done_says_so_in_one_line_and_that_the_run_goes_on(self):
        line = sweep.not_swept("PermissionError")
        self.assertEqual(len(line.splitlines()), 1)
        self.assertIn("PermissionError", line)
        self.assertIn("the run goes on", line)


class TheSweepOnTheSimulatedWorld(unittest.TestCase):
    def setUp(self):
        self.world = simulated.SimulatedWorld()
        self.world.make_folder(TMP)

    def test_an_area_whose_lock_is_free_and_whose_scopes_are_gone_is_removed_with_its_lock(self):
        area = stale(self.world, 1)
        line = sweeping(self.world)
        self.assertEqual(line, "shuttle: removed 1 stale run area of runs that are gone\n")
        self.assertFalse(self.world.operations.files.exists(area))
        self.assertFalse(self.world.operations.files.exists(run_area.lock_path(area)))
        self.assertEqual(remains(self.world), [])
        self.assertEqual(self.world.locks_held, set())
        self.assertEqual(
            [args for args, _ in self.world.calls("boundary.list_units")],
            [(sweep.unit_pattern(part(1)),)],
        )

    def test_scopes_that_are_inactive_or_failed_do_not_keep_an_area(self):
        stale(self.world, 1)
        self.world.put_unit(boundary.unit_of(boundary.scope_name("r", part(1))), "failed")
        self.world.put_unit(boundary.unit_of(boundary.freeze_scope_name("r", part(1))), "inactive")
        self.assertIn("removed 1 stale", sweeping(self.world))

    def test_a_stale_looking_area_whose_scope_is_still_active_is_left_and_the_line_says_so(self):
        for scope in (
            boundary.scope_name("r", part(1)),
            boundary.gate_scope_name("r", part(1), 0),
            boundary.freeze_scope_name("r", part(1)),
        ):
            with self.subTest(scope):
                world = simulated.SimulatedWorld()
                world.make_folder(TMP)
                stale(world, 1)
                world.put_unit(boundary.unit_of(scope), "active")
                before = everything(world)
                line = sweeping(world)
                self.assertEqual(
                    line,
                    f"shuttle: removed 0 stale run areas of runs that are gone; left: "
                    f"{run_area.area_name(part(1))!r} ({sweep.REASON_SCOPE_ACTIVE})\n",
                )
                self.assertEqual(everything(world), before)  # the area and its lock file stay
                self.assertEqual(world.calls("boundary.stop"), [])  # and nothing is stopped
                self.assertEqual(world.calls("boundary.forget"), [])
                self.assertEqual(world.locks_held, set())  # the look let go of the lock

    def test_a_scope_of_another_run_does_not_keep_the_area(self):
        stale(self.world, 1)
        self.world.put_unit(boundary.unit_of(boundary.scope_name("r", part(2))), "active")
        self.assertIn("removed 1 stale", sweeping(self.world))

    def test_scopes_that_cannot_be_looked_up_leave_the_area_and_the_line_says_so(self):
        area = stale(self.world, 1)
        self.world.will_raise("boundary.list_units", OSError("systemctl did not answer"))
        line = sweeping(self.world)
        self.assertIn(f"{run_area.area_name(part(1))!r} ({sweep.REASON_SCOPES_UNKNOWN})", line)
        self.assertTrue(self.world.operations.files.exists(area))
        self.assertTrue(self.world.operations.files.exists(run_area.lock_path(area)))

    def test_an_area_whose_lock_is_held_is_left_alone_and_nothing_is_said_or_asked(self):
        area = stale(self.world, 1)
        self.world.put_lock_held_elsewhere(run_area.lock_path(area))
        before = everything(self.world)
        self.assertEqual(sweeping(self.world), "")
        self.assertEqual(everything(self.world), before)
        self.assertEqual(self.world.calls("boundary.list_units"), [])
        self.assertEqual(self.world.calls("files.remove_tree"), [])

    def test_an_area_that_cannot_be_removed_is_left_with_its_lock_and_the_line_says_so(self):
        area = stale(self.world, 1)
        self.world.will_raise("files.remove_tree", PermissionError("secret detail"))
        line = sweeping(self.world)
        self.assertEqual(
            line,
            "shuttle: removed 0 stale run areas of runs that are gone; left: "
            f"{run_area.area_name(part(1))!r} (it could not be removed (PermissionError))\n",
        )
        self.assertNotIn("secret detail", line)
        self.assertTrue(self.world.operations.files.exists(run_area.lock_path(area)))
        self.assertEqual(self.world.locks_held, set())

    def test_a_failure_on_one_area_does_not_stop_the_others(self):
        stale(self.world, 1)
        stale(self.world, 2)
        self.world.will_raise("files.remove_tree", OSError("injected"), nth=1)
        line = sweeping(self.world)
        self.assertIn("removed 1 stale run area of", line)
        self.assertIn(f"{run_area.area_name(part(1))!r} (it could not be removed (OSError))", line)
        first = run_area.area_name(part(1))
        self.assertEqual(remains(self.world), [first, first + ".lock"])  # only the second is gone

    def test_a_name_that_could_not_be_looked_at_is_left_and_the_line_says_it_was_not_checked(self):
        stale(self.world, 1)
        self.world.will_raise("files.look_at", PermissionError("detail"))
        line = sweeping(self.world)
        self.assertIn(
            f"{run_area.area_name(part(1))!r} (it could not be checked (PermissionError))", line
        )
        self.assertEqual(self.world.calls("files.remove_tree"), [])

    def test_a_lock_that_cannot_be_taken_for_a_reason_other_than_being_held_leaves_the_area(self):
        area = stale(self.world, 1)
        self.world.will_raise("files.try_lock", PermissionError("detail"))
        self.assertIn("could not be checked (PermissionError)", sweeping(self.world))
        self.assertTrue(self.world.operations.files.exists(area))

    def test_a_lock_file_with_no_area_that_cannot_be_removed_is_named_as_a_lock_file_not_an_area(
        self,
    ):
        lock = run_area.lock_path(area_of(1))
        self.world.put_file(lock, "")
        self.world.will_raise("files.release_lock", PermissionError("detail"), nth=1)
        line = sweeping(self.world)
        name = run_area.area_name(part(1)) + run_area.LOCK_SUFFIX
        self.assertEqual(
            line,
            "shuttle: removed 0 stale run areas of runs that are gone; left: "
            f"{name!r} (it could not be removed (PermissionError))\n",
        )
        self.assertNotIn(f"{run_area.area_name(part(1))!r}", line)
        self.assertTrue(self.world.operations.files.exists(lock))

    def test_a_sweep_that_stops_on_the_second_of_two_areas_reports_the_first_it_removed(self):
        stale(self.world, 1)
        stale(self.world, 2)
        # two looks per area: the third look is the second area's first
        self.world.will_raise("files.look_at", RuntimeError("injected"), nth=3)
        line = sweeping(self.world)
        self.assertEqual(
            line,
            "shuttle: removed 1 stale run area of runs that are gone; "
            "the sweep then stopped (RuntimeError) and the run goes on\n",
        )
        self.assertEqual(
            remains(self.world), [run_area.area_name(part(2)) + s for s in ("", ".lock")]
        )
        self.assertEqual(self.world.locks_held, set())

    def test_a_lock_file_with_no_area_beside_it_is_removed_and_counted_as_a_lock_file(self):
        lock = run_area.lock_path(area_of(1))
        self.world.put_file(lock, "")
        line = sweeping(self.world)
        self.assertEqual(
            line,
            "shuttle: removed 0 stale run areas of runs that are gone and 1 lock file with no area beside it and a free lock\n",
        )
        self.assertFalse(self.world.operations.files.exists(lock))
        self.assertEqual(self.world.calls("boundary.list_units"), [])

    def test_a_lock_file_with_no_area_that_is_held_or_not_ours_is_left(self):
        held = run_area.lock_path(area_of(1))
        self.world.put_lock_held_elsewhere(held)
        foreign = run_area.lock_path(area_of(2))
        self.world.put_file(foreign, "")
        self.world.put_foreign(foreign)
        before = everything(self.world)
        self.assertEqual(sweeping(self.world), "")
        self.assertEqual(everything(self.world), before)

    def test_nothing_that_looked_stale_is_no_line(self):
        self.assertEqual(sweeping(self.world), "")
        self.world.put_file(f"{TMP}/unrelated", "")
        self.assertEqual(sweeping(self.world), "")

    def test_the_temporary_folder_that_cannot_be_listed_is_one_line_and_nothing_removed(self):
        stale(self.world, 1)
        self.world.will_raise("files.list_names", PermissionError("detail"))
        line = sweeping(self.world)
        self.assertEqual(line, sweep.not_swept("PermissionError") + "\n")
        self.assertEqual(self.world.calls("files.remove_tree"), [])

    def test_a_sweep_that_fails_for_any_reason_never_raises(self):
        for operation in ("files.temporary_folder", "files.list_names", "files.look_at"):
            with self.subTest(operation):
                world = simulated.SimulatedWorld()
                world.make_folder(TMP)
                stale(world, 1)
                world.will_raise(operation, RuntimeError("injected"))
                self.assertNotEqual(sweeping(world), "")

    def test_a_reader_of_the_line_that_went_away_does_not_stop_the_sweep(self):
        stale(self.world, 1)

        class Gone:
            def write(self, text):
                raise BrokenPipeError

        sweep_run_areas.sweep_before_the_run_makes_its_area(
            {"world": self.world.operations, "err": Gone()}
        )
        self.assertEqual(remains(self.world), [])

    def test_two_sweeps_at_once_remove_an_area_once_and_the_second_leaves_it_to_the_first(self):
        stale(self.world, 1)
        seen = []
        # While the first sweep holds the lock and asks about scopes, a second sweep starts.
        self.world.on_call("boundary.list_units", lambda: seen.append(sweeping(self.world)))
        first = sweeping(self.world)
        self.assertEqual(seen, [""])  # the second saw a held lock: said nothing, took nothing
        self.assertEqual(first, "shuttle: removed 1 stale run area of runs that are gone\n")
        self.assertEqual(len(self.world.calls("files.remove_tree")), 1)
        self.assertEqual(remains(self.world), [])

    def test_a_sweep_between_the_runs_lock_and_its_area_finds_the_lock_held_and_leaves_it(self):
        world = scenes.scene()
        seen = []
        world.on_call("files.make_private_folder", lambda: seen.append(sweeping(world)))
        world.make_folder(TMP)
        code, _, err = scenes.run_in(world)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(seen, [""])
        self.assertEqual(
            flat(scenes.outcome(world)["receipt"])["ending"]["ending"], "ended_by_itself"
        )

    def test_a_sweep_between_the_areas_removal_and_its_locks_is_a_held_lock_and_changes_nothing(
        self,
    ):
        world = scenes.scene()
        seen = []
        world.on_call("files.release_lock", lambda: seen.append(sweeping(world)))
        scenes.run_in(world)
        self.assertEqual(seen, [""])
        self.assertEqual(remains(world), [])


class ALookAlikeIsLeftAlone(unittest.TestCase):
    """A folder that only looks like a run area is never removed, with or without a lock file."""

    def setUp(self):
        self.world = simulated.SimulatedWorld()
        self.world.make_folder(TMP)

    def left_alone(self):
        before = everything(self.world)
        self.assertEqual(sweeping(self.world), "")
        self.assertEqual(everything(self.world), before)
        self.assertEqual(self.world.calls("files.remove_tree"), [])
        self.assertEqual(self.world.calls("boundary.list_units"), [])
        self.assertEqual(self.world.locks_held, set())

    def test_a_folder_with_the_right_name_and_no_lock_file_an_area_from_before_the_lock(self):
        self.world.make_folder(f"{area_of(1)}/home")
        self.left_alone()

    def test_a_folder_whose_lock_file_is_a_link(self):
        area = area_of(1)
        self.world.make_folder(f"{area}/home")
        self.world.put_file(f"{TMP}/elsewhere", "")
        self.world.put_link(run_area.lock_path(area), f"{TMP}/elsewhere")
        self.left_alone()

    def test_a_folder_whose_lock_file_leads_nowhere(self):
        area = area_of(1)
        self.world.make_folder(area)
        self.world.put_a_name_that_leads_nowhere(run_area.lock_path(area))
        self.left_alone()

    def test_a_link_to_a_folder_with_a_lock_file(self):
        self.world.make_folder(f"{TMP}/real/home")
        self.world.put_link(area_of(1), f"{TMP}/real")
        self.world.put_file(run_area.lock_path(area_of(1)), "")
        self.left_alone()

    def test_a_file_with_the_areas_name_and_a_lock_file(self):
        self.world.put_file(area_of(1), "not a folder")
        self.world.put_file(run_area.lock_path(area_of(1)), "")
        self.left_alone()

    def test_a_folder_not_owned_by_the_user_with_a_free_lock_file(self):
        area = area_of(1)
        self.world.make_folder(f"{area}/home")
        self.world.put_foreign(area)
        self.world.put_file(run_area.lock_path(area), "")
        self.left_alone()

    def test_a_folder_whose_lock_file_is_not_owned_by_the_user(self):
        area = area_of(1)
        self.world.make_folder(area)
        self.world.put_file(run_area.lock_path(area), "")
        self.world.put_foreign(run_area.lock_path(area))
        self.left_alone()

    def test_a_folder_whose_lock_is_a_folder_or_a_pipe(self):
        for number, make in ((1, self.world.make_folder), (2, self.world.put_pipe)):
            self.world.make_folder(area_of(number))
            make(run_area.lock_path(area_of(number)))
        self.left_alone()

    def test_a_name_that_is_not_exactly_the_pattern_with_a_lock_file(self):
        for name in (
            run_area.area_name(part(1)) + "-old",
            run_area.area_name(part(0xABC).upper()),
            run_area.AREA_PREFIX + "abc12345",
        ):
            self.world.make_folder(f"{TMP}/{name}")
            self.world.put_file(f"{TMP}/{name}.lock", "")
        self.left_alone()

    def test_a_folder_in_another_temporary_folder_is_not_looked_at(self):
        self.world.make_folder("/other")
        self.world.make_folder(f"/other/{run_area.area_name(part(1))}")
        self.world.put_file(f"/other/{run_area.area_name(part(1))}.lock", "")
        self.left_alone()


class TheSweepInARun(unittest.TestCase):
    def test_a_run_removes_the_area_of_a_run_that_is_gone_and_ends_as_it_would_have(self):
        world = scenes.scene()
        world.make_folder(TMP)
        stale(world, 9)
        code, _, err = scenes.run_in(world)
        self.assertEqual(
            (code, err), (0, "shuttle: removed 1 stale run area of runs that are gone\n")
        )
        self.assertEqual(remains(world), [])
        receipt = flat(scenes.outcome(world)["receipt"])
        self.assertEqual(receipt["ending"]["ending"], "ended_by_itself")
        self.assertEqual(receipt["execution"]["teardown_failure"], "none")

    def test_a_sweep_that_fails_changes_nothing_about_the_run_not_its_ending_exit_or_receipt(self):
        clean = scenes.scene()
        clean.make_folder(TMP)
        scenes.run_in(clean)
        clean_receipt = flat(scenes.outcome(clean)["receipt"])
        for operation, error in (
            ("files.remove_tree", PermissionError("detail")),
            ("files.list_names", OSError("detail")),
            ("boundary.list_units", OSError("detail")),
            ("files.try_lock", OSError("detail")),
            ("files.release_lock", OSError("detail")),
        ):
            with self.subTest(operation):
                world = scenes.scene()
                world.make_folder(TMP)
                stale(world, 9)
                world.will_raise(operation, error)  # the sweep's own first call is the first
                code, _, err = scenes.run_in(world)
                self.assertEqual(code, 0)
                receipt = flat(scenes.outcome(world)["receipt"])
                for field in ("ending", "reason", "failed_step", "everything_stopped"):
                    self.assertEqual(receipt["ending"][field], clean_receipt["ending"][field])
                self.assertLessEqual(len(err.splitlines()), 1)

    def test_a_run_whose_sweep_stops_on_the_second_area_reports_the_first_and_ends_as_it_would(
        self,
    ):
        world = scenes.scene()
        world.make_folder(TMP)
        stale(world, 8)
        stale(world, 9)
        world.will_raise("files.look_at", RuntimeError("injected"), nth=3)
        code, _, err = scenes.run_in(world)
        self.assertEqual(code, 0)
        self.assertEqual(
            err,
            "shuttle: removed 1 stale run area of runs that are gone; "
            "the sweep then stopped (RuntimeError) and the run goes on\n",
        )
        receipt = flat(scenes.outcome(world)["receipt"])
        self.assertEqual(receipt["ending"]["ending"], "ended_by_itself")

    def test_a_run_whose_sweep_could_not_remove_an_area_prints_one_line_and_ends_normally(self):
        world = scenes.scene()
        world.make_folder(TMP)
        stale(world, 9)
        world.will_raise("files.remove_tree", PermissionError("detail"), nth=1)
        code, _, err = scenes.run_in(world)
        self.assertEqual(code, 0)
        self.assertEqual(
            err,
            "shuttle: removed 0 stale run areas of runs that are gone; left: "
            f"{run_area.area_name(part(9))!r} (it could not be removed (PermissionError))\n",
        )
        receipt = flat(scenes.outcome(world)["receipt"])
        self.assertEqual(receipt["ending"]["ending"], "ended_by_itself")
        self.assertEqual(receipt["execution"]["teardown_failure"], "none")

    def test_a_live_runs_area_is_left_whole_while_another_run_starts_and_ends(self):
        world = scenes.scene()
        world.make_folder(TMP)
        live = area_of(9)
        world.make_folder(f"{live}/home")
        world.put_file(f"{live}/home/login", "a copy of a login")
        world.put_lock_held_elsewhere(run_area.lock_path(live))
        before = {n: d for n, d in world.files.items() if n.startswith(live)}
        code, _, err = scenes.run_in(world)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual({n: d for n, d in world.files.items() if n.startswith(live)}, before)
        self.assertIn(run_area.lock_path(live), world.files)
        self.assertEqual(
            flat(scenes.outcome(world)["receipt"])["ending"]["ending"], "ended_by_itself"
        )

    def test_the_sweep_comes_after_the_plan_is_accepted_and_before_the_runs_own_lock(self):
        world = scenes.scene()
        scenes.run_in(world)
        order = [op for op, _, _ in world.log if op in ("files.list_names", "files.create_lock")]
        self.assertEqual(order, ["files.list_names", "files.create_lock"])
        refused = simulated.SimulatedWorld()
        state = {
            "world": refused.operations,
            "problems": {},
            "stand_ins": {},
            "facts": {},
            "run_part": part(1),
            "err": io.StringIO(),
        }
        bad = [{"action": "copy", "name": "../x", "source": "/s"}]
        self.assertEqual(set_up_run_area.set_up(state, bad), {"ok": False})
        self.assertEqual(refused.calls("files.list_names"), [])

    def test_the_check_form_sweeps_nothing_and_changes_no_area(self):
        world = scenes.scene()
        world.make_folder(TMP)
        stale(world, 9)
        before = everything(world)
        out, err = io.StringIO(), io.StringIO()
        check_form.check(scenes.DOCUMENT, out, err, world.operations)
        self.assertEqual(everything(world), before)
        for operation in (
            "files.list_names",
            "files.temporary_folder",
            "files.try_lock",
            "files.create_lock",
            "boundary.list_units",
            "files.look_at",
        ):
            self.assertEqual(world.calls(operation), [], operation)
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
