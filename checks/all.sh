#!/bin/sh
# The one definition of "this change is sound". The pre-push hook and the hosted job
# call this script and nothing else.
#
# Runs, in order, and stops at the first stage that fails:
#   lint    ruff check .
#   format  ruff format --check .
#   types   mypy (strict, over shuttle/ and checks/; see pyproject.toml)
#   tests   python -m unittest discover -s tests/by_value: the tests that start no real
#           process, under TESTS_SECONDS (below)
#   real    python -m unittest discover, over tests/command and then tests/boundary: the tests
#           that start real processes, under REAL_SECONDS (below), for the two folders together.
#           It stops at the first folder that fails, so a failure in tests/command means
#           tests/boundary did not run. The stage also runs under a file-size limit and an
#           address-space limit (below), which every process it starts inherits; the harness
#           of tests/rehearsal/real_run.py sets tighter ones for the command it starts.
# The budgets, each written once below the header: TESTS_SECONDS keeps the logic tests fast;
# REAL_SECONDS ends a real-process test that never returns, and does not police speed.
# Every folder under tests/ that holds tests is in exactly one of the two (a test pins it);
# tests/rehearsal and tests/hostile hold helpers and tables, not tests.
# Prints one line per stage ("<stage>: passed" or "<stage>: failed"; a failed stage's
# own output goes to standard error), then a last line on standard output:
#   check: passed
#   check: failed: <stage>
# The format stage adds how to fix it: "check: failed: format; fix it with: ./checks/all.sh --fix"
# A tests or real stage ended by its time budget says so, with that budget's number:
#   check: failed: tests (timed out after 20 seconds)
#   check: failed: real (timed out after 120 seconds)
#   check: could not run: <tool> is not installed (ruff, mypy or, for the tests, coverage); install the tools with: <command>
#   check: could not run: the real stage's <file-size|address-space> limit cannot be set, because this shell's own limit is lower; raise it (ulimit -f or -v) or start a shell without it
#
# ./checks/all.sh --fix applies what ruff can change mechanically and says what changed:
#   ruff check --fix --no-unsafe-fixes, then ruff format (checks/fixmode.py does the work).
# It adds no ignore comment, edits no configuration and only ruff touches files. It needs
# ruff only, not mypy. It prints one line per file changed ("changed: <path>", a name's
# control characters shown as escapes), a line "failed: <path>" for each file ruff could not
# parse or write, then a last line:
#   fix: changed <N> files ("1 file" for one); now run ./checks/all.sh
#   fix: nothing to change
#   fix: failed; ruff could not finish (its output is on standard error)
# (the same last line is printed, exit 1, when checks/fixmode.py cannot run at all: missing, or
# not parseable)
# It does not run types or tests and does not say the change is sound. Lint findings it
# cannot fix are left in place and shown on standard error; the check still fails on them.
#
# Exit codes:
#   0  every stage passed; or, with --fix, it finished (whether or not it changed anything)
#   1  a stage failed (the last line names it); or, with --fix, ruff could not finish
#      (a file it could not parse or write, or ruff ending abnormally)
#   2  the check could not run: a tool is missing, or a limit of the real stage cannot be set
#      (the last line names it and what to do)
#   3  the argument was not recognised (one line on standard error names the two forms)
#
# PYTHON names the interpreter that has the tools. By default checks/interpreter.sh picks this
# tree's .venv/bin/python, else the main working tree's (for a linked worktree), else python3. There are no retries: a failed stage stays failed.

TESTS_SECONDS=20
REAL_SECONDS=120
# Limits of the real stage, set once so no test has to ask: a time limit does not stop a test
# that reads a device without end from filling memory (the machine's out-of-memory killer ended a
# whole session that way). They sit above what any test raises a harness limit to. `ulimit -f`
# counts 512-byte blocks and `-v` kilobytes in sh.
REAL_FILE_BLOCKS=262144
REAL_ADDRESS_KB=3145728

mode=check
[ "$#" -eq 1 ] && [ "$1" = --fix ] && mode=fix
if [ "$#" -gt 0 ] && [ "$mode" = check ]; then
    echo "usage: ./checks/all.sh   or   ./checks/all.sh --fix" >&2
    exit 3
fi

root=$(cd "$(dirname "$0")/.." && pwd) || exit 2
cd "$root" || exit 2

if [ -z "${PYTHON:-}" ]; then
    unusable="check: could not run: checks/interpreter.sh is missing or unusable; set PYTHON or restore the file"
    [ -f checks/interpreter.sh ] || { echo "$unusable"; exit 2; }
    . checks/interpreter.sh
    command -v choose_python >/dev/null 2>&1 || { echo "$unusable"; exit 2; }
    PYTHON=$(choose_python "$root")
    : "${PYTHON:=python3}"
fi

INSTALL="python3 -m pip install -r requirements-dev.txt"
tools="ruff mypy coverage"
[ "$mode" = fix ] && tools=ruff
for tool in $tools; do
    if ! "$PYTHON" -m "$tool" --version >/dev/null 2>&1; then
        echo "check: could not run: $tool is not installed; install the tools with: $INSTALL"
        exit 2
    fi
done

if [ "$mode" = fix ]; then
    out=$("$PYTHON" checks/fixmode.py)
    code=$?
    # The only deciding here: no "fix:" last line, or an exit code other than 0 or 1, means failure.
    case "$code:$(printf '%s\n' "$out" | tail -n 1)" in
        [01]:"fix: "*) ;;
        *)
            [ -n "$out" ] && printf '%s\n' "$out"
            echo "fix: failed; ruff could not finish (its output is on standard error)"
            exit 1
            ;;
    esac
    printf '%s\n' "$out"
    exit "$code"
fi

# A limit this shell may not raise would end the real stage as if a test had failed; no test ran.
unsettable="the real stage's %s limit cannot be set, because this shell's own limit is lower; raise it (ulimit %s) or start a shell without it"
(ulimit -f "$REAL_FILE_BLOCKS") 2>/dev/null || {
    printf "check: could not run: $unsettable\n" "file-size" "-f"
    exit 2
}
(ulimit -v "$REAL_ADDRESS_KB") 2>/dev/null || {
    printf "check: could not run: $unsettable\n" "address-space" "-v"
    exit 2
}

output=$(mktemp) || exit 2
trap 'rm -f "$output"' EXIT

stage() {
    name=$1
    budget=$2
    shift 2
    "$@" >"$output" 2>&1
    code=$?
    if [ "$code" -eq 0 ]; then
        echo "$name: passed"
        return 0
    fi
    echo "$name: failed"
    cat "$output" >&2
    case "$name" in
        format) echo "check: failed: format; fix it with: ./checks/all.sh --fix" ;;
        tests | real)
            if [ "$code" -eq 124 ]; then
                echo "check: failed: $name (timed out after $budget seconds)"
            else
                echo "check: failed: $name"
            fi
            ;;
        *) echo "check: failed: $name" ;;
    esac
    exit 1
}

stage lint 0 "$PYTHON" -m ruff check .
stage format 0 "$PYTHON" -m ruff format --check .
stage types 0 "$PYTHON" -m mypy
# As of 2026-11-26 the by-value tests take about 3 seconds; a run past 20 is a wait that crept
# back in. The real-process tests take about 10 seconds; 120 is far past that, so only a test that
# never returns reaches it. The two folders run in one command, so the one budget covers both.
stage tests "$TESTS_SECONDS" timeout "$TESTS_SECONDS" "$PYTHON" -m unittest discover -s tests/by_value -t tests
stage real "$REAL_SECONDS" timeout "$REAL_SECONDS" sh -c \
    'ulimit -f "$1" && ulimit -v "$2" && "$0" -m unittest discover -s tests/command -t tests && "$0" -m unittest discover -s tests/boundary -t tests' \
    "$PYTHON" "$REAL_FILE_BLOCKS" "$REAL_ADDRESS_KB"
echo "check: passed"
