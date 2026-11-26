"""The per-run report: how big and slow the suite is and which code has no test, as Markdown.

Usage: report.py   (run from anywhere; the project root is the folder above checks/)
Writes the report on standard output. Nothing fails on a number in it. Exit codes: 0 the
report was written; 1 it could not be produced (standard output is then one line saying so
and why, whatever the cause).

The suite is run once under coverage.py (checks/timed_tests.py does the timing; the coverage
settings come from [tool.coverage] in pyproject.toml, written out with absolute paths to a
temporary file, so child processes the tests start are measured too: `patch = subprocess`).
Every number is printed by this run; nothing is read from a file in the tree. The data files
live in a temporary folder that is removed afterwards.

The building of the report from data is in pure functions; run() gathers the data.
"""

# These scripts read files and run tools; the ban on that is for the package, not for them.
# ruff: noqa: TID251

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tokenize
import tomllib
import traceback
from dataclasses import dataclass
from typing import Any

from names import escape_name, fenced

COMMAND = "./checks/report.sh"
# As of 2026-11-26 the eight slowest tests are listed.
SLOWEST = 8
TEST_FOLDERS = ("by_value", "command", "boundary")
MARKER = "# not tested:"
COULD_NOT = "The test report could not be produced"
RUN_TIMEOUT_SECONDS = 600
COVERAGE_ENVIRONMENT = (
    "COVERAGE_PROCESS_START",
    "COVERAGE_PROCESS_CONFIG",
    "COVERAGE_FILE",
    "COVERAGE_RCFILE",
    "COVERAGE_CORE",
)


@dataclass(frozen=True)
class TestRecord:
    __test__ = False  # not a test case, whatever its name says to a test loader

    id: str
    seconds: float
    outcome: str  # passed, skipped, failed or error
    reason: str = ""


@dataclass(frozen=True)
class FileCoverage:
    path: str
    statements: int
    missing: tuple[int, ...]  # lines of statements never run, and not marked as untested
    excluded: tuple[int, ...]  # lines carrying a "not tested" marker (statements not counted)


@dataclass(frozen=True)
class Marker:
    path: str
    line: int
    reason: str


@dataclass(frozen=True)
class Facts:
    """Everything the report prints, gathered by one run."""

    commit: str
    command: str
    python: str
    coverage: str
    tests: tuple[TestRecord, ...]
    total_seconds: float
    was_successful: bool
    peak_self_kib: int
    peak_children_kib: int
    files: tuple[FileCoverage, ...]
    markers: tuple[Marker, ...]
    failures: tuple[str, ...] = ()


# ------------------------------------------------------------------ pure functions


def ranges(lines: list[int] | tuple[int, ...]) -> str:
    """[1, 2, 3, 7, 9, 10] as "1-3, 7, 9-10"."""
    out: list[str] = []
    ordered = sorted(set(lines))
    start = 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and ordered[end + 1] == ordered[end] + 1:
            end += 1
        first, last = ordered[start], ordered[end]
        out.append(str(first) if first == last else f"{first}-{last}")
        start = end + 1
    return ", ".join(out)


def to_kib(value: int, platform: str) -> int:
    """ru_maxrss is in kibibytes on Linux and in bytes on macOS."""
    return value // 1024 if platform == "darwin" else value


def folder_of(test_id: str) -> str:
    return test_id.split(".")[0] if "." in test_id else "(other)"


def slowest(tests: tuple[TestRecord, ...], count: int = SLOWEST) -> list[TestRecord]:
    return sorted(tests, key=lambda t: (-t.seconds, t.id))[:count]


def time_per_folder(tests: tuple[TestRecord, ...]) -> list[tuple[str, int, float]]:
    """(folder, tests, seconds summed over its tests) for the known folders and any other."""
    count: dict[str, int] = {name: 0 for name in TEST_FOLDERS}
    seconds: dict[str, float] = {name: 0.0 for name in TEST_FOLDERS}
    for test in tests:
        name = folder_of(test.id)
        count[name] = count.get(name, 0) + 1
        seconds[name] = seconds.get(name, 0.0) + test.seconds
    return [(name, count[name], seconds[name]) for name in sorted(count)]


def find_markers(path: str, source: str) -> tuple[list[Marker], list[str]]:
    """The "# not tested: <reason>" comments in a file's source (comments only, never text in
    a string), and the problems with them: a marker with an empty reason, or a near miss
    (`# not tested` without the colon) that coverage would not honour."""
    found: list[Marker] = []
    problems: list[str] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return [], [f"{path}: could not be read for markers"]
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        text = token.string
        line = token.start[0]
        if MARKER in text:
            reason = text.split(MARKER, 1)[1].strip()
            if reason:
                found.append(Marker(path, line, reason))
            else:
                problems.append(f"{path} line {line}: a '{MARKER}' marker with no reason")
        elif re.search(r"#\s*not[ _-]?tested\b", text, re.IGNORECASE):
            problems.append(
                f"{path} line {line}: not the marker form '{MARKER} <reason>' "
                "(coverage would not exclude it)"
            )
    return found, problems


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return json.dumps(str(value))  # JSON string escapes are valid in a TOML basic string


def coverage_config(pyproject: dict[str, Any], root: str, data_file: str) -> str:
    """A TOML coverage configuration from the project's [tool.coverage] tables, with the
    source folders made absolute (child processes start in other folders) and the data file
    set to a place outside the tree."""
    tables = dict(pyproject.get("tool", {}).get("coverage", {}))
    run = dict(tables.get("run", {}))
    run["source"] = [os.path.join(root, s) for s in run.get("source", [])]
    run["data_file"] = data_file
    tables["run"] = run
    lines = []
    for table in sorted(tables):
        lines.append(f"[tool.coverage.{table}]")
        lines += [f"{key} = {_toml_value(value)}" for key, value in tables[table].items()]
        lines.append("")
    return "\n".join(lines)


def normalize_coverage(data: dict[str, Any], root: str) -> list[FileCoverage]:
    """coverage.py's JSON report as one record per file, paths relative to root, in path order."""
    out = []
    for name, entry in data.get("files", {}).items():
        path = os.path.relpath(name, root) if os.path.isabs(name) else name
        out.append(
            FileCoverage(
                path.replace(os.sep, "/"),
                int(entry["summary"]["num_statements"]),
                tuple(entry.get("missing_lines", [])),
                tuple(entry.get("excluded_lines", [])),
            )
        )
    return sorted(out, key=lambda f: f.path)


def percent(statements: int, missing: int) -> str:
    return "n/a" if statements == 0 else f"{100 * (statements - missing) / statements:.0f}%"


def _table(rows: list[tuple[str, ...]], header: tuple[str, ...]) -> list[str]:
    """Rows of columns as aligned text lines: the first column left-aligned, the middle ones
    (numbers) right-aligned, the last free text."""
    every = [header, *rows]
    widths = [max(len(r[i]) for r in every) for i in range(len(header) - 1)]
    lines = []
    for row in every:
        cells = [row[0].ljust(widths[0])]
        cells += [row[i].rjust(widths[i]) for i in range(1, len(header) - 1)]
        cells.append(row[-1])
        lines.append("  ".join(cells).rstrip())
    return lines


def render_coverage(files: tuple[FileCoverage, ...]) -> list[str]:
    rows: list[tuple[str, ...]] = [
        (
            escape_name(f.path),
            str(f.statements),
            str(len(f.missing)),
            percent(f.statements, len(f.missing)),
            ranges(f.missing),
        )
        for f in files
    ]
    total = sum(f.statements for f in files)
    never = sum(len(f.missing) for f in files)
    rows.append(("total", str(total), str(never), percent(total, never), ""))
    return _table(rows, ("file", "statements", "never run", "run", "lines never run"))


def describe_outcomes(tests: tuple[TestRecord, ...]) -> str:
    kinds = {"passed": 0, "skipped": 0, "failed": 0, "error": 0}
    for test in tests:
        kinds[test.outcome] = kinds.get(test.outcome, 0) + 1
    return (
        f"{len(tests)} run: {kinds['passed']} passed, {kinds['skipped']} skipped, "
        f"{kinds['failed']} failed, {kinds['error']} errors"
    )


def render_report(facts: Facts) -> str:
    """The whole report as Markdown. Every name, reason and path goes into a fenced block,
    escaped to one line each, so none can close the block or start markup."""
    peak = max(facts.peak_self_kib, facts.peak_children_kib)
    skipped = [f"{escape_name(t.id)}: {escape_name(t.reason)}" for t in facts.tests if t.reason]
    slow = [f"{t.seconds:8.3f} s  {escape_name(t.id)}" for t in slowest(facts.tests)]
    folders = [
        f"{name:<10}{count:>5} tests{seconds:>10.3f} s"
        for name, count, seconds in time_per_folder(facts.tests)
    ]
    out = [
        "## Test report for this run",
        "",
        f"Commit `{escape_name(facts.commit)}`; command `{facts.command}`; "
        f"Python {escape_name(facts.python)}; coverage.py {escape_name(facts.coverage)}.",
        "",
        "Generated by this run, never checked in. Nothing fails on a number here. The suite "
        "ran under coverage.py, which slows it, so times and memory are larger than a plain "
        "`./checks/all.sh` run's.",
        "",
        "### Tests",
        "",
        f"- {describe_outcomes(facts.tests)}.",
        f"- Total time: {facts.total_seconds:.3f} s (wall time of the suite run).",
        f"- Peak memory: {peak / 1024:.1f} MiB, the largest resident size any one process of "
        f"the run reached (`resource.getrusage`: the test process itself "
        f"{facts.peak_self_kib / 1024:.1f} MiB, the largest process it started and waited for "
        f"{facts.peak_children_kib / 1024:.1f} MiB). It is not the total over all processes, "
        "and it includes coverage's own overhead.",
        "",
    ]
    if facts.failures:
        out += ["Tests that did not pass:", "", fenced([escape_name(f) for f in facts.failures])]
    out += ["Skipped, with the reason given:", ""]
    out += [fenced(skipped)] if skipped else ["None skipped.", ""]
    out += [f"### The {SLOWEST} slowest tests", ""]
    out += [fenced(slow)] if slow else ["No tests ran.", ""]
    out += [
        "### Time per test folder",
        "",
        "Summed over the tests in each folder.",
        "",
        fenced(folders),
        "### Coverage",
        "",
        "Statements per Python file, the statements never run and their line ranges. "
        "Child processes the tests start are measured; code that runs only from copies of "
        "the scripts placed in temporary trees is not counted against the originals. "
        "Statements on a line marked deliberately untested are left out of the counts and "
        "listed below. The percentage is for orientation only.",
        "",
        fenced(render_coverage(facts.files)),
        "### Deliberately untested",
        "",
    ]
    if facts.markers:
        out += [
            f"Lines marked `{MARKER} <reason>`:",
            "",
            fenced(
                [f"{escape_name(m.path)}:{m.line}  {escape_name(m.reason)}" for m in facts.markers]
            ),
        ]
    else:
        out += [f"No line carries a `{MARKER} <reason>` marker.", ""]
    return "\n".join(out)


def failure_line(reason: str) -> str:
    """The one line that stands in for a report that could not be produced."""
    one = escape_name(reason.strip().splitlines()[-1] if reason.strip() else "unknown cause")
    return f"{COULD_NOT}: {one}; see the job log."


# --------------------------------------------------------------------- the runner


def _run(args: list[str], root: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=RUN_TIMEOUT_SECONDS,
    )


def _must(done: subprocess.CompletedProcess[str], what: str) -> None:
    if done.returncode != 0:
        sys.stderr.write(done.stdout + done.stderr)
        raise RuntimeError(f"{what} failed (exit {done.returncode})")


def source_markers(root: str, paths: list[str]) -> tuple[list[Marker], list[str]]:
    found: list[Marker] = []
    problems: list[str] = []
    for path in paths:
        full = os.path.join(root, path)
        try:
            with open(full, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as error:
            problems.append(f"{path}: {error}")
            continue
        markers, bad = find_markers(path, text)
        found += markers
        problems += bad
    return found, problems


def git_commit(root: str) -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        return "unknown (git could not run)"
    if not sha:
        return "unknown (not a git checkout)"
    return sha + (" plus uncommitted changes" if dirty else "")


def gather(root: str, scratch: str) -> Facts:
    with open(os.path.join(root, "pyproject.toml"), "rb") as source:
        pyproject = tomllib.load(source)
    rc = os.path.join(scratch, "coverage.toml")
    with open(rc, "w", encoding="utf-8") as config:
        config.write(coverage_config(pyproject, root, os.path.join(scratch, "data", ".coverage")))
    env = {k: v for k, v in os.environ.items() if k not in COVERAGE_ENVIRONMENT}
    timing = os.path.join(scratch, "timing.json")
    timed = os.path.join(root, "checks", "timed_tests.py")
    py = sys.executable
    _must(
        _run([py, "-m", "coverage", "run", f"--rcfile={rc}", timed, timing], root, env), "the run"
    )
    _must(_run([py, "-m", "coverage", "combine", f"--rcfile={rc}"], root, env), "combine")
    out = os.path.join(scratch, "coverage.json")
    _must(_run([py, "-m", "coverage", "json", f"--rcfile={rc}", "-o", out], root, env), "json")
    version = _run([py, "-m", "coverage", "--version"], root, env).stdout.split()
    with open(timing, encoding="utf-8") as timed_file:
        t = json.load(timed_file)
    with open(out, encoding="utf-8") as coverage_file:
        files = tuple(normalize_coverage(json.load(coverage_file), root))
    markers, problems = source_markers(root, [f.path for f in files])
    if problems:
        raise RuntimeError("; ".join(problems))
    tests = tuple(
        TestRecord(r["id"], float(r["seconds"]), r["outcome"], r["reason"]) for r in t["tests"]
    )
    return Facts(
        commit=git_commit(root),
        command=COMMAND,
        python=sys.version.split()[0],
        coverage=version[2] if len(version) > 2 else "unknown",
        tests=tests,
        total_seconds=float(t["total_seconds"]),
        was_successful=bool(t["was_successful"]),
        peak_self_kib=to_kib(int(t["maxrss_self"]), t["platform"]),
        peak_children_kib=to_kib(int(t["maxrss_children"]), t["platform"]),
        files=files,
        markers=tuple(markers),
        failures=tuple(f"{r.id} ({r.outcome})" for r in tests if r.outcome in ("failed", "error")),
    )


def run() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as scratch:
        facts = gather(root, scratch)
    sys.stdout.write(render_report(facts))
    return 0


def main() -> int:
    try:
        return run()
    except Exception as error:  # an empty report must never pass for one
        traceback.print_exc()
        print(failure_line(f"{type(error).__name__}: {error}"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
