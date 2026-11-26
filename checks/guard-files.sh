#!/bin/sh
# Lists the guard files a pull request changes, as a job-summary section on standard output.
# Usage: checks/guard-files.sh <base commit>   (run inside the pull request's tree)
# Guard files: anything under checks/, .githooks/ or .github/, pyproject.toml,
# requirements-dev.txt and tests/by_value/test_rules.py. Each is marked changed, added or
# deleted; a moved file shows as deleted from its old path. Names are shown escaped, one per
# line. The work is in checks/guards.py.
# Exit codes: 0 listed (or none changed); 1 it could not be produced (standard output then
# says so in one line, also when the helper itself could not run or printed nothing);
# 2 misuse.
line="The guard file listing could not be produced; see the job log for why."
out=$("${PYTHON:-python3}" "$(dirname "$0")/guards.py" "$@")
code=$?
if [ -z "$out" ] && [ "$code" -ne 2 ]; then
    echo "$line"
    code=1
elif [ -n "$out" ]; then
    printf '%s\n' "$out"
fi
exit "$code"
