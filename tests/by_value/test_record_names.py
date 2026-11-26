"""By value: the names of the records beside one request id.

Every kind of record has its name reserved in the one list of fixed values (the stop record and
the liveness file included, though only the request and outcome records are written), the names
are made in one place, and no request id can make one kind's name another kind's, or a record's
name a temporary name.
"""

import itertools
import unittest

from shuttle.core import decisions as core
from shuttle.core import fixed

# Ids that look like what they must not be mistaken for, beside every one-character and every
# two-character id the alphabet allows.
LOOK_ALIKES = (
    "req-1",
    "request",
    "outcome",
    "stop",
    "liveness",
    "tmp-1",
    "a-request",
    "x_stop",
    "-",
    "_",
    "json",
)


def every_id():
    """The look-alikes and every id of one or two characters the alphabet allows, each once.

    A name is `<id>.<kind>.json` and an id holds no dot, so what holds for the shortest ids
    and the look-alikes holds for any id: the test above it states the reason.
    """
    shortest = (
        "".join(c) for n in (1, 2) for c in itertools.product(fixed.ID_CHARACTERS, repeat=n)
    )
    yield from dict.fromkeys((*LOOK_ALIKES, *shortest))


class TheKindsAreOnTheList(unittest.TestCase):
    def test_the_four_kinds_are_the_fixed_list(self):
        self.assertEqual(fixed.RECORD_KINDS, ("request", "outcome", "stop", "liveness"))

    def test_a_name_is_made_for_every_kind_on_the_list(self):
        for kind in fixed.RECORD_KINDS:
            with self.subTest(kind):
                self.assertEqual(core.record_name("req-1", kind), f"req-1.{kind}.json")

    def test_a_name_is_refused_for_a_kind_that_is_not_on_the_list(self):
        for kind in ("", "request.json", "Request", "tmp", "stopped"):
            with self.subTest(kind), self.assertRaises(ValueError):
                core.record_name("req-1", kind)


class NoIdMakesOneNameAnother(unittest.TestCase):
    def test_a_request_id_holds_no_dot(self):
        self.assertNotIn(".", fixed.ID_CHARACTERS)

    def test_the_name_of_one_kind_is_never_the_name_of_another_for_any_id(self):
        names = {}
        for request_id in every_id():
            for kind in fixed.RECORD_KINDS:
                name = core.record_name(request_id, kind)
                self.assertNotIn(name, names, f"{request_id!r} {kind}")
                names[name] = (request_id, kind)

    def test_the_id_and_kind_are_read_back_from_the_name(self):
        for request_id in every_id():
            for kind in fixed.RECORD_KINDS:
                name = core.record_name(request_id, kind)
                self.assertEqual(core.read_record_name(name), (request_id, kind), name)

    def test_no_id_makes_a_record_name_equal_to_a_temporary_name(self):
        for request_id in every_id():
            for kind in fixed.RECORD_KINDS:
                name = core.record_name(request_id, kind)
                for process_number in (1, 31337):
                    temporary = core.temporary_name(name, process_number)
                    self.assertNotEqual(temporary, name)
                    self.assertIsNone(core.read_record_name(temporary), temporary)
                    self.assertNotIn(
                        temporary, [core.record_name(request_id, k) for k in fixed.RECORD_KINDS]
                    )

    def test_a_temporary_name_is_the_record_name_then_tmp_then_the_process_number(self):
        self.assertEqual(core.temporary_name("a.request.json", 7), "a.request.json.tmp-7")

    def test_names_that_are_not_records_read_back_as_nothing(self):
        for name in (
            "",
            "request.json",
            "a.json",
            "a.request",
            "a.b.request.json",
            ".request.json",
        ):
            with self.subTest(name):
                self.assertIsNone(core.read_record_name(name))


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
