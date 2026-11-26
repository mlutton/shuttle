"""By value: the parts of the input document that carry the refusal checks' data.

The instruction and its hash, references, gates, the statement location and reach are parts of
the document. Their shape is checked by `validate_document`; what they hold is judged by the
checks in test_refusals.py.
"""

import copy
import unittest

from shuttle.core import decisions as core

GOOD = {
    "format_version": 1,
    "request_id": "req-1",
    "records_location": "/some/records",
    "thread": "t-1",
    "round": 2,
    "kind": "plain",
    "time_limit_seconds": 30,
    "executor": {"name": "command", "settings": {"command": "python3", "arguments": []}},
}
HASH = "a" * 64
REFERENCE = {
    "name": "runbook",
    "path": "/refs/runbook.md",
    "hash": HASH,
    "size": 3,
    "hash_source": "caller",
}
GATE = {"name": "quota", "command": "check-quota", "arguments": [], "limit_seconds": 5}


def with_change(**top):
    doc = copy.deepcopy(GOOD)
    doc.update(top)
    return doc


class TheDocumentCarriesTheCheckedParts(unittest.TestCase):
    ACCEPTED = (
        ("instruction and its hash", {"instruction": "do it", "instruction_hash": HASH}),
        ("a reference", {"references": [REFERENCE]}),
        ("no references", {"references": []}),
        ("a gate", {"gates": [GATE]}),
        ("no gates", {"gates": []}),
        ("a statement location", {"statement_location": "/out/statement.json"}),
        ("an empty reach", {"reach": {}}),
        ("reach, which the checks refuse by its content", {"reach": {"read": ["/etc"]}}),
    )

    def test_each_part_is_accepted_by_the_shape_check(self):
        for label, change in self.ACCEPTED:
            with self.subTest(label):
                got = core.validate_document(with_change(**change))
                self.assertIsNone(got["refusal"], got["problem"])

    BAD = (
        ("instruction not text", {"instruction": 5, "instruction_hash": HASH}, "missing_setting"),
        ("references not a list", {"references": "runbook"}, "missing_setting"),
        ("a reference not an object", {"references": ["runbook"]}, "missing_setting"),
        (
            "a reference without a hash",
            {"references": [{"name": "r", "path": "/r", "size": 1, "hash_source": "caller"}]},
            "missing_setting",
        ),
        (
            "a reference with an unknown field",
            {"references": [dict(REFERENCE, extra=1)]},
            "unknown_field",
        ),
        ("gates not a list", {"gates": "quota"}, "missing_setting"),
        (
            "a gate without a limit",
            {"gates": [{"name": "q", "command": "c", "arguments": []}]},
            "missing_setting",
        ),
        ("a gate with an unknown field", {"gates": [dict(GATE, extra=1)]}, "unknown_field"),
        ("a gate limit of zero", {"gates": [dict(GATE, limit_seconds=0)]}, "missing_setting"),
        ("a statement location not text", {"statement_location": 5}, "missing_setting"),
    )

    def test_a_part_of_the_wrong_shape_is_refused_at_the_input_check_with_the_header_kept(self):
        for label, change, reason in self.BAD:
            with self.subTest(label):
                got = core.validate_document(with_change(**change))
                self.assertEqual(got["refusal"], {"reason": reason, "step": "input_check"})
                self.assertEqual(got["header_source"]["request_id"], "req-1")

    def test_a_document_without_a_request_id_still_cannot_form_a_header(self):
        doc = copy.deepcopy(GOOD)
        del doc["request_id"]
        self.assertIsNone(core.validate_document(doc)["header_source"])


if __name__ == "__main__":
    unittest.main()
