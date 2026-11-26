"""./checks/all.sh --fix: ruff's safe fixes and the formatter, then what changed.

Run from the tree's root by all.sh with the interpreter that has ruff. Files that changed
are found by hashing every regular file before and after, keyed by exact path (names are
kept as str with surrogateescape, so any bytes survive), so ruff alone decides what it
touches. A file ruff could not parse or write is named as failed. Whatever goes wrong, the
last line is one of the documented "fix:" lines.
Exit codes: 0 finished; 1 ruff could not finish (the last line says so).
"""

# These scripts read files and run tools; the ban on that is for the package, not for them.
# ruff: noqa: TID251

import hashlib
import json
import os
import subprocess
import sys
import traceback
from typing import Any

from names import escape_name

FAILED_LINE = "fix: failed; ruff could not finish (its output is on standard error)"
# Diagnostics that are not lint findings: ruff could not write a file, or could not parse it.
COULD_NOT_FINISH = (None, "E902", "invalid-syntax")
SKIPPED_FOLDERS = (".git", "__pycache__", ".ruff_cache", ".mypy_cache")


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Paths whose content hash differs, or that appear or vanish, in path order."""
    return sorted(
        path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
    )


def parse_diagnostics(text: str) -> list[dict[str, Any]]:
    """ruff's JSON output as a list of diagnostics, or ValueError if it has any other shape."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("ruff's JSON output is not a list")
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str):
            raise ValueError("a ruff diagnostic has no file name")
        if entry.get("code") is not None and not isinstance(entry["code"], str):
            raise ValueError("a ruff diagnostic has a code that is not text")
    return data


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
        f"{escape_name(os.path.relpath(d['filename'], root))}:{_row(d)}: "
        f"{d['code']} {_first_line(d)}"
        for d in diagnostics
        if d.get("code") not in COULD_NOT_FINISH
    ]


def _row(diagnostic: dict[str, Any]) -> object:
    location = diagnostic.get("location")
    return location.get("row", "?") if isinstance(location, dict) else "?"


def _first_line(diagnostic: dict[str, Any]) -> str:
    lines = str(diagnostic.get("message", "")).splitlines()
    return escape_name(lines[0]) if lines else ""


def render_lines(changed: list[str], failed: list[str], format_failed: bool) -> list[str]:
    lines = [f"changed: {escape_name(path)}" for path in changed]
    if failed or format_failed:
        lines += [f"failed: {escape_name(path)}" for path in failed]
        lines.append(FAILED_LINE)
    elif not changed:
        lines.append("fix: nothing to change")
    else:
        noun = "file" if len(changed) == 1 else "files"
        lines.append(f"fix: changed {len(changed)} {noun}; now run ./checks/all.sh")
    return lines


def regular_files(root: str) -> list[str]:
    """Every regular file under root, not followed through symbolic links (a link to a file is
    the same content as its target and would be counted twice), skipping what ruff does not
    own: .git, caches and virtual environments."""
    found = []
    for folder, folders, files in os.walk(root):
        folders[:] = [
            f
            for f in folders
            if f not in SKIPPED_FOLDERS
            and not os.path.exists(os.path.join(folder, f, "pyvenv.cfg"))
        ]
        found += [os.path.join(folder, n) for n in files]
    return [path for path in found if not os.path.islink(path) and os.path.isfile(path)]


def file_hash(path: str) -> str | None:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def snapshot(root: str) -> dict[str, str]:
    hashes = {}
    for full in regular_files(root):
        digest = file_hash(full)
        if digest is not None:
            hashes[os.path.relpath(full, root)] = digest
    return hashes


def ruff(*args: str) -> tuple[int, str, str]:
    done = subprocess.run([sys.executable, "-m", "ruff", *args], capture_output=True)
    return done.returncode, os.fsdecode(done.stdout), os.fsdecode(done.stderr)


def run() -> int:
    root = os.getcwd()
    before = snapshot(root)
    lint_code, lint_out, lint_err = ruff(
        "check", "--fix", "--no-unsafe-fixes", "--output-format", "json", "."
    )
    diagnostics: list[dict[str, Any]] = []
    lint_ended = lint_code in (0, 1)
    if lint_ended:
        try:
            diagnostics = parse_diagnostics(lint_out)
        except ValueError:  # includes json.JSONDecodeError
            lint_ended = False
    if not lint_ended:
        sys.stderr.write(lint_out + lint_err)
    for line in remaining_findings(diagnostics, root):
        print(line, file=sys.stderr)
    format_code, _, format_err = ruff("format", ".")
    sys.stderr.write(format_err)
    after = snapshot(root)
    failed = set(failed_from_diagnostics(diagnostics, root))
    failed |= set(failed_from_format_output(format_err, list(before)))
    lines = render_lines(
        changed_files(before, after), sorted(failed), not lint_ended or format_code != 0
    )
    print("\n".join(lines))
    return 1 if lines[-1] == FAILED_LINE else 0


def main() -> int:
    try:
        return run()
    except Exception:  # whatever went wrong, the last line must still be a "fix:" line
        traceback.print_exc()
        print(FAILED_LINE)
        return 1


if __name__ == "__main__":
    sys.exit(main())
