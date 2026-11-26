"""./checks/all.sh --fix: ruff's safe fixes and the formatter, then what changed.

Run from the tree's root by all.sh with the interpreter that has ruff. Files that changed
are found by hashing every Python file before and after, keyed by exact path, so ruff only
decides what it touches. A file ruff could not parse or write is named as failed.
Exit codes: 0 finished; 1 ruff could not finish (the last line says so).
"""

# These scripts read files and run tools; the ban on that is for the package, not for them.
# ruff: noqa: TID251

import hashlib
import json
import os
import subprocess
import sys
from typing import Any

from names import escape_name

SUFFIXES = (".py", ".pyi", ".ipynb")
# Diagnostics that are not lint findings: ruff could not write a file, or could not parse it.
COULD_NOT_FINISH = (None, "E902", "invalid-syntax")
SKIPPED_FOLDERS = (".git", "__pycache__", ".ruff_cache", ".mypy_cache")


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths whose content hash differs, or that appear or vanish, in path order."""
    return sorted(
        path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
    )


def failed_from_diagnostics(diagnostics: list[dict[str, Any]], root: str) -> list[str]:
    """Files ruff could not read, parse or write: an I/O error (E902) or a syntax error
    (no rule code)."""
    return sorted(
        {
            os.path.relpath(str(d["filename"]), root)
            for d in diagnostics
            if d.get("code") in COULD_NOT_FINISH
        }
    )


def failed_from_format_output(output: str, known: list[str]) -> list[str]:
    """Files the formatter reported it could not write or parse, matched against known paths
    (a name is not parsed out of the message, so a name with odd characters is still whole)."""
    return sorted(
        path
        for path in known
        if f"Failed to write {path}:" in output or f"Failed to parse {path}:" in output
    )


def remaining_findings(diagnostics: list[dict[str, Any]], root: str) -> list[str]:
    """One line per lint finding ruff could not fix (the failed files are not among them)."""
    return [
        f"{escape_name(os.path.relpath(d['filename'], root))}:{d['location']['row']}: "
        f"{d['code']} {d['message'].splitlines()[0]}"
        for d in diagnostics
        if d.get("code") not in COULD_NOT_FINISH
    ]


def render_lines(changed: list[str], failed: list[str], format_failed: bool) -> list[str]:
    lines = [f"changed: {escape_name(path)}" for path in changed]
    if failed or format_failed:
        lines += [f"failed: {escape_name(path)}" for path in failed]
        lines.append("fix: failed; ruff could not finish (its output is on standard error)")
    elif not changed:
        lines.append("fix: nothing to change")
    else:
        noun = "file" if len(changed) == 1 else "files"
        lines.append(f"fix: changed {len(changed)} {noun}; now run ./checks/all.sh")
    return lines


def python_files(root: str) -> list[str]:
    found = []
    for folder, folders, files in os.walk(root):
        folders[:] = [
            f
            for f in folders
            if f not in SKIPPED_FOLDERS
            and not os.path.exists(os.path.join(folder, f, "pyvenv.cfg"))
        ]
        found += [os.path.join(folder, name) for name in files if name.endswith(SUFFIXES)]
    return found


def snapshot(root: str) -> dict[str, str]:
    hashes = {}
    for full in python_files(root):
        if os.access(full, os.R_OK):
            with open(full, "rb") as f:
                hashes[os.path.relpath(full, root)] = hashlib.sha256(f.read()).hexdigest()
    return hashes


def ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args], capture_output=True, text=True, errors="replace"
    )


def main() -> int:
    root = os.getcwd()
    before = snapshot(root)
    lint = ruff("check", "--fix", "--no-unsafe-fixes", "--output-format", "json", ".")
    diagnostics: list[dict[str, Any]] = []
    lint_ended = lint.returncode in (0, 1)
    if lint_ended:
        try:
            diagnostics = json.loads(lint.stdout)
        except json.JSONDecodeError:
            lint_ended = False
    if not lint_ended:
        sys.stderr.write(lint.stdout + lint.stderr)
    for line in remaining_findings(diagnostics, root):
        print(line, file=sys.stderr)
    fmt = ruff("format", ".")
    sys.stderr.write(fmt.stderr)
    after = snapshot(root)
    failed = failed_from_diagnostics(diagnostics, root)
    failed = sorted(set(failed) | set(failed_from_format_output(fmt.stderr, list(before))))
    lines = render_lines(
        changed_files(before, after), failed, not lint_ended or fmt.returncode != 0
    )
    print("\n".join(lines))
    return 1 if lines[-1].startswith("fix: failed") else 0


if __name__ == "__main__":
    sys.exit(main())
