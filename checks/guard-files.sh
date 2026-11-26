#!/bin/sh
# Lists the guard files a pull request changes, as a job-summary section on standard output.
# Usage: checks/guard-files.sh <base commit>   (run inside the pull request's tree)
# Guard files: anything under checks/, .githooks/ or .github/, pyproject.toml,
# requirements-dev.txt and tests/by_value/test_rules.py. This only reports; it exits 0
# unless it was misused (exit 2) or git could not compare the commits (exit 1).
[ "$#" -eq 1 ] || { echo "usage: checks/guard-files.sh <base commit>" >&2; exit 2; }
changed=$(git diff --name-only "$1" HEAD) || exit 1
guards=$(printf '%s\n' "$changed" | grep -E \
    '^(checks/|\.githooks/|\.github/|pyproject\.toml$|requirements-dev\.txt$|tests/by_value/test_rules\.py$)')
if [ -z "$guards" ]; then
    echo "No guard files changed in this pull request."
    exit 0
fi
echo "## This pull request changes the guardrails"
echo
echo "The reviewer should read these files:"
echo
printf '%s\n' "$guards" | sed 's/^/- `/; s/$/`/'
