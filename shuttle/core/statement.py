"""The statement an executor leaves: its shape, judged by value against the schema as data.

The schema is the data file `shuttle/data/statement_schema.json`, read by the shell and handed
in; this module holds no copy of it, so a second program that reads the file judges the same
way. Execution judges the shape and never the content: it does not read the claim as anything
but a word of the list, and it never rewrites, completes or tidies the statement.
"""

import json
from collections.abc import Mapping
from typing import Any, TypedDict

# What the receipt's statement state holds, besides the state "none" (nothing was left).
RIGHT_SHAPE = "right_shape"
WRONG_SHAPE = "wrong_shape"


class Examined(TypedDict):
    problems: list[str]  # empty when the shape is right
    claim: str | None  # the claim word, only when the shape is right


def kept_name(request_id: str) -> str:
    """The name of the kept copy of the statement, beside the records. A request id holds no
    dot, so no record's name (`<id>.<kind>.json`) can be this one."""
    return f"{request_id}.statement.kept"


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise ValueError(f"the key {key!r} is there twice")
        found[key] = value
    return found


def _check(value: object, spec: Mapping[str, Any], where: str, problems: list[str]) -> None:
    kind = spec["kind"]
    if kind == "word":
        if not isinstance(value, str) or value not in spec["words"]:
            problems.append(f"{where} must be one of {spec['words']}")
    elif kind == "text":
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{where} must be text that is not blank")
    elif kind == "list":
        if not isinstance(value, list):
            problems.append(f"{where} must be a list")
            return
        for number, item in enumerate(value):
            _check(item, spec["items"], f"{where}[{number}]", problems)
    else:
        _check_object(value, spec, where, problems)


def _check_object(value: object, spec: Mapping[str, Any], where: str, problems: list[str]) -> None:
    if not isinstance(value, dict):
        problems.append(f"{where} must be an object")
        return
    names = [field["name"] for field in spec["fields"]]
    prefix = f"{where}." if where else ""
    problems.extend(f"{prefix}{name} is missing" for name in names if name not in value)
    problems.extend(f"{prefix}{name} is not a field of it" for name in value if name not in names)
    for field in spec["fields"]:
        if field["name"] in value:
            _check(value[field["name"]], field, prefix + field["name"], problems)


def examine(data: bytes, schema: Mapping[str, Any]) -> Examined:
    """The shape of a statement's bytes against the schema, and its claim when the shape is right.

    The bytes must be UTF-8 holding one JSON object, no key twice. Every problem found is listed,
    in the order of the schema.
    """
    try:
        parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (ValueError, RecursionError) as error:
        return {"problems": [f"it is not JSON ({type(error).__name__}: {error})"], "claim": None}
    problems: list[str] = []
    _check_object(parsed, {"fields": schema["fields"]}, "", problems)
    claim = parsed.get("claim") if not problems else None
    return {"problems": problems, "claim": claim if isinstance(claim, str) else None}
