"""The state and value pair every receipt field is.

A field says how its value is known (its state) beside the value itself, so a field's own text
can be the word "none" without being mistaken for the state "none". The four states are in
`fixed.STATES`.
"""

from shuttle.core import fixed
from shuttle.core.shapes import JsonValue, Pair

_NOTHING_HELD: tuple[JsonValue, ...] = ("", [], {})


def value(held: JsonValue) -> Pair:
    """A value: execution looked and found this."""
    return {"state": fixed.VALUE, "value": held}


def none() -> Pair:
    """None: execution looked and there is nothing."""
    return {"state": fixed.NONE, "value": None}


def cannot_tell() -> Pair:
    """Cannot tell: execution could not look."""
    return {"state": fixed.CANNOT_TELL, "value": None}


def not_built() -> Pair:
    """Not built: the step behind this field is still a stand-in."""
    return {"state": fixed.NOT_BUILT, "value": None}


def of_known(held: JsonValue) -> Pair:
    """A value, or none when there is nothing (None)."""
    return none() if held is None else value(held)


def of_text(text: str) -> Pair:
    """A pair from text that uses "none" and "cannot tell" for those states (a decision's text)."""
    if text == fixed.NONE:
        return none()
    if text == fixed.CANNOT_TELL:
        return cannot_tell()
    return value(text)


def text_of(held: object) -> object:
    """The text `of_text` was made from, for a pair read back; anything else is returned as it is."""
    if isinstance(held, dict) and set(held) == {"state", "value"}:
        if held["state"] in (fixed.NONE, fixed.CANNOT_TELL):
            return held["state"]
        if held["state"] == fixed.VALUE:
            return held["value"]
    return held


def problem_with(held: object) -> str | None:
    """Why `held` is not a state and value pair, or None when it is one."""
    if not isinstance(held, dict) or set(held) != {"state", "value"}:
        return "it is not a pair of a state and a value"
    state, content = held["state"], held["value"]
    if not isinstance(state, str) or state not in fixed.STATES:
        return f"its state {state!r} is not one of {list(fixed.STATES)}"
    if state != fixed.VALUE:
        return None if content is None else f"state {state!r} carries a value"
    if content is None or content in _NOTHING_HELD:
        return "state 'value' holds nothing; it must say 'none' or 'cannot tell' instead"
    return None
