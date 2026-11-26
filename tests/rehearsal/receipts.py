"""Reading a receipt in tests: each field's pair as the plain text it says.

`flat(receipt)` turns every pair of state and value into the value when the state is "value", and
into the state's own word ("none", "cannot tell", "not built") otherwise: the receipt as it was
before every field became a pair. It cannot tell the state "none" (or "cannot tell", "not built")
from a value that is the same word, so a test that cares which one a field holds reads the pair
directly (see `EveryFieldHasTheStateTheRunEarnedIt` in tests/by_value/test_receipt.py).
"""


def flat(receipt):
    return {
        group: {name: _plain(held) for name, held in fields.items()}
        for group, fields in receipt.items()
    }


def _plain(held):
    return held["value"] if held["state"] == "value" else held["state"]
