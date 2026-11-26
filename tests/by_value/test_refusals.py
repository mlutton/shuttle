"""By value: the pure refusal checks, as tables of cases.

Each check is a function over plain data that returns None (no refusal) or a refusal naming the
reason code, the failed step and one line of problem. The names are the ones `shuttle.core.refusals`
is expected to offer.
"""

import hashlib
import unittest

from shuttle.core import fixed, refusals


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RefusalCase(unittest.TestCase):
    def assertRefusal(self, found, reason, step):
        self.assertIsNotNone(found, f"expected a refusal {reason}")
        self.assertEqual((found["reason"], found["step"]), (reason, step))
        self.assertIn(reason, fixed.REASONS_BY_ENDING["could_not_start"])
        self.assertIn(step, fixed.STEPS_FOR_REASON[reason])
        self.assertTrue(found["problem"])


class ParseKinds(unittest.TestCase):
    CASES = (
        ("one of each", "judge\n", "plain\n", {"judge": True, "plain": False}),
        (
            "several, blank lines and comments",
            "# a\nbuild\n\njudge\n",
            "plain\n",
            {"build": True, "judge": True, "plain": False},
        ),
        (
            "surrounding space is dropped",
            "  build  \n",
            "\tplain\n",
            {"build": True, "plain": False},
        ),
        ("both empty", "", "", {}),
        ("a name in both files expects a statement", "x\n", "x\n", {"x": True}),
    )

    def test_each_file_gives_its_kinds_and_whether_a_statement_is_expected(self):
        for label, with_statement, without, expected in self.CASES:
            with self.subTest(label):
                self.assertEqual(refusals.parse_kinds(with_statement, without), expected)


class CheckKind(RefusalCase):
    KINDS = {"judge": True, "plain": False}

    def test_a_kind_on_either_list_is_accepted(self):
        for kind in ("judge", "plain"):
            with self.subTest(kind):
                self.assertIsNone(refusals.check_kind(kind, self.KINDS))

    def test_a_kind_on_neither_list_is_unknown_kind_at_the_input_check(self):
        for kind in ("", "Judge", "judge ", "other", "plain\n"):
            with self.subTest(kind):
                self.assertRefusal(
                    refusals.check_kind(kind, self.KINDS), "unknown_kind", "input_check"
                )

    def test_with_no_kinds_at_all_every_kind_is_unknown(self):
        self.assertRefusal(refusals.check_kind("plain", {}), "unknown_kind", "input_check")


class CheckInstruction(RefusalCase):
    def test_a_matching_hash_is_accepted(self):
        for text in ("do it", "", "line one\nline two\n", "naïve ✓"):
            with self.subTest(text):
                self.assertIsNone(refusals.check_instruction(text, digest(text)))

    def test_neither_given_is_accepted(self):
        self.assertIsNone(refusals.check_instruction(None, None))

    def test_a_hash_that_differs_is_refused_whatever_else_is_right(self):
        cases = (
            ("another text's hash", "do it", digest("do it ")),
            ("not a hash", "do it", "abc"),
            ("empty hash", "do it", ""),
            ("upper case is not the recorded form", "do it", digest("do it").upper()),
            ("hash of the text without its newline", "a\n", digest("a")),
        )
        for label, text, claimed in cases:
            with self.subTest(label):
                self.assertRefusal(
                    refusals.check_instruction(text, claimed),
                    "instruction_hash_mismatch",
                    "input_check",
                )

    def test_one_given_without_the_other_is_refused(self):
        self.assertRefusal(
            refusals.check_instruction("do it", None), "instruction_hash_mismatch", "input_check"
        )
        self.assertRefusal(
            refusals.check_instruction(None, digest("x")),
            "instruction_hash_mismatch",
            "input_check",
        )


class CheckReferences(RefusalCase):
    A = {"name": "runbook", "hash": digest("a"), "size": 1}
    B = {"name": "notes", "hash": digest("bb"), "size": 2}
    FOUND = {
        "runbook": {"hash": digest("a"), "size": 1},
        "notes": {"hash": digest("bb"), "size": 2},
    }

    def test_no_references_and_matching_references_are_accepted(self):
        self.assertIsNone(refusals.check_references([], {}))
        self.assertIsNone(refusals.check_references([self.A, self.B], self.FOUND))

    def test_a_reference_not_found_is_reference_missing(self):
        self.assertRefusal(
            refusals.check_references([self.A], {}), "reference_missing", "input_check"
        )
        self.assertRefusal(
            refusals.check_references([self.A, self.B], {"runbook": self.FOUND["runbook"]}),
            "reference_missing",
            "input_check",
        )

    def test_a_reference_whose_hash_or_size_differs_is_reference_hash_mismatch(self):
        cases = (
            ("hash", {"runbook": {"hash": digest("z"), "size": 1}}),
            ("size", {"runbook": {"hash": digest("a"), "size": 2}}),
        )
        for label, found in cases:
            with self.subTest(label):
                self.assertRefusal(
                    refusals.check_references([self.A], found),
                    "reference_hash_mismatch",
                    "input_check",
                )

    def test_the_first_bad_reference_in_the_document_order_decides(self):
        found = {"notes": {"hash": "wrong", "size": 2}}
        got = refusals.check_references([self.A, self.B], found)
        self.assertRefusal(got, "reference_missing", "input_check")
        self.assertIn("runbook", got["problem"])


class CheckStatementLocation(RefusalCase):
    def test_a_free_location_for_a_kind_that_expects_a_statement_is_accepted(self):
        self.assertIsNone(refusals.check_statement_location(True, "/out/s.json", False))

    def test_an_occupied_location_is_refused(self):
        self.assertRefusal(
            refusals.check_statement_location(True, "/out/s.json", True),
            "statement_location_occupied",
            "input_check",
        )

    def test_a_kind_that_expects_a_statement_needs_a_location(self):
        self.assertRefusal(
            refusals.check_statement_location(True, None, False), "missing_setting", "input_check"
        )

    def test_a_kind_that_expects_none_is_not_asked_about_the_location(self):
        for location, occupied in ((None, False), ("/out/s.json", True), ("/out/s.json", False)):
            with self.subTest((location, occupied)):
                self.assertIsNone(refusals.check_statement_location(False, location, occupied))


class CheckReach(RefusalCase):
    def test_absent_and_empty_reach_are_accepted(self):
        for reach in (None, {}, []):
            with self.subTest(reach):
                self.assertIsNone(refusals.check_reach(reach))

    def test_any_content_is_reach_not_available(self):
        for reach in ({"read": ["/etc"]}, ["x"], "all", 1, True, 0, ""):
            with self.subTest(reach):
                self.assertRefusal(
                    refusals.check_reach(reach), "reach_not_available", "input_check"
                )


class LooksLikeCredential(unittest.TestCase):
    YES = (
        "sk-abcdefghijklmnopqrstuvwxyz",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_11ABCDEFG0abcdefghijklmnop",
        "xoxb-1234-5678-abcdef",
        "AKIAABCDEFGHIJKLMNOP",
        "Bearer abc.def.ghi",
        "-----BEGIN PRIVATE KEY-----",
        "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7",
    )
    NO = ("", "1", "true", "/usr/bin", "hello world", "en_US.UTF-8", "a-short-word", "x" * 10)

    def test_known_secret_shapes_and_long_unbroken_tokens_look_like_credentials(self):
        for value in self.YES:
            with self.subTest(value):
                self.assertTrue(refusals.looks_like_credential(value))

    def test_ordinary_values_do_not(self):
        for value in self.NO:
            with self.subTest(value):
                self.assertFalse(refusals.looks_like_credential(value))


class CheckEnvironmentEntries(RefusalCase):
    def test_names_alone_are_accepted(self):
        self.assertIsNone(refusals.check_environment_entries([]))
        self.assertIsNone(refusals.check_environment_entries(["HOME", "MY_KEY-2"]))

    def test_a_name_given_with_a_credential_like_value_is_refused(self):
        for entry in (
            "TOKEN=sk-abcdefghijklmnopqrstuvwxyz",
            "A=Bearer abc.def",
            "K= AKIAABCDEFGHIJKLMNOP",
        ):
            with self.subTest(entry):
                got = refusals.check_environment_entries(["HOME", entry])
                self.assertRefusal(got, "credential_like_value", "input_check")
                self.assertNotIn("abcdefghijklmnop", got["problem"])

    def test_a_credential_like_value_is_found_wherever_it_sits_in_the_list(self):
        for entries in (
            ["MODE=fast", "TOKEN=sk-abcdefghijklmnopqrstuvwxyz"],
            ["=x", "K=Bearer abc.def"],
        ):
            with self.subTest(entries):
                got = refusals.check_credential_values(entries)
                self.assertRefusal(got, "credential_like_value", "input_check")
                self.assertNotIn("abcdefghijklmnop", got["problem"])
        for entries in ([], ["HOME", "MODE=fast", 5], "not a list", None):
            with self.subTest(entries):
                self.assertIsNone(refusals.check_credential_values(entries))

    def test_a_name_given_with_any_other_value_is_missing_setting(self):
        for entry in ("MODE=fast", "MODE=", "=x"):
            with self.subTest(entry):
                self.assertRefusal(
                    refusals.check_environment_entries([entry]), "missing_setting", "input_check"
                )

    def test_a_bad_name_or_a_non_text_entry_is_missing_setting(self):
        for entry in ("", "has space", "dot.name", 5, None, ["A"]):
            with self.subTest(entry):
                self.assertRefusal(
                    refusals.check_environment_entries([entry]), "missing_setting", "input_check"
                )

    def test_a_list_that_is_not_a_list_is_missing_setting(self):
        for entries in ("HOME", {"HOME": "x"}, 3):
            with self.subTest(entries):
                self.assertRefusal(
                    refusals.check_environment_entries(entries), "missing_setting", "input_check"
                )


class GateAnswers(RefusalCase):
    def test_a_gate_answers_by_its_exit_code(self):
        cases = (
            ("exit 0 is yes", dict(started=True, exit_code=0, timed_out=False), "yes"),
            ("exit 1 is no", dict(started=True, exit_code=1, timed_out=False), "no"),
            (
                "another exit code is failed",
                dict(started=True, exit_code=2, timed_out=False),
                "failed",
            ),
            ("exit 255 is failed", dict(started=True, exit_code=255, timed_out=False), "failed"),
            (
                "killed by a signal is failed",
                dict(started=True, exit_code=None, timed_out=False),
                "failed",
            ),
            (
                "past its limit is failed even with exit 0",
                dict(started=True, exit_code=0, timed_out=True),
                "failed",
            ),
            (
                "past its limit is failed even with exit 1",
                dict(started=True, exit_code=1, timed_out=True),
                "failed",
            ),
            (
                "one that could not start is failed",
                dict(started=False, exit_code=None, timed_out=False),
                "failed",
            ),
        )
        for label, facts, answer in cases:
            with self.subTest(label):
                self.assertEqual(refusals.gate_answer(**facts), answer)

    def test_all_yes_is_accepted_and_no_gates_is_accepted(self):
        self.assertIsNone(refusals.check_gates([]))
        self.assertIsNone(refusals.check_gates([("quota", "yes"), ("disk", "yes")]))

    def test_a_no_is_gate_said_no_at_gates_and_names_the_gate_and_its_answer(self):
        got = refusals.check_gates([("quota", "yes"), ("disk", "no")])
        self.assertRefusal(got, "gate_said_no", "gates")
        self.assertIn("disk", got["problem"])
        self.assertIn("no", got["problem"])

    def test_a_failure_is_gate_failed_at_gates_and_names_the_gate_and_its_answer(self):
        got = refusals.check_gates([("quota", "failed")])
        self.assertRefusal(got, "gate_failed", "gates")
        self.assertIn("quota", got["problem"])
        self.assertIn("failed", got["problem"])

    def test_the_first_gate_that_does_not_say_yes_decides(self):
        self.assertRefusal(
            refusals.check_gates([("a", "failed"), ("b", "no")]), "gate_failed", "gates"
        )
        self.assertRefusal(
            refusals.check_gates([("a", "no"), ("b", "failed")]), "gate_said_no", "gates"
        )

    def test_an_answer_that_is_not_yes_no_or_failed_is_gate_failed(self):
        self.assertRefusal(refusals.check_gates([("a", "maybe")]), "gate_failed", "gates")


class Combining(RefusalCase):
    FIRST = {"reason": "unknown_kind", "step": "input_check", "problem": "p1"}
    SECOND = {"reason": "gate_said_no", "step": "gates", "problem": "p2"}

    def test_the_first_refusal_of_a_list_decides_and_none_are_skipped(self):
        self.assertIsNone(refusals.first_refusal([]))
        self.assertIsNone(refusals.first_refusal([None, None]))
        self.assertEqual(refusals.first_refusal([None, self.FIRST, self.SECOND]), self.FIRST)

    def test_every_problem_is_listed_in_order_for_the_check_form(self):
        self.assertEqual(refusals.all_problems([None, self.FIRST, self.SECOND]), "p1; p2")
        self.assertEqual(refusals.all_problems([None]), "")


class FillRequestId(unittest.TestCase):
    def test_an_absent_request_id_is_filled_with_the_generated_one_and_the_original_is_untouched(
        self,
    ):
        original = {"kind": "plain"}
        got = refusals.fill_request_id(original, "abc123")
        self.assertEqual(got, {"kind": "plain", "request_id": "abc123"})
        self.assertEqual(original, {"kind": "plain"})

    def test_a_request_id_given_is_kept_even_when_it_is_invalid(self):
        for given in ("mine", "", "has space", 5, None):
            with self.subTest(given):
                self.assertEqual(
                    refusals.fill_request_id({"request_id": given}, "abc123"),
                    {"request_id": given},
                )

    def test_a_document_that_is_not_an_object_is_returned_as_it_is(self):
        for raw in ([], "x", 3, None):
            with self.subTest(raw):
                self.assertEqual(refusals.fill_request_id(raw, "abc123"), raw)


if __name__ == "__main__":
    unittest.main()
