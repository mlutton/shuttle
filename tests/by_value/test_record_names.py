"""By value: the names of the records beside one request id.

Every kind of record has its name reserved in the one list of fixed values (the stop record and
the liveness file included, though only the request and outcome records are written), the names
are made in one place, and a request id cannot hold a dot.
"""

import unittest

from shuttle.core import decisions as core
from shuttle.core import fixed


class TheKindsAreOnTheList(unittest.TestCase):
    def test_the_four_kinds_are_the_fixed_list(self):
        self.assertEqual(fixed.RECORD_KINDS, ("request", "outcome", "stop", "liveness"))

    def test_every_kind_on_the_list_gives_a_name_of_the_form_id_kind_json(self):
        for kind in fixed.RECORD_KINDS:
            with self.subTest(kind):
                self.assertEqual(core.record_name("req-1", kind), f"req-1.{kind}.json")

    def test_a_name_is_refused_for_a_kind_that_is_not_on_the_list(self):
        for kind in ("", "request.json", "Request", "tmp", "stopped"):
            with self.subTest(kind), self.assertRaises(ValueError):
                core.record_name("req-1", kind)


class AnIdHoldsNoDot(unittest.TestCase):
    def test_a_request_id_holds_no_dot(self):
        self.assertNotIn(".", fixed.ID_CHARACTERS)

    def test_a_temporary_name_is_the_record_name_then_tmp_then_the_process_number(self):
        self.assertEqual(core.temporary_name("a.request.json", 7), "a.request.json.tmp-7")


class AnIdWithADotIsRefused(unittest.TestCase):
    """Pins unchanged behaviour: the existing check refuses a dot, so names stay unambiguous."""

    def test_a_request_id_with_a_dot_forms_no_header(self):
        document = {
            "format_version": fixed.INPUT_VERSION,
            "records_location": "/r",
            "thread": "t",
            "round": 1,
            "kind": "plain",
        }
        for request_id in ("a.b", "a.stop", "a.request.json", ".", "x."):
            with self.subTest(request_id):
                checked = core.validate_document(dict(document, request_id=request_id))
                self.assertIsNone(checked["header_source"])
                self.assertTrue(checked["problem"])


if __name__ == "__main__":
    unittest.main()
