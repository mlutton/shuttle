"""By value: validating the input document."""
import copy
import unittest

from shuttle import core

GOOD = {
    "format_version": 1,
    "request_id": "req-1",
    "records_location": "/some/records",
    "thread": "t-1",
    "round": 2,
    "kind": "plain",
    "time_limit_seconds": 30,
    "executor": {
        "name": "command",
        "settings": {"command": "python3", "arguments": ["script.py"]},
    },
}


def with_change(**top):
    doc = copy.deepcopy(GOOD)
    doc.update(top)
    return doc


def without(key):
    doc = copy.deepcopy(GOOD)
    del doc[key]
    return doc


class ValidateDocument(unittest.TestCase):
    def test_a_good_document_has_a_header_source_and_no_refusal(self):
        got = core.validate_document(GOOD)
        self.assertIsNone(got["refusal"])
        self.assertEqual(got["header_source"], {
            "request_id": "req-1",
            "records_location": "/some/records",
            "executor_name": "command",
            "thread": "t-1",
            "round": 2,
            "kind": "plain",
            "parent_session": "none",
            "asked_by": "none",
        })

    def test_optional_header_fields_are_carried_when_given(self):
        got = core.validate_document(with_change(parent_session="p-9", asked_by="someone"))
        self.assertIsNone(got["refusal"])
        self.assertEqual(got["header_source"]["parent_session"], "p-9")
        self.assertEqual(got["header_source"]["asked_by"], "someone")

    def test_small_and_large_usable_time_limits_are_accepted(self):
        for limit in (0.001, 1, 30.5, 86400, 10 ** 8):
            with self.subTest(limit):
                self.assertIsNone(core.validate_document(with_change(time_limit_seconds=limit))["refusal"])

    def test_a_good_document_may_name_environment_variables(self):
        self.assertIsNone(core.validate_document(with_change(environment=["A_B", "C"]))["refusal"])

    def test_refusals_that_still_form_a_header(self):
        bad_settings = copy.deepcopy(GOOD)
        bad_settings["executor"]["settings"]["extra"] = 1
        no_args = copy.deepcopy(GOOD)
        del no_args["executor"]["settings"]["arguments"]
        other_executor = copy.deepcopy(GOOD)
        other_executor["executor"]["name"] = "codex"
        cases = [
            ("unknown field", with_change(surprise=1), "unknown_field"),
            ("other version", with_change(format_version=2), "unknown_format_version"),
            ("no version", without("format_version"), "unknown_format_version"),
            ("no executor", without("executor"), "missing_setting"),
            ("other executor", other_executor, "unknown_executor"),
            ("unknown setting", bad_settings, "unknown_setting"),
            ("missing setting", no_args, "missing_setting"),
            ("version true", with_change(format_version=True), "unknown_format_version"),
            ("version 1.0", with_change(format_version=1.0), "unknown_format_version"),
            ("version text", with_change(format_version="1"), "unknown_format_version"),
            ("no time limit", without("time_limit_seconds"), "no_time_limit"),
            ("zero time limit", with_change(time_limit_seconds=0), "no_time_limit"),
            ("negative time limit", with_change(time_limit_seconds=-5), "no_time_limit"),
            ("time limit true", with_change(time_limit_seconds=True), "no_time_limit"),
            ("time limit text", with_change(time_limit_seconds="30"), "no_time_limit"),
            ("time limit a huge integer", with_change(time_limit_seconds=10 ** 400), "no_time_limit"),
            ("time limit infinity", with_change(time_limit_seconds=float("inf")), "no_time_limit"),
            ("time limit not a number", with_change(time_limit_seconds=float("nan")), "no_time_limit"),
            ("time limit the clock cannot use", with_change(time_limit_seconds=1e30), "no_time_limit"),
            ("environment not a list", with_change(environment="PATH"), "missing_setting"),
            ("environment name not text", with_change(environment=[1]), "missing_setting"),
            ("environment name with an equals sign", with_change(environment=["A=b"]), "missing_setting"),
        ]
        for name, doc, reason in cases:
            with self.subTest(name):
                got = core.validate_document(doc)
                self.assertEqual(got["refusal"], {"reason": reason, "step": "input_check"})
                self.assertEqual(got["header_source"]["request_id"], "req-1")
                self.assertTrue(got["problem"])

    def test_documents_too_broken_to_form_a_header_have_no_header_source(self):
        cases = [
            ("not an object", ["a"]),
            ("no request id", without("request_id")),
            ("request id not text", with_change(request_id=7)),
            ("request id with a slash", with_change(request_id="../x")),
            ("empty request id", with_change(request_id="")),
            ("no records location", without("records_location")),
            ("no thread", without("thread")),
            ("no round", without("round")),
            ("round is a boolean", with_change(round=True)),
            ("round is text", with_change(round="2")),
            ("no kind", without("kind")),
            ("parent session not text", with_change(parent_session=3)),
            ("asked by not text", with_change(asked_by=["x"])),
        ]
        for name, doc in cases:
            with self.subTest(name):
                got = core.validate_document(doc)
                self.assertIsNone(got["header_source"])
                self.assertTrue(got["problem"])

    def test_validation_leaves_the_document_unchanged(self):
        doc = with_change(surprise=1)
        before = copy.deepcopy(doc)
        core.validate_document(doc)
        self.assertEqual(doc, before)


class ParseCommandLine(unittest.TestCase):
    def test_run_with_one_path(self):
        self.assertEqual(core.parse_command_line(["run", "doc.json"]), {"form": "run", "document_path": "doc.json"})

    def test_other_forms_are_refused_in_one_line(self):
        for form in ("check", "stop", "status"):
            with self.subTest(form):
                got = core.parse_command_line([form, "x"])
                self.assertEqual(got["refusal"].count("\n"), 0)
                self.assertIn(form, got["refusal"])

    def test_anything_else_is_refused(self):
        for argv in ([], ["run"], ["run", "a", "b"], ["frob", "x"]):
            with self.subTest(argv):
                self.assertIn("refusal", core.parse_command_line(argv))


if __name__ == "__main__":
    unittest.main()
