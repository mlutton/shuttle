"""The state and value pair every receipt field is.

A field says how its value is known (its state) beside the value itself, so a field's own text
can be the word "none" without being mistaken for the state "none". The four states are in
`fixed.STATES`.
"""

import math
from typing import TypeGuard

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


def plain_json(held: object) -> TypeGuard[JsonValue]:
    """Whether `held` is made only of what JSON holds: text, booleans, finite numbers, lists, and
    dictionaries with text keys. A tuple, a set, bytes, a loop, `nan` and `inf` are not."""
    try:
        return _plain(held)
    except RecursionError:
        return False


def _plain(held: object) -> bool:
    if isinstance(held, float):
        return math.isfinite(held)
    if held is None or isinstance(held, str | bool | int):
        return True
    if isinstance(held, list):
        return all(_plain(item) for item in held)
    if isinstance(held, dict):
        return all(isinstance(key, str) and _plain(item) for key, item in held.items())
    return False


def observed(held: object) -> Pair:
    """The pair for something execution observed, whatever it is; it never gives a pair the
    builder refuses.

    Nothing (None, empty text, an empty list or dictionary): none, since execution looked and
    there was nothing. Anything JSON cannot hold, or a number that is not finite: cannot tell,
    for this field alone. Anything else: that value.
    """
    if held is None:
        return none()
    if not plain_json(held):
        return cannot_tell()
    if held in _NOTHING_HELD:
        return none()
    return value(held)


def of_text(text: str) -> Pair:
    """A pair from text that uses "none" and "cannot tell" for those states (a decision's text);
    any other text is observed."""
    if text == fixed.NONE:
        return none()
    if text == fixed.CANNOT_TELL:
        return cannot_tell()
    return observed(text)


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
    if not plain_json(content):
        return "state 'value' holds something JSON cannot hold (or a number that is not finite)"
    return None
