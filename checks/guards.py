"""Lists the guard files a pull request changes, as a job-summary section.

Usage: guards.py <base commit>   (run inside the pull request's tree)
Exit codes: 0 listed (or none changed); 1 git could not compare the commits (the summary
then says so); 2 misuse.
"""

# These scripts read files and run tools; the ban on that is for the package, not for them.
# ruff: noqa: TID251

import os
import subprocess
import sys

from names import escape_name

GUARD_FOLDERS = ("checks/", ".githooks/", ".github/")
GUARD_FILES = ("pyproject.toml", "requirements-dev.txt", "tests/by_value/test_rules.py")
NONE_CHANGED = "No guard files changed in this pull request."
COULD_NOT_LIST = "The guard file listing could not be produced: git could not compare the commits."


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


def longest_run(text: str, char: str) -> int:
    best = run = 0
    for c in text:
        run = run + 1 if c == char else 0
        best = max(best, run)
    return best


def render_summary(guards: list[tuple[str, str]]) -> str:
    """Markdown. Names sit in one fenced block, escaped to one line each, so no name can
    close the block or start markup: the fence is longer than any run of backticks inside."""
    if not guards:
        return NONE_CHANGED + "\n"
    lines = [f"{what:<8}{escape_name(path)}" for what, path in guards]
    fence = "`" * max(3, longest_run("\n".join(lines), "`") + 1)
    return (
        "## This pull request changes the guardrails\n\n"
        "The reviewer should read these files "
        "(one per line; a backslash or control character in a name is shown as an escape):\n\n"
        + fence
        + "\n"
        + "\n".join(lines)
        + "\n"
        + fence
        + "\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: guards.py <base commit>", file=sys.stderr)
        return 2
    diff = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", "-z", argv[1], "HEAD"],
        capture_output=True,
    )
    if diff.returncode != 0:
        sys.stderr.write(os.fsdecode(diff.stderr))
        print(COULD_NOT_LIST)
        return 1
    sys.stdout.write(render_summary(guard_changes(parse_name_status(diff.stdout))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
