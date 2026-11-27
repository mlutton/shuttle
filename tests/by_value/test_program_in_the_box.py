"""By value: whether the box shows the program the caller's machine found.

The decision is `boundary.hidden_program`, over the facts the shell gathers (where the program was
found, the file that leads to, the paths the box shows). The same facts reach every driver's run
through `decisions.executor_driver_check`; the simulated world carries a command driver run and a
check of a stand-in for the Codex driver's tool, and no test starts a tool.
"""

import importlib
import io
import os
import sys
import unittest

from shuttle.core import boundary, decisions, fixed
from shuttle.shell import check_form

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")

SHOWN: boundary.Shown = {
    "place": "/work/place",
    "references": ["/refs/runbook"],
    "visible": ["/opt/tool"],
    "git_folders": ["/repos/main/.git"],
    "resolver": None,
}


def facts(found_at, resolves_to=None, shown=SHOWN):
    return {"found_at": found_at, "resolves_to": resolves_to or found_at, "shown": shown}


class WhereTheProgramIs(unittest.TestCase):
    def test_a_program_the_box_shows_is_accepted(self):
        for name, path in {
            "a system folder": "/usr/bin/tool",
            "a system link folder": "/bin/tool",
            "the etc folder": "/etc/alternatives/tool",
            "the place": "/work/place/bin/tool",
            "a reference that is the program": "/refs/runbook",
            "a visible folder": "/opt/tool/bin/tool",
            "a git folder": "/repos/main/.git/hooks/tool",
        }.items():
            with self.subTest(name):
                self.assertIsNone(boundary.hidden_program(facts(path)))

    def test_a_program_in_a_hidden_folder_is_refused_naming_the_folder_and_reach_visible(self):
        for path, folder in {
            "/home/someone/.local/bin/tool": "/home/someone/.local/bin",
            "/opt/other/tool": "/opt/other",
            "/opt/tool-two/tool": "/opt/tool-two",  # starts like a visible folder, is not in it
            "/work/place-two/tool": "/work/place-two",
            "/tmp/fresh/tool": "/tmp/fresh",
            "/tool": "/",
        }.items():
            with self.subTest(path):
                reason, line = boundary.hidden_program(facts(path))
                self.assertEqual(reason, "program_not_visible")
                self.assertIn(repr(folder), line)
                self.assertIn(repr(path), line)
                self.assertIn("reach.visible", line)

    def test_a_link_in_a_shown_folder_to_a_file_in_a_hidden_one_names_the_folder_of_the_file(self):
        reason, line = boundary.hidden_program(facts("/usr/bin/tool", "/opt/other/bin/real"))
        self.assertEqual(reason, "program_not_visible")
        self.assertIn(repr("/opt/other/bin"), line)
        self.assertNotIn(repr("/usr/bin"), line)
        self.assertIn("link", line)
        self.assertIn("reach.visible", line)

    def test_a_link_in_a_hidden_folder_is_refused_even_when_it_leads_to_a_shown_file(self):
        reason, line = boundary.hidden_program(facts("/home/someone/bin/tool", "/usr/bin/real"))
        self.assertEqual(reason, "program_not_visible")
        self.assertIn(repr("/home/someone/bin"), line)

    def test_a_link_between_two_shown_places_is_accepted(self):
        self.assertIsNone(boundary.hidden_program(facts("/usr/bin/tool", "/opt/tool/real")))

    def test_a_program_that_was_not_found_is_not_this_checks_to_refuse(self):
        nothing = {"found_at": None, "resolves_to": None, "shown": SHOWN}
        self.assertIsNone(boundary.hidden_program(nothing))
        self.assertIsNone(boundary.hidden_program(facts("/opt/other/tool", shown=None)))

    def test_the_reason_is_fixed_and_belongs_to_the_driver_check_step(self):
        self.assertIn("program_not_visible", fixed.REASONS_BY_ENDING["could_not_start"])
        self.assertEqual(fixed.STEPS_FOR_REASON["program_not_visible"], ("executor_driver_check",))

    def test_a_resolver_file_is_shown_only_where_the_box_binds_it(self):
        elsewhere = {**SHOWN, "resolver": "/run/systemd/resolve/stub-resolv.conf"}
        self.assertIsNone(boundary.hidden_program(facts(elsewhere["resolver"], shown=elsewhere)))
        self.assertIsNotNone(boundary.hidden_program(facts("/run/other/tool", shown=elsewhere)))


class TheSameAnswerAsTheBoxsArguments(unittest.TestCase):
    """What the decision says is shown is what `box_arguments` binds, so they cannot drift."""

    def test_the_shown_paths_are_the_binds_but_the_run_area_and_the_executors_own_tmp(self):
        for resolver in (None, "/run/systemd/resolve/stub-resolv.conf", "/etc/r", "/tmp/r"):
            for writable in (True, False):
                with self.subTest(resolver=resolver, place_writable=writable):
                    reach: boundary.Reach = {
                        **SHOWN,
                        "resolver": resolver,
                        "area": "/scratch/area",
                        "home": "/scratch/area/home",
                        "tmp": "/scratch/area/tmp",
                        "place_writable": writable,
                        "records": "/records",
                    }
                    argv = boundary.box_arguments(reach)
                    bound = {
                        argv[at + 2]
                        for at, part in enumerate(argv)
                        if part in ("--ro-bind", "--bind", "--ro-bind-try")
                    }
                    self.assertEqual(
                        bound - {"/scratch/area", "/tmp"}, set(boundary.shown_paths(reach))
                    )


class ForEveryDriver(unittest.TestCase):
    """The decision sits in the driver-agnostic check, so a driver need not name it."""

    COMMAND = {"name": "command", "settings": {"command": "tool", "arguments": []}}
    CODEX_TOOL = {"name": "codex", "settings": {"model": "example-model", "effort": "low"}}
    FOUND = {"tool_found": True, "login_found": True, "network": None, "changes_allowed": True}

    def decide(self, executor, program, found=None):
        # the Codex driver wants both standard settings; the command driver refuses network off
        found = {**(found or self.FOUND), "network": False if executor is self.CODEX_TOOL else None}
        return decisions.executor_driver_check(executor, [], {"PATH": "/bin"}, found, program)

    def test_each_driver_refuses_a_program_in_a_hidden_folder_and_accepts_a_shown_one(self):
        for executor in (self.COMMAND, self.CODEX_TOOL):
            with self.subTest(executor["name"]):
                reason, line = self.decide(executor, facts("/home/someone/bin/tool"))
                self.assertEqual(reason, "program_not_visible")
                self.assertIn("'/home/someone/bin'", line)
                self.assertEqual(self.decide(executor, facts("/usr/bin/tool")), (None, None))
                listed = {**SHOWN, "visible": ["/home/someone/bin"]}
                self.assertEqual(
                    self.decide(executor, facts("/home/someone/bin/tool", shown=listed)),
                    (None, None),
                )

    def test_a_program_not_found_is_still_not_installed_for_each_driver(self):
        nothing = {"found_at": None, "resolves_to": None, "shown": None}
        for executor in (self.COMMAND, self.CODEX_TOOL):
            with self.subTest(executor["name"]):
                found = {**self.FOUND, "tool_found": False}
                self.assertEqual(self.decide(executor, nothing, found)[0], "tool_not_installed")


class TheCheckFormOnTheSimulatedWorld(unittest.TestCase):
    def check(self, world):
        out, err = io.StringIO(), io.StringIO()
        code = check_form.check(scenes.DOCUMENT, out, err, world.operations)
        return code, "\n".join(out.getvalue().splitlines())

    def scene(self, command, **extra):
        return scenes.scene(scenes.document(command=command, **extra))

    def test_a_command_named_by_a_path_in_a_hidden_folder_is_refused_and_a_listing_accepts_it(self):
        world = self.scene("/opt/hidden/bin/tool")
        world.program("/opt/hidden/bin/tool")
        _, text = self.check(world)
        self.assertIn("program_not_visible", text)
        self.assertIn("'/opt/hidden/bin'", text)
        world = self.scene("/opt/hidden/bin/tool", reach={"visible": ["/opt/hidden/bin"]})
        world.program("/opt/hidden/bin/tool")
        world.make_folder("/opt/hidden/bin")
        code, text = self.check(world)
        self.assertEqual(code, 0, text)

    def test_a_command_in_the_place_or_a_reference_or_a_system_folder_is_accepted(self):
        for command in ("/place/tool", "/usr/bin/tool", "/refs/runbook/tool"):
            with self.subTest(command):
                world = self.scene(command)
                world.program(command)
                world.make_folder("/refs/runbook")
                code, text = self.check(world)
                self.assertEqual(code, 0, text)

    def test_a_link_in_a_system_folder_to_a_hidden_file_names_the_folder_the_file_is_in(self):
        world = self.scene("tool")
        world.links["/usr/bin/tool"] = "/opt/real/tool"
        _, text = self.check(world)
        self.assertIn("program_not_visible", text)
        self.assertIn("'/opt/real'", text)


if __name__ == "__main__":
    unittest.main()
