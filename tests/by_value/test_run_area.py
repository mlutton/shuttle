"""By value: the plan for a driver's setup requests (pure), the set-up and tear-down steps on the
simulated world, and the run area through a whole run: made, used, removed whatever the ending.

The same steps against the real files are in tests/command/test_run_area.py.
"""

import importlib
import os
import sys
import unittest

from shuttle.core import run_area
from shuttle.shell import set_up_run_area, tear_down

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
simulated = importlib.import_module("rehearsal.simulated_world")
flat = importlib.import_module("rehearsal.receipts").flat

AREA = "/tmp/area"


def copy(name, source="/src/x"):
    return {"action": "copy", "name": name, "source": source}


class ThePlan(unittest.TestCase):
    def test_each_action_becomes_its_step_with_whole_paths(self):
        got = run_area.plan(
            AREA,
            [
                copy("home", "/data/with space/$HOME"),
                {"action": "leave_out", "name": "home/history"},
                {"action": "leave_out", "name": "home/cache/deep"},
                {"action": "share", "name": "home/login", "source": "/data/login"},
                {"action": "write", "name": "config/generated.toml", "text": "a = 1\n"},
                {"action": "writable", "name": "home"},
                {"action": "variable", "variable": "TOOL_HOME", "in_run_area": "home"},
                {"action": "variable", "variable": "MODE", "value": "quiet"},
            ],
        )
        self.assertEqual(got["problem"], None)
        self.assertEqual(
            got["steps"],
            [
                {
                    "do": "copy",
                    "source": "/data/with space/$HOME",
                    "target": f"{AREA}/home",
                    "leave_out": ["history", "cache/deep"],
                },
                {"do": "folder", "target": f"{AREA}/home"},
                {"do": "share", "source": "/data/login", "target": f"{AREA}/home/login"},
                {"do": "folder", "target": f"{AREA}/config"},
                {"do": "write", "target": f"{AREA}/config/generated.toml", "text": "a = 1\n"},
                {"do": "writable", "target": f"{AREA}/home"},
            ],
        )
        self.assertEqual(got["variables"], {"TOOL_HOME": f"{AREA}/home", "MODE": "quiet"})

    def test_a_leave_out_applies_to_a_copy_listed_after_it_too(self):
        got = run_area.plan(AREA, [{"action": "leave_out", "name": "h/old"}, copy("h")])
        self.assertEqual(got["steps"][0]["leave_out"], ["old"])

    def test_no_requests_is_an_empty_plan(self):
        self.assertEqual(run_area.plan(AREA, []), {"steps": [], "variables": {}, "problem": None})

    def test_every_refused_request_says_which_and_plans_nothing(self):
        table = {
            "not an action": [{"action": "delete", "name": "x"}],
            "not a dictionary": ["copy"],
            "a name that climbs out": [copy("../out")],
            "a name that climbs out inside": [copy("a/../../out")],
            "an absolute name": [copy("/etc/x")],
            "an empty name": [copy("")],
            "an empty part": [copy("a//b")],
            "a dot part": [copy("a/./b")],
            "a name with a newline": [copy("a\nb")],
            "a name with a space": [copy("a b")],
            "a name that is not text": [{"action": "write", "name": 3, "text": ""}],
            "the instruction's name": [copy(run_area.INSTRUCTION_NAME)],
            "a relative source": [copy("a", "relative/path")],
            "a source with a null": [copy("a", "/x\0y")],
            "a write with no text": [{"action": "write", "name": "a"}],
            "a name made twice": [copy("a"), copy("a")],
            "a name under a shared name": [
                {"action": "share", "name": "login", "source": "/l"},
                {"action": "write", "name": "login/x", "text": ""},
            ],
            "a copy under a shared name": [
                {"action": "share", "name": "login", "source": "/l"},
                copy("login/x"),
            ],
            "a shared name made writable": [
                {"action": "share", "name": "login", "source": "/l"},
                {"action": "writable", "name": "login"},
            ],
            "a name below a shared one made writable": [
                {"action": "share", "name": "login", "source": "/l"},
                {"action": "writable", "name": "login/x"},
            ],
            "a name nothing made, made writable": [{"action": "writable", "name": "x"}],
            "a leave-out no copy holds": [
                copy("a"),
                {"action": "leave_out", "name": "b/x"},
            ],
            "a leave-out of the copy itself": [
                copy("a"),
                {"action": "leave_out", "name": "a"},
            ],
            "a variable with a bad name": [{"action": "variable", "variable": "A=B", "value": ""}],
            "the path variable": [{"action": "variable", "variable": "PATH", "value": "x"}],
            "a variable with no value": [{"action": "variable", "variable": "A"}],
            "a variable with two values": [
                {"action": "variable", "variable": "A", "value": "x", "in_run_area": "y"}
            ],
            "a variable passed twice": [
                {"action": "variable", "variable": "A", "value": "x"},
                {"action": "variable", "variable": "A", "value": "y"},
            ],
            "a variable's path that climbs out": [
                {"action": "variable", "variable": "A", "in_run_area": ".."}
            ],
        }
        kept = run_area.INSTRUCTION_NAME
        for name in (kept, kept + "/z", kept + "/a/b"):
            for action in (
                copy(name),
                {"action": "share", "name": name, "source": "/l"},
                {"action": "write", "name": name, "text": ""},
                {"action": "writable", "name": name},
                {"action": "leave_out", "name": name},
                {"action": "variable", "variable": "A", "in_run_area": name},
            ):
                table[f"the kept name or below ({name}, {action['action']})"] = [action]
        for variable in (
            "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS",
            "LD_PRELOAD",
            "LD_",
            "LD_X",
        ):
            table[f"the variable {variable}"] = [
                {"action": "variable", "variable": variable, "value": "x"}
            ]
        table["a variable's path no request makes"] = [
            copy("a"),
            {"action": "variable", "variable": "A", "in_run_area": "b"},
        ]
        table["a variable's path that is a prefix of a name, not a folder above it"] = [
            copy("ab"),
            {"action": "variable", "variable": "A", "in_run_area": "a"},
        ]
        for label, requests in table.items():
            with self.subTest(label):
                got = run_area.plan(AREA, requests)
                self.assertTrue(got["problem"], label)
                self.assertEqual((got["steps"], got["variables"]), ([], {}))

    def test_a_variable_may_name_what_a_request_makes_or_a_folder_above_it(self):
        for name in ("h", "h/inside", "config", "config/generated.toml"):
            with self.subTest(name):
                got = run_area.plan(
                    AREA,
                    [
                        copy("h"),
                        {"action": "write", "name": "config/generated.toml", "text": ""},
                        {"action": "variable", "variable": "A", "in_run_area": name},
                    ],
                )
                self.assertIsNone(got["problem"])

    def test_a_name_below_a_copy_may_be_written_shared_or_made_writable(self):
        got = run_area.plan(
            AREA,
            [
                copy("h"),
                {"action": "share", "name": "h/login", "source": "/l"},
                {"action": "writable", "name": "h/deeper/file"},
            ],
        )
        self.assertIsNone(got["problem"])


def a_state(world):
    return {"world": world.operations, "problems": {}, "stand_ins": {}, "facts": {}}


class TheSteps(unittest.TestCase):
    def setUp(self):
        self.world = simulated.SimulatedWorld()
        self.world.make_folder("/src/history")
        self.world.put_file("/src/settings", "settings text")
        self.world.put_file("/src/history/old", "history")
        self.world.put_file("/src/login", "LOGIN-STAND-IN")
        self.state = a_state(self.world)

    def test_every_action_lands_in_the_run_area_and_nothing_outside_it(self):
        before = dict(self.world.files)
        requests = [
            {"action": "copy", "name": "home", "source": "/src"},
            {"action": "leave_out", "name": "home/history"},
            {"action": "leave_out", "name": "home/login"},
            {"action": "share", "name": "home/login", "source": "/src/login"},
            {"action": "write", "name": "home/generated", "text": "made"},
            {"action": "writable", "name": "home/settings"},
            {"action": "variable", "variable": "HOME_OF_TOOL", "in_run_area": "home"},
        ]
        got = set_up_run_area.set_up(self.state, requests)
        area = self.state["run_area"]
        self.assertEqual(got, {"ok": True})
        self.assertEqual(self.world.text_of(f"{area}/home/settings"), "settings text")
        self.assertEqual(self.world.text_of(f"{area}/home/generated"), "made")
        self.assertEqual(self.world.links[f"{area}/home/login"], "/src/login")
        self.assertNotIn(f"{area}/home/history/old", self.world.files)
        self.assertEqual(self.state["setup_variables"], {"HOME_OF_TOOL": f"{area}/home"})
        outside = {n: d for n, d in self.world.files.items() if not n.startswith(area + "/")}
        self.assertEqual(outside, before)  # nothing outside the area was made, changed or removed
        self.assertEqual(
            [args for args, _ in self.world.calls("files.share_by_link")],
            [("/src/login", f"{area}/home/login")],
        )
        self.assertEqual(self.world.calls("files.read"), [])  # nothing was read, the login least

    def test_the_run_area_is_new_and_the_tear_down_removes_it_whole_and_leaves_the_original(self):
        set_up_run_area.set_up(
            self.state, [{"action": "share", "name": "l", "source": "/src/login"}]
        )
        area = self.state["run_area"]
        self.assertTrue(self.world.operations.files.usable_folder(area))
        self.assertEqual(tear_down.remove(self.state), {"failure": ""})
        self.assertFalse(self.world.operations.files.exists(area))
        self.assertNotIn("run_area", self.state)
        self.assertEqual(self.world.text_of("/src/login"), "LOGIN-STAND-IN")

    def test_a_refused_plan_fails_the_step_with_a_line_before_anything_is_made(self):
        got = set_up_run_area.set_up(self.state, [copy("../x")])
        self.assertEqual(got, {"ok": False})
        self.assertIn("not a name inside the run area", self.state["problems"]["setup"])
        self.assertEqual(self.world.calls("files.make_temporary_folder"), [])
        self.assertNotIn("run_area", self.state)

    def test_a_name_below_the_kept_instruction_name_ends_a_run_as_a_refused_setup_with_no_area(
        self,
    ):
        name = run_area.INSTRUCTION_NAME + "/z"
        got = set_up_run_area.set_up(self.state, [{"action": "write", "name": name, "text": "t"}])
        self.assertEqual(got, {"ok": False})
        self.assertIn("kept for the instruction", self.state["problems"]["setup"])
        self.assertEqual(self.world.calls("files.make_temporary_folder"), [])

    def test_an_action_that_fails_fails_the_step_naming_its_number_and_the_error_only(self):
        self.world.will_raise("files.copy_path", PermissionError("secret detail"))
        got = set_up_run_area.set_up(self.state, [copy("h", "/src"), copy("i", "/src")])
        self.assertEqual(got, {"ok": False})
        line = self.state["problems"]["setup"]
        self.assertIn("setup step 1 (copy) failed (PermissionError)", line)
        self.assertNotIn("secret detail", line)

    def test_a_source_that_is_not_there_fails_the_step(self):
        self.assertEqual(
            set_up_run_area.set_up(self.state, [copy("h", "/src/absent")]), {"ok": False}
        )
        self.assertEqual(
            set_up_run_area.set_up(a_state(self.world), [
                {"action": "share", "name": "l", "source": "/src/absent"}]),
            {"ok": False},
        )  # fmt: skip

    def test_a_tear_down_that_fails_says_so_by_the_error_and_the_area_is_not_tried_again(self):
        set_up_run_area.set_up(self.state, [])
        self.world.will_raise("files.remove_tree", PermissionError("detail"))
        got = tear_down.remove(self.state)
        self.assertEqual(got, {"failure": "the run area could not be removed (PermissionError)"})
        self.assertEqual(tear_down.remove(self.state), {"failure": ""})  # nothing left to try

    def test_a_tear_down_with_no_run_area_has_nothing_to_remove(self):
        self.assertEqual(tear_down.remove(self.state), {"failure": ""})
        self.assertEqual(self.world.calls("files.remove_tree"), [])


class TheAreaThroughARun(unittest.TestCase):
    def areas(self, world):
        return [n for n in world.folders if n.startswith("/tmp/" + run_area.AREA_PREFIX)]

    def receipt(self, world):
        return flat(scenes.outcome(world)["receipt"])

    def test_a_good_run_makes_the_area_and_removes_it_at_the_end(self):
        world = scenes.scene()
        code, _, err = scenes.run_in(world)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(world.calls("files.make_temporary_folder")), 1)
        self.assertEqual(self.areas(world), [])
        receipt = self.receipt(world)
        self.assertEqual(receipt["ending"]["ending"], "ended_by_itself")
        self.assertEqual(receipt["execution"]["teardown_failure"], "none")

    def test_an_area_is_removed_after_a_time_limit_and_after_a_stop_that_is_not_confirmed(self):
        for program in ({"times_out": True}, {"survives_stop": True}):
            with self.subTest(program):
                world = scenes.scene(**program)
                code, _, err = scenes.run_in(world)
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(self.areas(world), [])

    def test_an_area_is_removed_when_a_later_step_fails_before_the_launch(self):
        world = scenes.scene()
        world.will_raise("processes.start", OSError("injected"))
        scenes.run_in(world)
        self.assertEqual(self.receipt(world)["ending"]["failed_step"], "launch")
        self.assertEqual(self.areas(world), [])

    def test_an_area_is_removed_when_the_set_up_failed_part_way(self):
        world = scenes.scene()
        world.will_raise("files.make_temporary_folder", OSError("injected"))
        scenes.run_in(world)
        ending = self.receipt(world)["ending"]
        self.assertEqual((ending["reason"], ending["failed_step"]), ("setup_failed", "setup"))

    def test_a_run_refused_before_the_set_up_makes_no_area(self):
        world = scenes.scene(scenes.document(command="absent"))
        scenes.run_in(world)
        self.assertEqual(world.calls("files.make_temporary_folder"), [])

    def test_a_tear_down_that_fails_is_in_the_receipt_and_changes_no_ending(self):
        world = scenes.scene()
        world.will_raise("files.remove_tree", OSError("injected"))
        scenes.run_in(world)
        receipt = self.receipt(world)
        self.assertEqual(receipt["ending"]["ending"], "ended_by_itself")
        self.assertEqual(
            receipt["execution"]["teardown_failure"],
            "the run area could not be removed (OSError)",
        )

    def test_a_signal_before_the_launch_still_removes_the_area(self):
        world = scenes.scene()
        world.on_call("files.make_temporary_folder", lambda: world.deliver("SIGINT"))
        scenes.run_in(world)
        self.assertEqual(self.areas(world), [])


if __name__ == "__main__":
    unittest.main()
