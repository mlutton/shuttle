#!/bin/sh
# The one definition of "this change is sound". The pre-push hook and the hosted job
# call this script and nothing else.
#
# Runs, in order, and stops at the first stage that fails:
#   lint    ruff check .
#   format  ruff format --check .
#   types   mypy (strict, over shuttle/; see pyproject.toml)
#   tests   python -m unittest discover -s tests
# Prints one line per stage ("<stage>: passed" or "<stage>: failed"; a failed stage's
# own output goes to standard error), then a last line on standard output:
#   check: passed
#   check: failed: <stage>
#   check: could not run: <tool> is not installed; install the tools with: <command>
#
# Exit codes:
#   0  every stage passed
#   1  a stage failed (the last line names it)
#   2  the check could not run: a tool is missing (the last line names it and the command)
#
# PYTHON names the interpreter that has the tools. By default it is .venv/bin/python
# when that exists, else python3. There are no retries: a failed stage stays failed.

root=$(cd "$(dirname "$0")/.." && pwd) || exit 2
cd "$root" || exit 2

if [ -z "${PYTHON:-}" ]; then
    if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi
fi

INSTALL="python3 -m pip install -r requirements-dev.txt"
for tool in ruff mypy; do
    if ! "$PYTHON" -m "$tool" --version >/dev/null 2>&1; then
        echo "check: could not run: $tool is not installed; install the tools with: $INSTALL"
        exit 2
    fi
done

output=$(mktemp) || exit 2
trap 'rm -f "$output"' EXIT

stage() {
    name=$1
    shift
    if "$@" >"$output" 2>&1; then
        echo "$name: passed"
    else
        echo "$name: failed"
        cat "$output" >&2
        echo "check: failed: $name"
        exit 1
    fi
}

stage lint "$PYTHON" -m ruff check .
stage format "$PYTHON" -m ruff format --check .
stage types "$PYTHON" -m mypy
stage tests "$PYTHON" -m unittest discover -s tests
echo "check: passed"
