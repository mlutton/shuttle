"""Lists the guard files a pull request changes, as a job-summary section.

Usage: guards.py <base commit>   (run inside the pull request's tree)
Exit codes: 0 listed (or none changed); 1 it could not be produced, whatever the cause
(git could not compare the commits, an unexpected error; the output is then one line saying
so); 2 misuse. Names are kept as str with surrogateescape and printed escaped.
"""

# These scripts read files and run tools; the ban on that is for the package, not for them.
# ruff: noqa: TID251

import ast
import os
import subprocess
import sys
import traceback
from typing import Any

from names import escape_name, fenced

# tests/hostile/ holds the attack lists the rule tests loop (a deleted row is a weaker guard), so
# it is a guard folder and a file put there needs no listing by hand. The files named below are
# the tests that are themselves rules, or that loop a table: a test file that imports from
# `hostile` must be named here (tests/by_value/test_check_helpers.py pins that).
GUARD_FOLDERS = ("checks/", ".githooks/", ".github/", ".claude/agents/", "tests/hostile/")
GUARD_FILES = (
    "pyproject.toml",
    "requirements-dev.txt",
    "tests/by_value/test_rules.py",
    "AGENTS.md",
    "CLAUDE.md",
    "CODING_STANDARDS.md",
    "docs/process.md",
    "tests/by_value/test_agent_documents.py",
    "tests/by_value/test_check_helpers.py",
    "tests/by_value/test_name_functions.py",
    "tests/by_value/test_names_table.py",
    "tests/command/test_hostile_tables.py",
    "tests/command/test_fix_mode.py",
    "tests/command/test_base_check.py",
    "tests/command/test_check_script.py",
    "tests/command/test_hook.py",
    "tests/by_value/test_report.py",
    "tests/command/test_report.py",
)
# The attack lists: table name, file, the variable holding the rows, and (for tables whose rows
# are tuples) the fields of a row in order.
TABLES = {
    "names": "tests/hostile/names_table.py",
    "imports": "tests/hostile/imports_table.py",
    "suppressions": "tests/hostile/suppressions_table.py",
}
TABLE_VARIABLES = {"names": "NAMES", "imports": "IMPORTS", "suppressions": "SUPPRESSIONS"}
TABLE_FIELDS = {
    "imports": ("label", "source", "folder", "caught_by", "note", "problem"),
    "suppressions": ("label", "source", "ruff_honours", "rule_test_refuses"),
}
KNOWN_GAP = "known gap"
NONE_CHANGED = "No guard files changed in this pull request."
COULD_NOT_LIST = "The guard file listing could not be produced; see the job log for why."


def parse_name_status(raw: bytes) -> list[tuple[str, str]]:
    """The output of `git diff --name-status --no-renames -z`: status, path, status, path..."""
    fields = [os.fsdecode(field) for field in raw.split(b"\0")]
    if fields and fields[-1] == "":
        fields.pop()
    return list(zip(fields[0::2], fields[1::2], strict=True))


def is_guard(path: str) -> bool:
    return path.startswith(GUARD_FOLDERS) or path in GUARD_FILES


def what_happened(status: str) -> str:
    return {"A": "added", "D": "deleted"}.get(status[:1], "changed")


def guard_changes(changes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The (what happened, path) of each guard file among the changes, in path order."""
    return sorted(
        ((what_happened(status), path) for status, path in changes if is_guard(path)),
        key=lambda change: change[1],
    )


def render_summary(guards: list[tuple[str, str]]) -> str:
    """Markdown. Names sit in one fenced block, escaped to one line each, so no name can
    close the block or start markup: the fence is longer than any run of backticks inside."""
    if not guards:
        return NONE_CHANGED + "\n"
    lines = [f"{what:<8}{escape_name(path)}" for what, path in guards]
    return (
        "## This pull request changes the guardrails\n\n"
        "The reviewer should read these files "
        "(one per line; a backslash or control character in a name is shown as an escape):\n\n"
        + fenced(lines)
    )


def _evaluate(node: ast.expr, env: dict[str, Any]) -> Any:
    """The value of a table's expression: constants, earlier constants by name, tuples, lists,
    dicts, and `*` and `+` over text, numbers and those. Nothing else is evaluated (the table
    files are data; reading them must not run them)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, ast.Tuple | ast.List):
        return [_evaluate(e, env) for e in node.elts]
    if isinstance(node, ast.Dict) and all(k is not None for k in node.keys):
        return {
            _evaluate(k, env): _evaluate(v, env)
            for k, v in zip(node.keys, node.values, strict=True)
            if k is not None
        }
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Mult):
        left, right = _evaluate(node.left, env), _evaluate(node.right, env)
        return left + right if isinstance(node.op, ast.Add) else left * right
    raise ValueError(f"line {getattr(node, 'lineno', '?')}: not plain data")


def _environment(text: str) -> dict[str, Any]:
    """The assignments of plain data in a table file (a docstring is allowed, nothing else)."""
    env: dict[str, Any] = {}
    for node in ast.parse(text).body:
        target = (
            node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        )
        if isinstance(target, ast.Name) and isinstance(node, ast.Assign):
            env[target.id] = _evaluate(node.value, env)
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            raise ValueError(f"line {node.lineno}: not an assignment of plain data")
    return env


def load_table(table: str, text: str) -> list[dict[str, Any]]:
    """The rows of a table file, as dicts with a "label" and a "gaps" (what is marked as a known
    gap: function key to reason; for the import table, a row whose note says "known gap").
    ValueError, saying why, when the text is not a table of plain data."""
    try:
        raw = _environment(text)[TABLE_VARIABLES[table]]
        rows = [
            dict(zip(TABLE_FIELDS[table], row, strict=False)) if table in TABLE_FIELDS else row
            for row in raw
        ]
        for row in rows:
            if table == "imports" and KNOWN_GAP in row.get("note", ""):
                row["gaps"] = {"import form": row["note"]}
            row.setdefault("gaps", {})
            str(row["label"])
        return rows
    except (SyntaxError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{type(error).__name__}: {error}") from error


def _gaps(rows: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    return {(r["label"], k): str(v) for r in rows for k, v in r["gaps"].items()}


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(
        f for f in before.keys() | after.keys() if f != "gaps" and before.get(f) != after.get(f)
    )


def _relabelled(
    before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Old label to new label for each row removed whose content is equal in every field but the
    label to a row added; each added row is matched once."""
    taken: set[str] = set()
    pairs: dict[str, str] = {}
    for old in (label for label in before if label not in after):
        for new in (label for label in after if label not in before and label not in taken):
            if {**before[old], "label": None} == {**after[new], "label": None}:
                pairs[old] = new
                taken.add(new)
                break
    return pairs


def _mark_lines(
    table: str,
    old: list[dict[str, Any]] | None,
    new: list[dict[str, Any]] | None,
    relabelled: dict[str, str],
) -> tuple[list[str], list[str]]:
    """The known-gap lines of one table: (marks added or closed, every mark in force at the
    head). A mark follows its row when the row was relabelled; one that went with a removed row
    is not called closed."""
    carried = {
        (relabelled.get(label, label), key): reason
        for (label, key), reason in _gaps(old or []).items()
    }
    held = _gaps(new or [])
    present = {r["label"] for r in new or []}
    lines: list[str] = []
    standing: list[str] = []
    for (label, key), reason in held.items():
        if carried.get((label, key)) != reason:
            lines.append(f"{table}: new known gap: {label}: {key}: {reason}")
        standing.append(f"{table}: known gap: {label}: {key}: {reason}")
    for (label, key), reason in carried.items():
        if label in present and (label, key) not in held:
            lines.append(f"{table}: known gap closed: {label}: {key}: {reason}")
    return lines, standing


def _table_lines(
    table: str, old: list[dict[str, Any]] | None, new: list[dict[str, Any]] | None
) -> tuple[list[str], list[str]]:
    """What changed and what stands, for one table that could be read at both ends (None: not
    there). The first list is the pull request's doing; the second every known-gap mark in
    force at the head."""
    lines: list[str] = []
    before = {r["label"]: r for r in old or []}
    after = {r["label"]: r for r in new or []}
    renamed = _relabelled(before, after)
    if new is None:
        lines.append(f"{table}: the table is gone from the head")
    for label in before:
        if label in renamed:
            lines.append(f"{table}: row relabelled: {label} \u2192 {renamed[label]}")
        elif label not in after:
            lines.append(f"{table}: row removed: {label}")
        elif fields := _changed_fields(before[label], after[label]):
            lines.append(f"{table}: row changed: {label} ({', '.join(fields)})")
    added = len(after.keys() - before.keys()) - len(renamed)
    if old is None:
        lines.append(f"{table}: no table at the base; all {added} rows are new")
    elif added:
        lines.append(f"{table}: {added} rows added")
    marks, standing = _mark_lines(table, old, new, renamed)
    lines += marks
    return lines, standing


def table_report(
    base: dict[str, list[dict[str, Any]] | str | None],
    head: dict[str, list[dict[str, Any]] | str | None],
) -> tuple[list[str], list[str]]:
    """What a pull request does to the attack lists, from the tables at the base and at the
    head, as (changes, standing), one line each. A table is its rows, or text saying why it
    could not be read, or None when it is not there. The changes name the table and label of
    each row removed, relabelled (old and new label) or changed (which fields), the count of
    rows added, and each known-gap mark added, whose reason changed or closed (its row still there). The standing lines are
    every known-gap mark in force at the head, every time."""
    changes: list[str] = []
    standing: list[str] = []
    for table in TABLES:
        old, new = base.get(table), head.get(table)
        for side, value in (("base", old), ("head", new)):
            if isinstance(value, str):
                changes.append(f"{table}: the table at the {side} could not be read: {value}")
        if not isinstance(old, str) and not isinstance(new, str) and (old or new) is not None:
            more, held = _table_lines(table, old, new)
            changes += more
            standing += held
        elif isinstance(old, str) and isinstance(new, list):
            standing += _table_lines(table, None, new)[1]
    return changes, standing


def render_tables(changes: list[str], standing: list[str]) -> str:
    """Markdown for table_report's lines, escaped, each group in one fenced block under its own
    heading; the first only when the pull request did something to a table, the second only
    when a mark stands; nothing for neither."""
    text = ""
    if changes:
        text += (
            "\n## What this pull request does to the hostile-case tables\n\n"
            "Rows removed, relabelled or changed, rows added, marks added or closed, one per line:\n\n"
            + fenced([escape_name(line) for line in changes])
        )
    if standing:
        text += (
            "\n## Known gaps in the tables, as they stand\n\n"
            "Each failure the tests excuse, with its reason, one per line:\n\n"
            + fenced([escape_name(line) for line in standing])
        )
    return text


def read_tables(ref: str) -> dict[str, list[dict[str, Any]] | str | None]:
    """The tables as committed at ref: rows, or why one could not be read, or None when the
    commit has no such file."""
    found: dict[str, list[dict[str, Any]] | str | None] = {}
    for table, path in TABLES.items():
        shown = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True)
        if shown.returncode != 0:
            found[table] = None
            continue
        try:
            found[table] = load_table(table, shown.stdout.decode("utf-8", "surrogateescape"))
        except ValueError as error:
            found[table] = str(error)
    return found


def run(base: str) -> int:
    diff = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", "-z", base, "HEAD"],
        capture_output=True,
    )
    if diff.returncode != 0:
        sys.stderr.buffer.write(diff.stderr)
        print(COULD_NOT_LIST)
        return 1
    sys.stdout.write(render_summary(guard_changes(parse_name_status(diff.stdout))))
    sys.stdout.write(render_tables(*table_report(read_tables(base), read_tables("HEAD"))))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: guards.py <base commit>", file=sys.stderr)
        return 2
    try:
        return run(argv[1])
    except Exception:  # an empty summary must never pass for a listing
        traceback.print_exc()
        print(COULD_NOT_LIST)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
