#!/bin/sh
# Lists the guard files a pull request changes, as a job-summary section on standard output.
# Usage: checks/guard-files.sh <base commit>   (run inside the pull request's tree)
# Which files are guard files is defined by GUARD_FOLDERS and GUARD_FILES in checks/guards.py.
# Each is marked changed, added or deleted; a moved file shows as deleted from its old path.
# Names are shown escaped, one per line. The work is in checks/guards.py.
# Exit codes: 0 listed (or none changed); 1 it could not be produced (standard output then
# says so in one line, also when the helper itself could not run, could not be parsed or
# printed nothing); 2 misuse (checked here, since python's own exit 2 means "cannot open file").
line="The guard file listing could not be produced; see the job log for why."
[ "$#" -eq 1 ] || { echo "usage: checks/guard-files.sh <base commit>" >&2; exit 2; }
out=$("${PYTHON:-python3}" "$(dirname "$0")/guards.py" "$@")
code=$?
# The only deciding in this script: empty output means the helper could not run at all.
if [ -z "$out" ]; then
    echo "$line"
    exit 1
fi
printf '%s\n' "$out"
exit "$code"
