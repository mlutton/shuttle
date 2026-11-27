"""By value: the Codex driver's decisions, with no tool and no login.

Nothing here starts a process or reads a login: the driver is handed facts and gives answers. The
saved output it reads (tests/by_value/saved_output/) is hand-made, small, with made-up identifiers
and counts, in the shape of what the tool writes; none of it is copied from a real run. The tool's
program name appears as data, which the rule test allows for a file that cannot start a process.
"""

import json
import os
import unittest

from shuttle.core import decisions, fixed, run_area, statement
from shuttle.core.drivers import codex
from shuttle.core.shapes import Facts

SAVED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_output")
PROGRAM = "co" + "dex"  # as the rule test writes it
SETTINGS = {"model": "example-model", "effort": "low"}
FOUND = {"tool_found": True, "login_found": True, "network": False, "changes_allowed": True}
AREA = "/area"


def saved_text(name):
    with open(os.path.join(SAVED, name), encoding="utf-8") as f:
        return f.read()


def shipped_schema():
    path = os.path.join(os.path.dirname(os.path.dirname(SAVED)), "..", "shuttle", "data")
    with open(os.path.join(path, "statement_schema.json"), encoding="utf-8") as f:
        return f.read()


def saved(events=None, last_message=None, record=None):
    return {
        "events": None if events is None else saved_text(events),
        "last_message": None if last_message is None else saved_text(last_message),
        "session_record": None if record is None else saved_text(record),
    }


def context(**extra):
    return {"place": "/place", "run_area": AREA, "network": False, "changes_allowed": True, **extra}


def state_of(pair):
    return (pair["state"], pair["value"])


class TheCheck(unittest.TestCase):
    def test_what_it_refuses_and_why(self):
        cases = {
            "an absent model": ({}, FOUND, "missing_setting"),
            "a model that is not text": ({"model": 3}, FOUND, "missing_setting"),
            "a model with a space": ({"model": "a b"}, FOUND, "missing_setting"),
            "an unknown setting": ({**SETTINGS, "colour": "red"}, FOUND, "unknown_setting"),
            "an effort that is not a word": (
                {"model": "m", "effort": 'low"x'},
                FOUND,
                "missing_setting",
            ),
            "no network setting in the document": (
                SETTINGS,
                {**FOUND, "network": None},
                "missing_setting",
            ),
            "no changes setting in the document": (
                SETTINGS,
                {**FOUND, "changes_allowed": None},
                "missing_setting",
            ),
            "a missing tool": (SETTINGS, {**FOUND, "tool_found": False}, "tool_not_installed"),
            "a missing login": (SETTINGS, {**FOUND, "login_found": False}, "no_login"),
        }
        for label, (settings, facts, reason) in cases.items():
            with self.subTest(label):
                got = codex.check(settings, facts)
                self.assertIsNotNone(got)
                self.assertEqual(got[0], reason)
                self.assertIn(reason, fixed.REASONS_BY_ENDING["could_not_start"])
                self.assertTrue(got[1])

    def test_good_settings_pass_with_or_without_an_effort(self):
        self.assertIsNone(codex.check(SETTINGS, FOUND))
        self.assertIsNone(codex.check({"model": "example-model"}, FOUND))

    def test_it_asks_where_the_login_is_and_never_opens_it(self):
        self.assertEqual(
            codex.login_path({"CODEX_HOME": "/custom", "HOME": "/h"}), "/custom/auth.json"
        )
        self.assertEqual(codex.login_path({"HOME": "/h"}), "/h/.codex/auth.json")
        self.assertIsNone(codex.login_path({}))
        self.assertIsNone(codex.login_path({"HOME": "relative"}))
        # The check is given only whether it is there: nothing in its facts can be read.
        self.assertEqual(set(FOUND), {"tool_found", "login_found", "network", "changes_allowed"})

    def test_the_document_check_names_a_driver_that_exists(self):
        good = {"name": PROGRAM, "settings": SETTINGS}
        self.assertIsNone(decisions._executor_refusal(good))
        self.assertEqual(
            decisions._executor_refusal({"name": PROGRAM, "settings": {}})[0], "missing_setting"
        )
        self.assertEqual(decisions._executor_refusal({"name": "nothing"})[0], "unknown_executor")


class TheLaunchCommand(unittest.TestCase):
    def argv(self, settings=SETTINGS, **extra):
        return codex.launch(settings, context(**extra))["argv"]

    def test_the_instruction_is_read_from_standard_input_and_never_named_on_the_line(self):
        argv = self.argv()
        self.assertEqual(argv[-1], "-")  # the tool reads its standard input when given a dash
        self.assertEqual(argv[:2], [PROGRAM, "exec"])
        self.assertEqual(argv[argv.index("-C") + 1], "/place")
        self.assertEqual(argv[argv.index("-m") + 1], "example-model")
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("-o") + 1], f"{AREA}/out/last-message.txt")
        self.assertEqual(codex.launch(SETTINGS, context())["output_to"], f"{AREA}/out/events.jsonl")

    def test_the_two_standard_settings_become_the_tools_own_sandbox(self):
        for network, changes, mode, net in (
            (False, True, "workspace-write", "false"),
            (True, True, "workspace-write", "true"),
            (False, False, "read-only", "false"),
            (True, False, "read-only", "true"),
        ):
            with self.subTest(network=network, changes=changes):
                argv = self.argv(network=network, changes_allowed=changes)
                self.assertEqual(argv[argv.index("-s") + 1], mode)
                self.assertIn(f"sandbox_workspace_write.network_access={net}", argv)
                self.assertIn("sandbox_workspace_write.exclude_slash_tmp=true", argv)

    def test_the_effort_is_passed_when_given_and_left_out_when_not(self):
        self.assertIn('model_reasoning_effort="low"', self.argv())
        self.assertFalse(any("effort" in part for part in self.argv({"model": "m"})))

    def test_no_part_of_the_line_holds_the_instruction_or_a_login(self):
        argv = self.argv()
        self.assertFalse(any("auth" in part or "instruction" in part for part in argv))


class TheSetupRequests(unittest.TestCase):
    ENVIRONMENT = {"HOME": "/h"}

    def requests(self):
        return codex.setup_requests(SETTINGS, self.ENVIRONMENT)

    def test_the_requests_are_ones_the_run_area_accepts(self):
        self.assertIsNone(run_area.refusal(self.requests()))

    def test_the_tool_home_is_in_the_run_area_with_the_settings_copied_and_the_login_linked(self):
        got = run_area.plan(AREA, self.requests())
        self.assertEqual(
            got["variables"],
            {
                "CODEX_HOME": f"{AREA}/home",
                "TMPDIR": f"{AREA}/tmp",
                "XDG_CACHE_HOME": f"{AREA}/cache",
            },
        )
        steps = got["steps"]
        self.assertIn(
            {
                "do": "copy",
                "source": "/h/.codex/config.toml",
                "target": f"{AREA}/home/config.toml",
                "leave_out": [],
            },
            steps,
        )
        self.assertIn(
            {"do": "share", "source": "/h/.codex/auth.json", "target": f"{AREA}/home/auth.json"},
            steps,
        )
        self.assertFalse([s for s in steps if s["do"] == "copy" and "auth" in s["source"]])

    def test_every_path_it_makes_is_inside_the_run_area(self):
        for step in run_area.plan(AREA, self.requests())["steps"]:
            self.assertTrue(step["target"].startswith(AREA + "/"), step)

    def test_history_sessions_and_caches_are_never_named(self):
        names = json.dumps(self.requests())
        for left_behind in ("history", "sessions", "models_cache", "sqlite", "logs"):
            self.assertNotIn(left_behind, names)

    def test_a_caller_with_no_home_gives_no_requests(self):
        self.assertEqual(codex.setup_requests(SETTINGS, {}), [])

    def test_the_named_tool_home_wins_over_the_default(self):
        got = codex.setup_requests(SETTINGS, {"CODEX_HOME": "/custom", "HOME": "/h"})
        self.assertEqual(got[0]["source"], "/custom/config.toml")


class Observing(unittest.TestCase):
    def group(self, **given):
        return codex.observe(SETTINGS, saved(**given))["group"]

    def test_a_finished_run_reads_from_its_events_and_session_record(self):
        got = self.group(
            events="events-finished.jsonl",
            last_message="last-message-done.txt",
            record="session-record.jsonl",
        )
        expected = {
            "executor_driver_name": ("value", "codex"),
            "executor_driver_version": ("value", "1"),
            "tool_version": ("value", "9.9.9"),
            "model": ("value", "example-model"),
            "effort": ("value", "low"),
            "tokens_in": ("value", 120),
            "tokens_out": ("value", 9),
            "tokens_cached": ("value", 40),
            "activity": ("value", 3),
            "session_id": ("value", "thread-0001"),
            "quota_level": ("value", 12.5),
            "vendor_limit_reached": ("value", False),
            "vendor_limit_reset": ("none", None),
            "waiting_question": ("none", None),
        }
        self.assertEqual({k: state_of(got[k]) for k in expected}, expected)

    def test_a_field_the_tool_does_not_give_reads_cannot_tell(self):
        got = self.group(events="events-finished.jsonl", last_message="last-message-done.txt")
        for field in (
            "tool_version",
            "model",
            "effort",
            "quota_level",
            "vendor_limit_reached",
            "refused_actions",
            "tool_made_own_commits",
        ):
            self.assertEqual(state_of(got[field]), ("cannot tell", None), field)

    def test_nothing_saved_reads_cannot_tell_for_everything_the_files_would_say(self):
        got = self.group()
        for field in ("tokens_in", "tokens_out", "tokens_cached", "activity", "session_id"):
            self.assertEqual(state_of(got[field]), ("cannot tell", None), field)
        self.assertEqual(state_of(got["waiting_question"]), ("cannot tell", None))

    def test_a_run_cut_short_has_no_usage_and_a_torn_last_line_is_skipped(self):
        got = self.group(events="events-cut-short.jsonl")
        self.assertEqual(state_of(got["tokens_in"]), ("none", None))
        self.assertEqual(state_of(got["session_id"]), ("value", "thread-0002"))
        self.assertEqual(state_of(got["activity"]), ("value", 0))

    def test_a_reached_limit_gives_its_reset_time(self):
        got = self.group(
            events="events-finished.jsonl", record="session-record-limit-reached.jsonl"
        )
        self.assertEqual(state_of(got["vendor_limit_reached"]), ("value", True))
        self.assertEqual(state_of(got["vendor_limit_reset"]), ("value", 1700003600))
        self.assertEqual(state_of(got["quota_level"]), ("value", 100))

    def test_the_driver_group_has_every_field_of_the_receipts_group(self):
        from shuttle.core.shapes import ExecutorDriverGroup

        self.assertEqual(set(self.group()), set(ExecutorDriverGroup.__annotations__))

    def test_the_statement_text_is_the_last_message_exactly_or_none(self):
        for name in ("last-message-done.txt", "last-message-question.txt"):
            observed = codex.observe(SETTINGS, saved(last_message=name))
            self.assertEqual(observed["statement_text"], saved_text(name))
        self.assertIsNone(codex.observe(SETTINGS, saved())["statement_text"])
        empty = {"events": None, "last_message": "", "session_record": None}
        self.assertIsNone(codex.observe(SETTINGS, empty)["statement_text"])


class AQuestionAsTheLastMessage(unittest.TestCase):
    def test_it_is_a_statement_of_the_wrong_shape_and_the_run_ended_by_itself(self):
        observed = codex.observe(
            SETTINGS,
            saved(events="events-asked-a-question.jsonl", last_message="last-message-question.txt"),
        )
        schema = json.loads(shipped_schema())
        examined = statement.examine(observed["statement_text"].encode(), schema)
        self.assertTrue(examined["problems"])  # wrong shape
        self.assertEqual(state_of(observed["group"]["waiting_question"])[0], "value")
        facts: Facts = {
            "launch": "ok",
            "wait": "exited",
            "stop": "confirmed",
            "closing_freeze": "ok",
            "delivery": "ok",
            "exit_code": 0,
        }
        got = decisions.decide_ending(facts)
        self.assertEqual(got["ending"], "ended_by_itself")

    def test_a_statement_in_the_right_shape_is_judged_right(self):
        observed = codex.observe(SETTINGS, saved(last_message="last-message-statement.json"))
        schema = json.loads(shipped_schema())
        examined = statement.examine(observed["statement_text"].encode(), schema)
        self.assertEqual((examined["problems"], examined["claim"]), ([], "done"))


class TheDriverNamesNoEnding(unittest.TestCase):
    def test_nothing_in_the_driver_names_an_ending_or_a_reason_of_one(self):
        path = os.path.join(os.path.dirname(codex.__file__), "codex.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        for ending in fixed.ENDINGS:
            self.assertNotIn(ending, source)
        for reason in ("time_limit", "stop_record", "launch_failed", "setup_failed"):
            self.assertNotIn(reason, source)

    def test_what_it_refuses_with_is_a_reason_the_decisions_already_list_and_not_an_ending(self):
        for reason in ("missing_setting", "unknown_setting", "tool_not_installed", "no_login"):
            self.assertIn(reason, fixed.REASONS_BY_ENDING["could_not_start"])
            self.assertNotIn(reason, fixed.ENDINGS)


if __name__ == "__main__":
    unittest.main()
