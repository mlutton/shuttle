#!/bin/sh
# Prints the per-run report (tests, slowest, time per folder, peak memory, coverage, lines
# marked untested) as Markdown on standard output. Nothing fails on a number in it.
# Usage: ./checks/report.sh      The work is in checks/report.py; PYTHON names the interpreter
# that has the development tools (default: .venv/bin/python when it exists, else python3).
# Runs the whole suite once under coverage, so it takes longer than ./checks/all.sh.
# Exit codes: 0 the report was printed; 1 it could not be produced (standard output is then
# one line saying so, also when the helper could not run or printed nothing).
root=$(cd "$(dirname "$0")/.." && pwd) || exit 1
if [ -z "${PYTHON:-}" ]; then
    if [ -x "$root/.venv/bin/python" ]; then PYTHON="$root/.venv/bin/python"; else PYTHON=python3; fi
fi
out=$("$PYTHON" "$root/checks/report.py")
code=$?
# The only deciding in this script: empty output means the helper could not run at all.
if [ -z "$out" ]; then
    echo "The test report could not be produced; see the job log for why."
    exit 1
fi
printf '%s\n' "$out"
exit "$code"
