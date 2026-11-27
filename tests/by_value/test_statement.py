"""By value: the statement's shape against the schema, the schema as data, and the notice.

The schema is the file `shuttle/data/statement_schema.json`, read here as a second program
would read it (plain `json`, no Shuttle code) and then handed to the shape check. Statements are
a table: each row is the text the executor left and what the check says of it.
"""

import json
import os
import unittest

from shuttle.core import fixed, notice, statement

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "shuttle",
    "data",
    "statement_schema.json",
)
with open(SCHEMA_PATH, encoding="utf-8") as f:
    SCHEMA = json.load(f)

RIGHT = {
    "claim": "done",
    "summary": "Did it.",
    "evidence": [{"claim": "the tests pass", "command": "./checks/all.sh"}],
    "not_tested": ["the hosted runner"],
    "feedback": "The instruction was clear.",
}


def changed(**changes):
    """RIGHT with some fields replaced; a value of `...` removes the field."""
    made = {**RIGHT, **changes}
    return {k: v for k, v in made.items() if v is not ...}


def text_of(held):
    return json.dumps(held)


ACCEPTED = {
    "every field right": text_of(RIGHT),
    "each claim word": None,  # expanded below
    "no evidence and nothing left untested": text_of(changed(evidence=[], not_tested=[])),
    "several evidence items and not-tested items": text_of(
        changed(
            evidence=[{"claim": "a", "command": "b"}, {"claim": "c", "command": "d"}],
            not_tested=["x", "y"],
        )
    ),
    "text with a newline and a non-ASCII letter": text_of(changed(summary="line\nnaïve ✓")),
    "padding the way a person writes it": "  " + json.dumps(RIGHT, indent=4) + "\r\n\r\n",
    "a key in another order": json.dumps(dict(reversed(list(RIGHT.items())))),
}

REJECTED = {
    "empty": "",
    "not JSON": "I did it.",
    "JSON that is not an object": "[1, 2]",
    "a bare string": '"done"',
    "null": "null",
    "a byte order mark first": "﻿" + text_of(RIGHT),
    "a key twice": text_of(RIGHT)[:-1] + ', "claim": "done"}',
    "nested too deep to read": "[" * 100000,
    "claim missing": text_of(changed(claim=...)),
    "claim not on the list": text_of(changed(claim="finished")),
    "claim in capitals": text_of(changed(claim="DONE")),
    "claim with a space after it": text_of(changed(claim="done ")),
    "claim not text": text_of(changed(claim=1)),
    "claim a list": text_of(changed(claim=["done"])),
    "summary missing": text_of(changed(summary=...)),
    "summary blank": text_of(changed(summary="  \n")),
    "summary not text": text_of(changed(summary=["x"])),
    "evidence missing": text_of(changed(evidence=...)),
    "evidence not a list": text_of(changed(evidence="all of it")),
    "an evidence item that is text": text_of(changed(evidence=["the tests pass"])),
    "an evidence item without its command": text_of(changed(evidence=[{"claim": "a"}])),
    "an evidence item without its claim": text_of(changed(evidence=[{"command": "a"}])),
    "an evidence item with a blank command": text_of(
        changed(evidence=[{"claim": "a", "command": ""}])
    ),
    "an evidence item with a field of its own": text_of(
        changed(evidence=[{"claim": "a", "command": "b", "log": "pasted"}])
    ),
    "not_tested missing": text_of(changed(not_tested=...)),
    "not_tested a text": text_of(changed(not_tested="nothing")),
    "not_tested with a blank item": text_of(changed(not_tested=["a", " "])),
    "not_tested with an item that is not text": text_of(changed(not_tested=[1])),
    "feedback missing": text_of(changed(feedback=...)),
    "feedback blank": text_of(changed(feedback="")),
    "a field the schema does not have": text_of(changed(confidence="high")),
    "a field with another name's spelling": text_of(changed(not_tested=..., notTested=[])),
}


class TheShapeCheck(unittest.TestCase):
    def test_a_statement_of_the_right_shape_has_no_problems_and_its_claim_is_read_as_it_is(self):
        words = next(f["words"] for f in SCHEMA["fields"] if f["name"] == "claim")
        cases = {k: v for k, v in ACCEPTED.items() if v is not None}
        cases.update({f"claim {word}": text_of(changed(claim=word)) for word in words})
        for label, text in cases.items():
            with self.subTest(label):
                got = statement.examine(text.encode("utf-8"), SCHEMA)
                self.assertEqual(got["problems"], [])
                self.assertEqual(got["claim"], json.loads(text)["claim"])

    def test_a_statement_of_the_wrong_shape_has_a_problem_and_no_claim(self):
        for label, text in REJECTED.items():
            with self.subTest(label):
                got = statement.examine(text.encode("utf-8"), SCHEMA)
                self.assertNotEqual(got["problems"], [])
                self.assertIsNone(got["claim"])

    def test_bytes_that_are_not_utf_8_are_the_wrong_shape(self):
        got = statement.examine(text_of(RIGHT).encode("utf-8")[:-1] + b"\xff}", SCHEMA)
        self.assertNotEqual(got["problems"], [])

    def test_each_problem_names_the_field_it_is_about(self):
        cases = (
            (changed(claim="finished"), "claim"),
            (changed(summary=" "), "summary"),
            (changed(evidence=[{"claim": "a"}]), "evidence[0].command is missing"),
            (changed(not_tested=["a", 1]), "not_tested[1]"),
            (changed(feedback=...), "feedback is missing"),
            (changed(extra=1), "extra is not a field of it"),
        )
        for held, expected in cases:
            with self.subTest(expected):
                got = statement.examine(text_of(held).encode(), SCHEMA)
                self.assertTrue(any(expected in p for p in got["problems"]), got["problems"])

    def test_every_problem_is_listed_not_only_the_first(self):
        got = statement.examine(
            text_of(changed(claim="x", summary="", feedback=...)).encode(), SCHEMA
        )
        self.assertEqual(len(got["problems"]), 3)

    def test_the_check_reads_the_schema_it_is_given_and_holds_no_copy(self):
        other = {"fields": [{"name": "answer", "kind": "word", "words": ["yes", "no"]}]}
        self.assertEqual(statement.examine(b'{"answer": "yes"}', other)["problems"], [])
        self.assertNotEqual(statement.examine(b'{"answer": "maybe"}', other)["problems"], [])
        self.assertNotEqual(statement.examine(text_of(RIGHT).encode(), other)["problems"], [])


class TheSchemaIsData(unittest.TestCase):
    def test_the_file_names_the_fields_the_ticket_names_in_plain_words(self):
        self.assertEqual(
            [f["name"] for f in SCHEMA["fields"]],
            ["claim", "summary", "evidence", "not_tested", "feedback"],
        )

    def test_the_claim_is_one_list_of_single_words(self):
        claim = SCHEMA["fields"][0]
        self.assertEqual(claim["kind"], "word")
        self.assertEqual(claim["words"], ["done", "partly_done", "blocked", "not_done"])

    def test_evidence_items_are_a_claim_and_a_command(self):
        evidence = next(f for f in SCHEMA["fields"] if f["name"] == "evidence")
        self.assertEqual([f["name"] for f in evidence["items"]["fields"]], ["claim", "command"])

    def test_the_kept_name_cannot_be_the_name_of_a_record(self):
        name = statement.kept_name("req-1")
        self.assertEqual(name, "req-1.statement.kept")
        for kind in fixed.RECORD_KINDS:
            self.assertNotEqual(name, f"req-1.{kind}.json")


class WhereTheStatementIsCopiedTo(unittest.TestCase):
    def test_the_parent_of_a_location_is_the_text_before_its_last_slash(self):
        for location, parent in (
            ("/out/s.json", "/out"),
            ("/s.json", "/"),
            ("/a b/$x/-s", "/a b/$x"),
            ("s.json", "."),
        ):
            with self.subTest(location):
                self.assertEqual(statement.location_parent(location), parent)

    def test_the_copy_goes_into_the_folder_the_parent_was_at_the_start_or_nowhere(self):
        for label, start, now, stopped, expected in (
            ("unchanged", "/real/out", "/real/out", True, "/real/out/s.json"),
            ("parent now leads elsewhere", "/real/out", "/victim", True, None),
            ("parent now gone", "/real/out", None, True, None),
            ("no parent seen at the start", None, "/real/out", True, None),
            ("the stop is not confirmed", "/real/out", "/real/out", False, None),
            ("the root", "/", "/", True, "/s.json"),
        ):
            with self.subTest(label):
                got = statement.location_copy_target("/out/s.json", start, now, stopped)
                self.assertEqual(got, expected)

    def test_the_name_is_the_locations_own_last_part_whole(self):
        got = statement.location_copy_target("/out/a b$x\n-s", "/real", "/real", True)
        self.assertEqual(got, "/real/a b$x\n-s")


class TheNotice(unittest.TestCase):
    REFERENCES = [{"name": "runbook", "path": "/refs/run book$1.md"}]

    def given(self, instruction, expects, location="/out/s.json", references=()):
        return notice.with_notice(instruction, expects, location, SCHEMA, references)

    def test_a_kind_that_expects_a_statement_gets_the_notice_after_its_instruction(self):
        got = self.given("do it", True)
        self.assertTrue(got.startswith("do it\n\n"))
        self.assertIn(f"Shuttle notice, version {fixed.NOTICE_VERSION}", got)
        self.assertIn("/out/s.json", got)
        self.assertIn("cannot commit in the place", got)
        for field in SCHEMA["fields"]:
            self.assertIn(f"- {field['name']}:", got)

    def test_a_kind_that_expects_none_gets_the_notice_without_its_statement_part(self):
        for location in ("/out/s.json", None):
            with self.subTest(location=location):
                got = self.given("do it", False, location=location)
                self.assertTrue(got.startswith("do it\n\n"))
                self.assertIn(f"Shuttle notice, version {fixed.NOTICE_VERSION}", got)
                self.assertIn("cannot commit in the place", got)
                self.assertNotIn("statement", got)
                self.assertNotIn("/out/s.json", got)
        got = self.given("x", False, references=self.REFERENCES)
        self.assertIn("- runbook: /refs/run book$1.md", got)
        self.assertIn("A reference wins over a file of the same name in the place.", got)

    def test_a_kind_that_expects_none_and_has_no_instruction_gets_the_notice_alone(self):
        got = self.given(None, False)
        self.assertTrue(got.startswith(f"Shuttle notice, version {fixed.NOTICE_VERSION}"))
        self.assertIn("cannot commit in the place", got)

    def test_a_kind_that_expects_a_statement_and_has_no_instruction_gets_the_notice_alone(self):
        got = self.given(None, True)
        self.assertTrue(got.startswith(f"Shuttle notice, version {fixed.NOTICE_VERSION}"))

    def test_references_are_named_with_their_paths_and_win_over_the_place(self):
        got = self.given("x", True, references=self.REFERENCES)
        self.assertIn("- runbook: /refs/run book$1.md", got)
        self.assertIn("A reference wins over a file of the same name in the place.", got)
        self.assertNotIn("A reference wins", self.given("x", True))

    def test_the_notice_for_a_statement_written_as_a_file_is_the_words_it_always_had(self):
        got = self.given("do it", True)
        self.assertIn("Write your statement as one JSON file at this exact path: /out/s.json", got)
        self.assertIn(
            "Execution keeps the file exactly as you wrote it and never changes or completes it.",
            got,
        )
        self.assertEqual(got, notice.with_notice("do it", True, "/out/s.json", SCHEMA, [], "file"))

    def test_the_notice_for_a_statement_given_as_the_final_message_says_so_and_names_no_path(self):
        got = notice.with_notice("do it", True, "/out/s.json", SCHEMA, [], "reply")
        self.assertIn("as your final message", got)
        self.assertIn("nothing else in the message", got)
        self.assertNotIn("/out/s.json", got)
        self.assertNotIn("one JSON file", got)
        for field in SCHEMA["fields"]:
            self.assertIn(f"- {field['name']}:", got)
        self.assertIn("cannot commit in the place", got)

    def test_a_kind_that_expects_no_statement_gets_the_same_notice_whichever_way_one_arrives(self):
        self.assertEqual(
            notice.with_notice("x", False, None, SCHEMA, [], "reply"), self.given("x", False, None)
        )

    def test_the_notice_is_the_same_text_every_time(self):
        self.assertEqual(self.given("x", True), self.given("x", True))

    def test_the_notice_holds_nothing_of_a_place(self):
        # The place is optional and may be absent: no sentence of the notice depends on it.
        self.assertNotIn("None", self.given("x", True))
