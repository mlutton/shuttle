#!/bin/sh
# Lists the guard files a pull request changes, as a job-summary section on standard output.
# Usage: checks/guard-files.sh <base commit>   (run inside the pull request's tree)
# Guard files: anything under checks/, .githooks/ or .github/, pyproject.toml,
# requirements-dev.txt and tests/by_value/test_rules.py. Each is marked changed, added or
# deleted; a moved file shows as deleted from its old path. The work is in checks/guards.py.
# Exit codes: 0 listed (or none changed); 1 git could not compare the commits (standard
# output then says so in one line); 2 misuse.
exec "${PYTHON:-python3}" "$(dirname "$0")/guards.py" "$@"
