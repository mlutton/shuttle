"""By value: validating the input document."""
import copy
import unittest

from shuttle import core

GOOD = {
    "format_version": 1,
    "request_id": "req-1",
    "records_location": "/some/records",
    "executor": {
        "driver": "command",
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
        })

    def test_refusals_that_still_form_a_header(self):
        bad_settings = copy.deepcopy(GOOD)
        bad_settings["executor"]["settings"]["extra"] = 1
        no_args = copy.deepcopy(GOOD)
        del no_args["executor"]["settings"]["arguments"]
        other_driver = copy.deepcopy(GOOD)
        other_driver["executor"]["driver"] = "codex"
        cases = [
            ("unknown field", with_change(surprise=1), "unknown_field"),
            ("other version", with_change(format_version=2), "unknown_format_version"),
            ("no version", without("format_version"), "unknown_format_version"),
            ("no executor", without("executor"), "missing_setting"),
            ("other driver", other_driver, "unknown_executor"),
            ("unknown setting", bad_settings, "unknown_setting"),
            ("missing setting", no_args, "missing_setting"),
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
