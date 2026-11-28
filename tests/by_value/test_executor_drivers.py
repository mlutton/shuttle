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
import types
import typing
import unittest

from shuttle.core import decisions, run_area
from shuttle.core.drivers import command, table
from shuttle.core.shapes import SetupAction
from shuttle.shell import check_form

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

SAVED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_output")
PROGRAM = "co" + "dex"
AREA = "/tmp/shuttle-run-area-" + f"{1:032x}"  # the first run's area: named for its run part
LOGIN = "/h/.codex/auth.json"
LOCATION = "/out/statement.json"
INSTRUCTION = "Do the task."


def saved(name):
    with open(os.path.join(SAVED, name), encoding="utf-8") as f:
        return f.read()


def document(changes_to_place="allowed", **extra):
    return scenes.document(
        executor={"name": PROGRAM, "settings": {"model": "example-model", "effort": "low"}},
        network="off",
        changes_to_place=changes_to_place,
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


class WhetherTheReplyBecomesTheStatement(unittest.TestCase):
    def test_only_a_reply_driver_that_gave_one_and_a_free_location_has_it_copied(self):
        for arrives, expects, taken, given, expected in (
            ("reply", True, False, True, True),
            ("reply", True, True, True, False),  # the executor already left one
            ("reply", True, False, False, False),  # no final message
            ("reply", False, False, True, False),  # the kind expects no statement
            ("file", True, False, True, False),  # the tool writes its own file
        ):
            with self.subTest(arrives=arrives, expects=expects, taken=taken, given=given):
                self.assertEqual(
                    decisions.copy_reply_to_statement(arrives, expects, taken, given), expected
                )


class EveryNameHasItsEntry(unittest.TestCase):
    """The type checker does not catch a name with no table entry; these do."""

    def test_the_setup_actions_table_has_an_entry_for_each_member_of_the_type_and_no_other(self):
        self.assertEqual(set(run_area.ACTIONS), set(typing.get_args(SetupAction)))

    def test_the_drivers_table_has_an_entry_for_each_driver_module_and_no_other(self):
        folder = os.path.join(
            os.path.dirname(os.path.dirname(SAVED)), "..", "shuttle", "core", "drivers"
        )
        modules = {
            name[:-3]
            for name in os.listdir(folder)
            if name.endswith(".py") and name not in ("__init__.py", "interface.py", "table.py")
        }
        self.assertEqual(set(table.DRIVERS), modules)
        for name, driver in table.DRIVERS.items():
            self.assertEqual(driver.__name__.rpartition(".")[2], name)


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


class TheCommandDriverRefusesWhatTheBoxDoesNotEnforce(unittest.TestCase):
    def verdict(self, **standard):
        world = scenes.scene(scenes.document(**standard))
        out, err = io.StringIO(), io.StringIO()
        check_form.check(scenes.DOCUMENT, out, err, world.operations)
        scenes.run_in(world)
        return out.getvalue(), flat(scenes.outcome(world)["receipt"])["ending"], world

    def test_network_off_is_refused_by_the_check_and_the_run_with_the_same_reason(self):
        checked, ending, world = self.verdict(network="off")
        self.assertIn("unknown_setting", checked)
        self.assertIn("cannot enforce network off", checked)
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "unknown_setting", "executor_driver_check"),
        )
        self.assertEqual(world.started, [])

    def test_changes_to_the_place_not_allowed_is_accepted_by_the_check_and_the_run(self):
        checked, ending, world = self.verdict(changes_to_place="not")
        self.assertNotIn("executor_driver_check", checked)
        self.assertIn("check: no refusal found", checked)
        self.assertEqual(ending["ending"], "ended_by_itself")
        self.assertEqual(len(world.started), 1)  # the box, not the driver, holds the place

    def test_no_restriction_asked_for_changes_nothing(self):
        for label, standard in (
            ("neither named", {}),
            ("network on", {"network": "on"}),
            ("changes allowed", {"changes_to_place": "allowed"}),
            ("both permissions", {"network": "on", "changes_to_place": "allowed"}),
        ):
            with self.subTest(label):
                checked, ending, _ = self.verdict(**standard)
                self.assertNotIn("executor_driver_check", checked)
                self.assertEqual(ending["ending"], "ended_by_itself")


class ARunNamingTheCodexDriver(unittest.TestCase):
    def test_the_box_makes_the_place_read_only_when_changes_are_not_allowed_and_codex_keeps_its_own(
        self,
    ):
        for setting, sandbox, kind in (
            ("not", "read-only", "--ro-bind"),
            ("allowed", "workspace-write", "--bind"),
        ):
            with self.subTest(setting):
                world = world_for(
                    "events-finished.jsonl",
                    "last-message-statement.json",
                    document(changes_to_place=setting),
                )
                self.run_it(world)
                argv, _ = world.started[-1]
                at = argv.index("-s")
                self.assertEqual(argv[at + 1], sandbox)
                place = [
                    argv[i : i + 3]
                    for i, p in enumerate(argv)
                    if p in (kind, "--bind", "--ro-bind")
                ]
                self.assertEqual([p[0] for p in place if p[2] == scenes.PLACE], [kind])

    def run_it(self, world):
        code, lines, err = scenes.run_in(world)
        self.assertEqual((code, err), (0, ""))
        return flat(scenes.outcome(world)["receipt"])

    def test_a_tool_the_box_could_not_start_ends_as_could_not_start_like_the_command_driver_does(
        self,
    ):
        world = world_for("events-finished.jsonl", "last-message-statement.json")
        world.program(PROGRAM, cannot_exec=True)
        receipt = self.run_it(world)
        ending = receipt["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "program_not_started", "launch"),
        )
        self.assertIn(repr(PROGRAM), ending["reason_text"])
        self.assertEqual(receipt["execution"]["exit_code"], "none")

    def test_a_memory_cap_takes_the_same_path_for_this_driver_as_for_the_command_driver(self):
        cap = 64 * 1024 * 1024
        world = world_for(
            "events-finished.jsonl", "last-message-statement.json", document(memory_limit_bytes=cap)
        )
        world.program(PROGRAM, oom_kills=True)
        receipt = self.run_it(world)
        argv, _ = world.started[-1]
        self.assertIn(f"MemoryMax={cap}", argv)
        self.assertIn("MemorySwapMax=0", argv)
        self.assertEqual(
            (receipt["ending"]["ending"], receipt["ending"]["reason"]),
            ("memory_limit", "memory_limit"),
        )
        self.assertEqual(world.units, {})

    def test_a_memory_cap_on_a_machine_that_cannot_hold_it_is_refused_for_this_driver_too(self):
        world = world_for(
            "events-finished.jsonl",
            "last-message-statement.json",
            document(memory_limit_bytes=64 * 1024 * 1024),
        )
        world.memory_cap = "ignored"
        out, err = io.StringIO(), io.StringIO()
        check_form.check(scenes.DOCUMENT, out, err, world.operations)
        self.assertIn("check: refused: memory_cap_unavailable", out.getvalue())
        receipt = self.run_it(world)
        self.assertEqual(
            (receipt["ending"]["reason"], receipt["ending"]["failed_step"]),
            ("memory_cap_unavailable", "input_check"),
        )
        self.assertEqual(world.started, [])  # the tool was never started

    def test_the_instruction_reaches_it_on_standard_input_and_never_on_the_command_line(self):
        world = world_for("events-finished.jsonl", "last-message-statement.json")
        self.run_it(world)
        argv, _ = world.started[-1]
        self.assertFalse(any(INSTRUCTION in part for part in argv))
        self.assertIn(PROGRAM, argv)
        self.assertIn(INSTRUCTION, world.children[-1].input.decode())

    def test_the_notice_asks_a_reply_driver_for_its_final_message_and_a_command_for_a_file(self):
        world = world_for("events-finished.jsonl", "last-message-statement.json")
        self.run_it(world)
        replied = world.children[-1].input.decode()
        self.assertIn("as your final message", replied)
        self.assertNotIn(LOCATION, replied)
        other = scenes.scene(scenes.document(kind="judge", statement_location=LOCATION))
        other.make_folder("/out")
        scenes.run_in(other)
        filed = other.children[-1].input.decode()
        self.assertIn(
            f"Write your statement as one JSON file at this exact path: {AREA}/shuttle-statement.json",
            filed,
        )
        self.assertNotIn(LOCATION, filed)

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

    def test_its_tool_home_is_in_the_executors_home_in_the_run_area_and_the_login_is_copied_in(
        self,
    ):
        world = world_for("events-finished.jsonl", "last-message-statement.json")
        self.run_it(world)
        _, environment = world.started[-1]
        self.assertEqual(environment["CODEX_HOME"], f"{AREA}/home/.codex")
        for variable in ("TMPDIR", "XDG_CACHE_HOME"):  # the box gives it its own `/tmp` and home
            self.assertNotIn(variable, environment)
        for operation in ("files.read", "files.hash", "files.copy", "files.link"):
            touched = [args for args, _ in world.calls(operation)]
            self.assertFalse(any(LOGIN in args for args in touched), operation)
        self.assertEqual(
            [args for args, _ in world.calls("files.copy_path")],
            [
                ("/h/.codex/config.toml", f"{AREA}/home/.codex/config.toml", ()),
                (LOGIN, f"{AREA}/home/.codex/auth.json", ()),
            ],
        )
        self.assertEqual(world.links, {})

    def test_its_event_stream_final_message_and_errors_are_kept_whole_and_the_receipt_says_where(
        self,
    ):
        world = world_for("events-finished.jsonl", "last-message-done.txt")
        world.programs[PROGRAM]["error"] = "a warning\n"
        receipt = self.run_it(world)
        kept = {
            "standard_output_kept": ("standard-output", saved("events-finished.jsonl")),
            "final_message_kept": ("final-message", saved("last-message-done.txt")),
            "standard_error_kept": ("standard-error", "a warning\n"),
        }
        for field, (what, text) in kept.items():
            where = f"/records/inj-1.{what}.kept"
            self.assertEqual(world.text_of(where), text, field)
            self.assertEqual(
                receipt["execution"][field],
                {"kept_at": where, "hash": hashlib.sha256(text.encode()).hexdigest()},
                field,
            )

    def test_a_final_message_that_is_also_the_statement_is_kept_whole_as_the_message_too(self):
        world = world_for("events-finished.jsonl", "last-message-statement.json")
        receipt = self.run_it(world)
        text = saved("last-message-statement.json")
        self.assertEqual(world.text_of("/records/inj-1.final-message.kept"), text)
        self.assertEqual(world.text_of("/records/inj-1.statement.kept"), text)
        self.assertEqual(
            receipt["execution"]["final_message_kept"]["hash"],
            hashlib.sha256(text.encode()).hexdigest(),
        )

    def test_a_tool_that_left_no_final_message_reads_none_for_it_and_the_rest_are_kept(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt")
        world.programs[PROGRAM]["writes"] = {}
        receipt = self.run_it(world)
        self.assertEqual(receipt["execution"]["final_message_kept"], "none")
        self.assertEqual(
            world.text_of("/records/inj-1.standard-output.kept"), saved("events-finished.jsonl")
        )

    def test_the_area_is_removed_whole_afterwards(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt")
        self.run_it(world)
        self.assertFalse(any(n.startswith(AREA) for n in world.files))
        self.assertEqual(world.text_of(LOGIN), "NOT-A-LOGIN-just-a-stand-in\n")


class TheCheckAndTheRunAgreeOnWhatTheSetupNeeds(unittest.TestCase):
    def a_command_driver_that_asks_for(self, requests):
        """The command driver with a setup of its own, in the table for the length of a test."""
        driver = types.SimpleNamespace(**vars(command))
        driver.setup_requests = lambda settings, environment: requests
        held = table.DRIVERS["command"]
        table.DRIVERS["command"] = driver
        self.addCleanup(table.DRIVERS.__setitem__, "command", held)

    def verdicts(self, world):
        out, err = io.StringIO(), io.StringIO()
        check_form.check(scenes.DOCUMENT, out, err, world.operations)
        checked = out.getvalue()
        code, _, _ = scenes.run_in(world)
        return checked, flat(scenes.outcome(world)["receipt"])["ending"], code

    def test_a_source_the_setup_needs_that_is_not_there_is_refused_by_both_with_the_same_reason(
        self,
    ):
        self.a_command_driver_that_asks_for(
            [{"action": "copy", "name": "home/settings", "source": "/absent/settings"}]
        )
        checked, ending, _ = self.verdicts(scenes.scene())
        self.assertIn("setup_failed", checked)
        self.assertIn("/absent/settings", checked)
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "setup_failed", "setup"),
        )

    def test_a_login_that_is_a_link_to_a_file_is_copied_as_the_file_by_both(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt", login=False)
        world.put_file("/elsewhere/login", "NOT-A-LOGIN-kept-elsewhere\n")
        world.put_link(LOGIN, "/elsewhere/login")
        checked, ending, _ = self.verdicts(world)
        self.assertNotIn("setup_failed", checked)
        self.assertEqual(ending["ending"], "ended_by_itself")
        copied = [
            args for args, _ in world.calls("files.copy_path") if args[1].endswith("auth.json")
        ]
        self.assertEqual([c[0] for c in copied], ["/elsewhere/login"])  # the file it leads to

    def test_a_login_that_is_a_link_to_nothing_is_refused_by_both_with_a_line_that_names_it(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt", login=False)
        world.put_link(LOGIN, "/elsewhere/absent")
        checked, ending, _ = self.verdicts(world)
        self.assertIn("setup_failed", checked)
        self.assertEqual((ending["reason"], ending["failed_step"]), ("setup_failed", "setup"))

    def test_a_copy_that_fails_names_its_source_and_what_to_do(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt")
        world.will_raise("files.copy_path", PermissionError("detail"), nth=2)
        checked, ending, _ = self.verdicts(world)
        line = ending["reason_text"]
        self.assertIn(repr(LOGIN), line)
        self.assertIn("regular file", line)
        self.assertNotIn("detail", line)

    def test_a_source_that_is_there_passes_both(self):
        self.a_command_driver_that_asks_for(
            [
                {"action": "copy", "name": "settings", "source": "/there"},
                {"action": "copy", "name": "login", "source": "/there"},
            ]
        )
        world = scenes.scene()
        world.put_file("/there", "text")
        checked, ending, _ = self.verdicts(world)
        self.assertNotIn("setup_failed", checked)
        self.assertEqual(ending["ending"], "ended_by_itself")

    def test_an_optional_copy_whose_source_is_not_there_is_left_out_by_both(self):
        self.a_command_driver_that_asks_for(
            [{"action": "copy", "name": "settings", "source": "/absent", "optional": True}]
        )
        world = scenes.scene()
        checked, ending, _ = self.verdicts(world)
        self.assertNotIn("setup_failed", checked)
        self.assertEqual(ending["ending"], "ended_by_itself")
        self.assertEqual(world.calls("files.copy_path"), [])

    def test_only_a_copy_may_be_optional_and_only_with_true_or_false(self):
        copy = {"action": "copy", "name": "a", "source": "/s"}
        self.assertIsNone(run_area.refusal([{**copy, "optional": True}]))
        self.assertIn("optional", run_area.refusal([{**copy, "optional": "yes"}]))
        self.assertEqual(run_area.required_sources([{**copy, "optional": True}]), [])
        self.assertEqual(run_area.required_sources([copy]), ["/s"])

    def test_a_tool_home_with_a_login_and_no_settings_file_passes_the_check_and_the_run(self):
        world = world_for("events-finished.jsonl", "last-message-done.txt")
        world.files.pop("/h/.codex/config.toml")
        checked, ending, _ = self.verdicts(world)
        self.assertNotIn("setup_failed", checked)
        self.assertEqual(ending["ending"], "ended_by_itself")
        copied = [args[0] for args, _ in world.calls("files.copy_path")]
        self.assertEqual(copied, [LOGIN])  # the settings file was not asked for
        self.assertEqual(len(world.calls("files.copy_path")), 1)  # the login still is copied


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
