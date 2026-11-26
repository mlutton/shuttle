"""By value: the place's decisions, as functions of plain data.

What looking at the place found and what to make of it (the refusals, in their order), the
environment every git call is given, the freeze's command, and what the freeze's answer means.
Nothing here runs git or a process.
"""

import unittest

from shuttle.core import boundary, fixed, place
from shuttle.core import decisions as core
from shuttle.core.shapes import FreezeAnswer

# Names that break careless code (the full table is looped, with the real filesystem, by the
# contract cases in tests/rehearsal/contract.py): what these tests need is that a name never
# reaches a line of text raw and is never changed on its way into the freeze's command.
AWKWARD = (
    "a b",
    "line\nbreak",
    "cr\rx",
    "tab\there",
    "-leading-dash",
    "$HOME",
    "${X}",
    "$$",
    "50%h",
    "back\\slash",
    "```",
    "bad\udcffname",
    "\u202eright-to-left",
)


def one_line(text):
    return len(text.splitlines()) <= 1 and all(c.isprintable() for c in text)


COMMIT = "a" * 40
OTHER = "b" * 40
GOOD = f"commit {OTHER}\nadded 3\nchanged 2\ndeleted 1\ndone\n".encode()


def facts(**changes):
    found = {
        "exists": True,
        "is_checkout": True,
        "head": COMMIT,
        "unclean": [],
        "nested": [],
        "filtered": [],
    }
    found.update(changes)
    return found


class TheEnvironmentOfEveryGitCall(unittest.TestCase):
    def test_it_holds_path_and_what_makes_the_call_independent_of_the_callers_git(self):
        env = place.git_environment("/bin")
        self.assertEqual(env["PATH"], "/bin")
        for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
            self.assertEqual(env[name], "/dev/null")
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")  # nothing is ever asked
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")  # looking never rewrites the index

    def test_it_overrides_the_places_own_settings_for_hooks_signing_and_the_ignore_file(self):
        env = place.git_environment("/bin")
        count = int(env["GIT_CONFIG_COUNT"])
        settings = {env[f"GIT_CONFIG_KEY_{n}"]: env[f"GIT_CONFIG_VALUE_{n}"] for n in range(count)}
        self.assertEqual(len(settings), count)
        self.assertEqual(settings["core.hooksPath"], "/dev/null")
        self.assertEqual(settings["commit.gpgsign"], "false")
        self.assertEqual(settings["tag.gpgsign"], "false")
        self.assertEqual(settings["core.excludesFile"], "/dev/null")
        self.assertEqual(settings["core.fsmonitor"], "false")
        self.assertEqual(settings["core.autocrlf"], "false")

    def test_the_author_and_the_committer_are_one_neutral_identity_with_a_fixed_date(self):
        env = place.git_environment("/bin")
        for who in ("AUTHOR", "COMMITTER"):
            self.assertEqual(env[f"GIT_{who}_NAME"], "Shuttle")
            self.assertEqual(env[f"GIT_{who}_EMAIL"], "")
            self.assertEqual(env[f"GIT_{who}_DATE"], env["GIT_AUTHOR_DATE"])

    def test_no_path_leaves_none_in_and_nothing_else_of_the_callers_is_ever_added(self):
        env = place.git_environment(None)
        self.assertNotIn("PATH", env)
        allowed = {"GIT_", "LC_ALL"}
        self.assertEqual([k for k in env if not any(k.startswith(p) for p in allowed)], [])


class TheRefusals(unittest.TestCase):
    def reason(self, where, found):
        refusal = place.check_place(where, found)
        return refusal and (refusal["reason"], refusal["step"])

    def test_a_place_that_can_be_run_on_is_not_refused(self):
        self.assertIsNone(place.check_place("/p", facts()))

    def test_a_place_that_is_not_given_or_cannot_be_a_path_is_missing(self):
        for where in (None, "", 3, ["/p"], "a\0b"):
            with self.subTest(place=where):
                self.assertEqual(self.reason(where, facts()), ("place_missing", "input_check"))
        self.assertEqual(self.reason("/p", None), ("place_missing", "input_check"))

    def test_a_folder_that_is_not_there_is_missing(self):
        self.assertEqual(
            self.reason("/p", facts(exists=False, is_checkout=False, head=None)),
            ("place_missing", "input_check"),
        )

    def test_a_folder_that_is_not_the_top_of_a_checkout_is_not_a_git_checkout(self):
        self.assertEqual(
            self.reason("/p", facts(is_checkout=False, head=None)),
            ("place_not_a_git_checkout", "input_check"),
        )

    def test_a_checkout_with_no_commit_has_nothing_to_fingerprint_and_is_not_a_git_checkout(self):
        self.assertEqual(
            self.reason("/p", facts(head=None)), ("place_not_a_git_checkout", "input_check")
        )

    def test_uncommitted_or_new_files_refuse_the_place(self):
        self.assertEqual(
            self.reason("/p", facts(unclean=["a.txt"])),
            ("place_has_uncommitted_changes", "input_check"),
        )

    def test_a_filter_attribute_refuses_the_place_naming_a_path_before_anything_else(self):
        found = facts(filtered=["data.big", "x.big"], unclean=["a"], nested=["inner"])
        self.assertEqual(self.reason("/p", found), ("place_has_filter_attribute", "input_check"))
        refusal = place.check_place("/p", found)
        self.assertIn("filter drivers are not supported", refusal["problem"])
        self.assertIn("'data.big'", refusal["problem"])

    def test_a_document_with_no_place_says_the_place_is_missing_from_it_not_none(self):
        refusal = place.check_place(None, None)
        self.assertEqual(refusal["reason"], "place_missing")
        self.assertNotIn("None", refusal["problem"])
        self.assertIn("no place", refusal["problem"])

    def test_a_nested_repository_is_named_before_the_new_file_git_says_it_is(self):
        found = facts(unclean=["inner/"], nested=["inner"])
        self.assertEqual(self.reason("/p", found), ("place_has_nested_repository", "input_check"))

    def test_every_reason_it_gives_is_one_the_fixed_list_allows_for_that_step(self):
        for found in (
            facts(exists=False),
            facts(is_checkout=False),
            facts(nested=["x"]),
            facts(filtered=["x"]),
            facts(unclean=["x"]),
        ):
            reason, step = self.reason("/p", found)
            self.assertIn(reason, fixed.REASONS_BY_ENDING["could_not_start"])
            self.assertIn(step, fixed.STEPS_FOR_REASON[reason])

    def test_the_problem_names_every_awkward_name_on_one_line_and_never_pastes_it_raw(self):
        for name in AWKWARD:
            for found in (facts(unclean=[name]), facts(nested=[name])):
                with self.subTest(name):
                    refusal = place.check_place(name, found)
                    self.assertTrue(refusal)
                    self.assertTrue(one_line(refusal["problem"]), refusal["problem"])

    def test_a_long_list_is_shortened_and_says_how_many_more(self):
        refusal = place.check_place("/p", facts(unclean=[f"f{n}" for n in range(10)]))
        self.assertIn("and 7 more", refusal["problem"])
        self.assertNotIn("f9", refusal["problem"])


class TheOpeningResult(unittest.TestCase):
    def test_a_clean_place_gives_its_own_commit_as_the_fingerprint(self):
        self.assertEqual(
            place.opening_result(None, facts(), 0.5),
            {"ok": True, "fingerprint": COMMIT, "duration_seconds": 0.5},
        )

    def test_a_refused_place_gives_no_fingerprint_and_fails(self):
        refusal = place.check_place("/p", facts(unclean=["x"]))
        self.assertEqual(
            place.opening_result(refusal, facts(unclean=["x"]), 0.5),
            {"ok": False, "duration_seconds": 0.5},
        )


class TheFreezeCommand(unittest.TestCase):
    def argv(self, where="/p", opening=COMMIT):
        return place.freeze_argv("scope-1", 2.5, where, opening, "req-1")

    def inside(self, argv):
        """What the scope's command is, once the scope tool turned each `$$` back into `$`."""
        return [part.replace("$$", "$") for part in argv[argv.index("--") + 1 :]]

    def test_it_runs_in_a_scope_of_its_own_with_the_limit_on_the_scope(self):
        argv = self.argv()
        self.assertEqual(
            argv[:5], ["systemd-run", "--user", "--scope", "--quiet", "--unit=scope-1"]
        )
        self.assertIn("RuntimeMaxSec=2500000us", argv)
        self.assertEqual(argv, boundary.scoped_argv("scope-1", 2.5, self.inside(argv)))

    def test_the_place_the_commit_the_reference_and_the_message_are_arguments_not_script_text(self):
        inside = self.inside(self.argv())
        self.assertEqual(inside[:4], ["sh", "-c", place.FREEZE_SCRIPT, "sh"])
        self.assertEqual(inside[4:6], ["/p", COMMIT])
        self.assertEqual(inside[6], "refs/shuttle/freeze/req-1")
        self.assertIn("req-1", inside[7])
        self.assertEqual(len(inside), 8)

    def test_a_place_with_awkward_characters_arrives_whole(self):
        for where in (*AWKWARD, "/a b/$HOME", "/$$x", "/${X}%h%n\\", "/-rf", "/new\nline"):
            with self.subTest(where):
                self.assertEqual(self.inside(self.argv(where=where))[4], where)

    def test_a_dollar_in_the_place_is_doubled_for_the_scope_tool_as_every_argument_is(self):
        argv = self.argv(where="/p$HOME")
        self.assertIn("/p$$HOME", argv)

    def test_an_opening_that_is_not_a_commit_id_is_refused_so_it_can_never_read_as_an_option(self):
        for opening in (
            "",
            "--upload-pack=x",
            "-n",
            COMMIT.upper(),
            "a" * 39,
            "a" * 41,
            "HEAD",
            COMMIT + "\n",
        ):
            with self.subTest(opening=opening), self.assertRaises(ValueError):
                self.argv(opening=opening)
        self.assertTrue(self.argv(opening="c" * 64))  # a SHA-256 repository

    def test_the_script_makes_no_commit_the_places_own_history_could_move(self):
        script = place.FREEZE_SCRIPT
        for word in ("commit-tree", "update-ref", "GIT_INDEX_FILE", "read-tree", "add -A"):
            self.assertIn(word, script)
        for word in ("git commit ", "checkout", "reset", "stash", "git push", "git config"):
            self.assertNotIn(word, script)

    def test_the_script_takes_the_variables_that_reach_the_users_systemd_out_of_git_s_environment(
        self,
    ):
        self.assertTrue(place.FREEZE_SCRIPT.startswith("unset " + " ".join(boundary.BUS_VARIABLES)))


class TheExecutorsWorkingDirectory(unittest.TestCase):
    def test_the_executor_starts_in_the_place_when_one_is_given_and_nowhere_in_particular_otherwise(
        self,
    ):
        with_place = boundary.launch_argv("n", 1, ["tool"], [], [], 3, "/p")
        without = boundary.launch_argv("n", 1, ["tool"], [], [], 3)
        inside = [part.replace("$$", "$") for part in with_place]
        at = inside.index("--chdir")
        self.assertEqual(inside[at : at + 2], ["--chdir", "/p"])
        self.assertLess(at, inside.index("--", at))  # before the executor's own command
        self.assertNotIn("--chdir", without)

    def test_a_place_with_awkward_characters_is_one_argument_unchanged(self):
        for where in ("/a b", "/$HOME", "/-x", "/a\nb", "/50%h"):
            with self.subTest(where):
                argv = [
                    p.replace("$$", "$")
                    for p in boundary.launch_argv("n", 1, ["t"], [], [], 3, where)
                ]
                self.assertEqual(argv[argv.index("--chdir") + 1], where)


class WhatTheFreezePrints(unittest.TestCase):
    def test_a_whole_answer_gives_the_commit_and_the_three_counts(self):
        self.assertEqual(place.parse_freeze_output(GOOD), (OTHER, 3, 2, 1))

    def test_anything_that_is_not_exactly_what_the_script_prints_when_done_gives_nothing(self):
        bad = {
            "empty": b"",
            "no done": GOOD.replace(b"done\n", b""),
            "cut short": GOOD[: len(GOOD) // 2],
            "text after done": GOOD + b"more\n",
            "no final newline": GOOD[:-1],
            "a count that is not a number": GOOD.replace(b"added 3", b"added x"),
            "a negative count": GOOD.replace(b"added 3", b"added -3"),
            "a count with a sign": GOOD.replace(b"added 3", b"added +3"),
            "a count that is a digit in another script": GOOD.replace(
                b"added 3", "added ٣".encode()
            ),
            "a count with nothing": GOOD.replace(b"added 3", b"added "),
            "words in another order": GOOD.replace(b"added", b"changed", 1),
            "a commit that is not hex": GOOD.replace(OTHER.encode(), b"z" * 40),
            "a short commit": GOOD.replace(OTHER.encode(), b"b" * 8),
            "a second answer": GOOD + GOOD,
            "bytes that are not text": b"\xff\xfe" + GOOD,
        }
        for label, output in bad.items():
            with self.subTest(label):
                self.assertIsNone(place.parse_freeze_output(output))

    def test_a_count_may_be_padded_the_way_wc_pads_it_on_some_systems(self):
        padded = GOOD.replace(b"added 3", b"added      3")
        self.assertEqual(place.parse_freeze_output(padded), (OTHER, 3, 2, 1))


class TheClosingResult(unittest.TestCase):
    def result(self, answer, why=boundary.ENDED):
        return place.closing_result(answer, why, 0.25)

    def test_a_whole_answer_from_a_scope_seen_to_end_is_the_fingerprint_and_the_counts(self):
        self.assertEqual(
            self.result(FreezeAnswer(0, GOOD)),
            {
                "ok": True,
                "fingerprint": OTHER,
                "files_added": 3,
                "files_changed": 2,
                "files_deleted": 1,
                "duration_seconds": 0.25,
            },
        )

    def test_everything_else_fails_with_no_fingerprint_and_no_counts_and_says_why(self):
        cases = {
            "the command could not be started": (None, boundary.ENDED, "could not be started"),
            "the scope's limit ran out": (FreezeAnswer(-15, b""), boundary.TIMED_OUT, "limit"),
            "the scope was not seen to end": (FreezeAnswer(0, GOOD), boundary.CANNOT_TELL, "scope"),
            "git ended with an error": (FreezeAnswer(128, b""), boundary.ENDED, "status 128"),
            "git ended with an error after it printed a whole answer": (
                FreezeAnswer(1, GOOD),
                boundary.ENDED,
                "status 1",
            ),
            "the answer is not whole": (FreezeAnswer(0, b"commit x\n"), boundary.ENDED, "answer"),
        }
        for label, (answer, why, word) in cases.items():
            with self.subTest(label):
                found = self.result(answer, why)
                self.assertEqual(sorted(found), ["duration_seconds", "ok", "problem"])
                self.assertIs(found["ok"], False)
                self.assertIn(word, found["problem"])
                self.assertIn("opening fingerprint stands", found["problem"])

    def test_a_scope_that_ran_out_of_its_limit_fails_even_when_the_answer_looks_whole(self):
        self.assertIs(self.result(FreezeAnswer(0, GOOD), boundary.TIMED_OUT)["ok"], False)


class WhatTheReceiptSaysOfTheTwoFingerprints(unittest.TestCase):
    ENDED = {"ending": "ended_by_itself", "reason": fixed.NONE, "failed_step": fixed.NONE}

    def execution(self, opening, closing):
        steps = {"opening_fingerprint": opening}
        if closing is not None:
            steps["closing_freeze"] = closing
        receipt = core.build_receipt(
            self.ENDED,
            {
                "receipt_id": "r",
                "execution_version": "1",
                "host": "h",
                "input_hash": "x",
                "launched": True,
                "started_at": "t",
                "ended_at": "t",
                "executor_duration": 1.0,
                "exit_code": 0,
                "signal": None,
                "executor_driver_observations": None,
                "stand_ins": steps,
                "reason_text": None,
            },
        )
        return receipt["execution"]

    def test_equal_fingerprints_say_the_run_changed_nothing_and_the_counts_are_zero(self):
        saw = self.execution(
            {"ok": True, "fingerprint": COMMIT},
            {
                "ok": True,
                "fingerprint": COMMIT,
                "files_added": 0,
                "files_changed": 0,
                "files_deleted": 0,
            },
        )
        self.assertEqual(saw["changed_nothing"], {"state": "value", "value": True})
        for field in ("files_added", "files_changed", "files_deleted"):
            self.assertEqual(saw[field], {"state": "value", "value": 0})

    def test_different_fingerprints_say_it_changed_something(self):
        saw = self.execution(
            {"ok": True, "fingerprint": COMMIT},
            {
                "ok": True,
                "fingerprint": OTHER,
                "files_added": 1,
                "files_changed": 0,
                "files_deleted": 0,
            },
        )
        self.assertEqual(saw["changed_nothing"], {"state": "value", "value": False})

    def test_a_failed_closing_freeze_cannot_tell_and_never_says_it_changed_something(self):
        saw = self.execution({"ok": True, "fingerprint": COMMIT}, {"ok": False, "problem": "p"})
        for field in (
            "changed_nothing",
            "fingerprint_after",
            "files_added",
            "files_changed",
            "files_deleted",
        ):
            self.assertEqual(saw[field], {"state": "cannot tell", "value": None}, field)
        self.assertEqual(saw["fingerprint_before"], {"state": "value", "value": COMMIT})

    def test_a_run_that_took_no_closing_freeze_has_nothing_to_compare(self):
        saw = self.execution({"ok": True, "fingerprint": COMMIT}, None)
        self.assertEqual(saw["changed_nothing"], {"state": "none", "value": None})
        self.assertEqual(saw["fingerprint_after"], {"state": "none", "value": None})


if __name__ == "__main__":
    unittest.main()
