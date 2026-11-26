"""Reading a receipt in tests: each field's pair as the plain text it says.

`flat(receipt)` turns every pair of state and value into the value when the state is "value", and
into the state's own word ("none", "cannot tell", "not built") otherwise: the receipt as it was
before every field became a pair. Tests that are about the pairs themselves read them directly.
"""


def flat(receipt):
    return {
        group: {name: _plain(held) for name, held in fields.items()}
        for group, fields in receipt.items()
    }


def _plain(held):
    return held["value"] if held["state"] == "value" else held["state"]
