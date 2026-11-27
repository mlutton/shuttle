"""The notice execution adds after the instruction of every kind.

One fixed, versioned text. Its statement part (where and how to write the statement) is there only
for a kind that expects a statement; its references part (where each reference is found, and that
a reference wins over a file of the same name in the place) only when the document has references;
its line that the executor cannot commit in the place always. The words are fixed; only the facts
(the location, the references, the fields of the schema) are filled in. A tool that gives its
statement as its final message is told that instead of being given a path. The place is not named: the
notice says "the place" and nothing depends on where it is.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from shuttle.core import fixed
from shuttle.core.shapes import StatementArrival


def _describe(spec: Mapping[str, Any]) -> str:
    kind = spec["kind"]
    if kind == "word":
        return "one of: " + ", ".join(spec["words"])
    if kind == "text":
        return "text that is not blank"
    if kind == "list":
        return "a list (it may be empty) of " + _describe(spec["items"])
    names = ", ".join(field["name"] for field in spec["fields"])
    return f"an object with exactly the fields {names}"


def _field_lines(fields: Sequence[Mapping[str, Any]], indent: str) -> list[str]:
    lines: list[str] = []
    for field in fields:
        lines.append(f"{indent}- {field['name']}: {_describe(field)}. {field.get('about', '')}")
        inner = field.get("items", {})
        if inner.get("kind") == "object":
            lines += _field_lines(inner["fields"], indent + "    ")
    return lines


def notice(
    statement_location: str | None,
    schema: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
    arrives: StatementArrival = "file",
) -> str:
    """The notice's text. `references` are the document's, each with a name and a path. A tool
    that cannot write at the statement location gives its statement as its final message
    (`arrives` is "reply"), and is told so instead of being given a path."""
    lines = [f"Shuttle notice, version {fixed.NOTICE_VERSION}"]
    if statement_location is not None and arrives == "reply":
        lines += [
            "",
            "Give your statement as your final message: one JSON object with exactly these "
            "fields, and no others, and nothing else in the message (no words before or after "
            "it, no code fence):",
            *_field_lines(schema["fields"], "  "),
            "Execution keeps your final message exactly as you wrote it and never changes or "
            "completes it.",
        ]
    elif statement_location is not None:
        lines += [
            "",
            f"Write your statement as one JSON file at this exact path: {statement_location}",
            "It must be one JSON object with exactly these fields, and no others:",
            *_field_lines(schema["fields"], "  "),
            "Execution keeps the file exactly as you wrote it and never changes or completes it.",
        ]
    if references:
        lines += ["", "References are read-only for you. Each is found at this path:"]
        lines += [f"- {reference['name']}: {reference['path']}" for reference in references]
        lines.append("A reference wins over a file of the same name in the place.")
    lines += ["", "You cannot commit in the place; leave your changes as files."]
    return "\n".join(lines) + "\n"


def with_notice(
    instruction: str | None,
    expects_statement: bool,
    statement_location: str | None,
    schema: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
    arrives: StatementArrival = "file",
) -> str:
    """The instruction the executor is given: the caller's, then the notice. A kind that expects
    no statement gets the notice without its statement part; with no instruction either, the
    notice alone."""
    text = notice(statement_location if expects_statement else None, schema, references, arrives)
    return text if instruction is None else instruction + "\n\n" + text
