"""By value, on the simulated world: a document names an executor driver and the run, the check
form and the table follow it. The program that stands in for the tool is a registered name in the
simulated world; nothing here starts a process, opens a login or runs the real tool.

The saved output the stand-in leaves is hand-made (tests/by_value/saved_output/), in the shape of
what the tool writes, with made-up identifiers and counts.
"""

import hashlib
import importlib
import io
import os
import sys
import unittest

from shuttle.core.drivers import command, table
from shuttle.shell import check_form

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

SAVED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_output")
PROGRAM = "co" + "dex"
AREA = "/tmp/shuttle-run-area-000001"  # the first run area the simulated world makes
LOGIN = "/h/.codex/auth.json"
LOCATION = "/out/statement.json"
INSTRUCTION = "Do the task."


def saved(name):
    with open(os.path.join(SAVED, name), encoding="utf-8") as f:
        return f.read()


def document(**extra):
    return scenes.document(
        executor={"name": PROGRAM, "settings": {"model": "example-model", "effort": "low"}},
        network="off",
        changes_to_place="allowed",
        kind="judge",
        instruction=INSTRUCTION,
        statement_location=LOCATION,
        **{"instruction_hash": hashlib.sha256(INSTRUCTION.encode()).hexdigest(), **extra},
    )


def world_for(events, last_message, doc=None, login=True, tool=True):
    world = scenes.scene(doc or document())
    world.variables.update({"HOME": "/h", "PATH": "/bin"})
    world.make_folder("/out")
    world.make_folder("/h/.codex")
    world.put_file("/h/.codex/config.toml", "made-up settings\n")
    if login:
        world.put_file(LOGIN, "NOT-A-LOGIN-just-a-stand-in\n")
    if tool:
        world.program(
            PROGRAM,
            output=saved(events),
            writes={f"{AREA}/out/last-message.txt": saved(last_message)},
        )
    return world


class TheTable(unittest.TestCase):
    def test_each_driver_is_found_by_its_own_name(self):
        for name, driver in table.DRIVERS.items():
            self.assertEqual(driver.NAME, name)
        self.assertIs(table.DRIVERS["command"], command)

    def test_the_command_driver_fits_the_same_interface_and_gives_no_statement(self):
        facts = {"tool_found": True, "login_found": False, "network": None, "changes_allowed": None}
        settings = {"command": "tool", "arguments": ["a"]}
        self.assertIsNone(command.settings_refusal(settings))
        self.assertIsNone(command.check(settings, facts))
        self.assertEqual(
            command.check(settings, {**facts, "tool_found": False})[0], "tool_not_installed"
        )
        self.assertIsNone(command.login_path({"HOME": "/h"}))
        self.assertEqual(command.setup_requests(settings, {}), [])
        self.assertEqual(command.launch(settings, {})["argv"], ["tool", "a"])
        nothing = {"events": None, "last_message": None, "session_record": None}
        self.assertFalse(command.observe(settings, nothing)["reply_given"])


def sources_outside_the_drivers():
    root = os.path.join(os.path.dirname(os.path.dirname(SAVED)), "..", "shuttle")
    for where, folders, names in os.walk(root):
        folders[:] = [f for f in folders if f != "__pycache__"]
        if os.path.basename(where) != "drivers":
            yield from (os.path.join(where, n) for n in names if n.endswith(".py"))


class NothingOutsideTheTableNamesADriver(unittest.TestCase):
    def test_no_module_outside_the_drivers_folder_imports_one_by_name_or_holds_its_name(self):
        found = []
        for path in sources_outside_the_drivers():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            found += [
                f"{os.path.basename(path)}: {held}"
                for held in (PROGRAM, "drivers.command", "drivers import command", "import command")
                if held in text
            ]
        self.assertEqual(found, [])


class ARunNamingTheCodexDriver(unittest.TestCase):
    def run_it(self, world):
        code, lines, err = scenes.run_in(world)
        self.assertEqual((code, err), (0, ""))
        return flat(scenes.outcome(world)["receipt"])

    def test_the_instruction_reaches_it_on_standard_input_and_never_on_the_command_line(self):
        world = world_for("events-finished.jsonl", "last-message-statement.json")
        self.run_it(world)
        argv, _ = world.started[-1]
        self.assertFalse(any(INSTRUCTION in part for part in argv))
        self.assertIn(PROGRAM, argv)
        self.assertIn(INSTRUCTION, world.children[-1].input.decode())

    def test_a_statement_it_gives_as_its_last_message_is_kept_like_any_other(self):
        receipt = self.run_it(world_for("events-finished.jsonl", "last-message-statement.json"))
        self.assertEqual(receipt["ending"]["ending"], "ended_by_itself")
        self.assertEqual(receipt["executor"]["statement_state"], "right_shape")
        self.assertEqual(receipt["executor"]["claim"], "done")

    def test_a_question_as_the_last_message_is_a_wrong_shape_statement_and_ended_by_itself(self):
        receipt = self.run_it(
            world_for("events-asked-a-question.jsonl", "last-message-question.txt")
        )
        self.assertEqual(receipt["ending"]["ending"], "ended_by_itself")
        self.assertEqual(receipt["executor"]["statement_state"], "wrong_shape")
        self.assertEqual(
            receipt["executor_driver"]["waiting_question"], saved("last-message-question.txt")
        )

    def test_the_receipts_driver_group_is_filled_from_what_it_observed(self):
        group = self.run_it(world_for("events-finished.jsonl", "last-message-done.txt"))[
            "executor_driver"
        ]
        self.assertEqual(group["executor_driver_name"], PROGRAM)
        self.assertEqual(
            (group["tokens_in"], group["tokens_out"], group["tokens_cached"], group["session_id"]),
            (120, 9, 40, "thread-0001"),
        )
        self.assertEqual(
            group["tool_version"], "cannot tell"
        )  # the session record is not found yet

    def test_its_tool_home_is_made_in_the_run_area_and_the_login_is_only_linked(self):
        world = world_for("events-finished.jsonl", "last-message-statement.json")
        self.run_it(world)
        _, environment = world.started[-1]
        self.assertEqual(environment["CODEX_HOME"], f"{AREA}/home")
        self.assertEqual(environment["TMPDIR"], f"{AREA}/tmp")
        self.assertEqual(
            [args for args, _ in world.calls("files.share_by_link")],
            [(LOGIN, f"{AREA}/home/auth.json")],
        )
        for operation in ("files.read", "files.hash", "files.copy", "files.copy_path"):
            touched = [args for args, _ in world.calls(operation)]
            self.assertFalse(any(LOGIN in args for args in touched), operation)
        self.assertEqual(
            [args for args, _ in world.calls("files.copy_path")],
            [("/h/.codex/config.toml", f"{AREA}/home/config.toml", ())],
        )

    def test_the_area_is_removed_whole_afterwards(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt")
        self.run_it(world)
        self.assertFalse(any(n.startswith(AREA) for n in world.files))
        self.assertEqual(world.text_of(LOGIN), "NOT-A-LOGIN-just-a-stand-in\n")


class TheCheckFormWithTheCodexDriver(unittest.TestCase):
    def check(self, world):
        out, err = io.StringIO(), io.StringIO()
        code = check_form.check(scenes.DOCUMENT, out, err, world.operations)
        return code, "\n".join(out.getvalue().splitlines())

    def test_a_tool_and_a_login_that_are_there_pass_and_nothing_is_started(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt")
        code, text = self.check(world)
        self.assertEqual(code, 0)
        self.assertNotIn("executor_driver_check", text)
        self.assertEqual(world.started, [])

    def test_a_missing_login_is_refused_without_the_login_being_opened(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt", login=False)
        _, text = self.check(world)
        self.assertIn("no_login", text)
        self.assertFalse(any(LOGIN in args for args, _ in world.calls("files.read")))

    def test_a_missing_tool_is_refused(self):
        _, text = self.check(
            world_for("events-finished.jsonl", "last-message-done.txt", tool=False)
        )
        self.assertIn("tool_not_installed", text)

    def test_a_document_with_no_standard_settings_is_refused_by_the_check(self):
        doc = document()
        del doc["network"]
        _, text = self.check(world_for("events-finished.jsonl", "last-message-done.txt", doc))
        self.assertIn("missing_setting", text)


if __name__ == "__main__":
    unittest.main()
