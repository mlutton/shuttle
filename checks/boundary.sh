#!/bin/bash
# Checks whether this machine can run the Shuttle boundary:
#   systemd-run --user --scope  around
#   bwrap --unshare-pid --die-with-parent --bind / / --dev /dev --proc /proc <command>
# Three parts, one output line each, then a last line:
#   boundary: works
#   boundary: does not work: <which part failed and the error text>
# Only the units this script starts are stopped, by exact name.
#
# Exit codes:
#   0  the check ran to a conclusion (works, or does not work)
#   2  the check itself could not run (systemd-run, systemctl or bwrap is missing)

for t in systemd-run systemctl bwrap; do
  command -v "$t" >/dev/null 2>&1 || { echo "check could not run: $t is not installed"; exit 2; }
done

UNIT="shuttle-boundary-check-$$-$RANDOM"
SLEEP_SECS=$((3000 + RANDOM % 500))
SLEEP_CMD="sleep $SLEEP_SECS"
WORK=$(mktemp -d)
PARENT_PID=""

cleanup() {
  systemctl --user stop "$UNIT.scope" >/dev/null 2>&1
  [ -n "$UNIT2_STARTED" ] && systemctl --user stop "$UNIT2.scope" >/dev/null 2>&1
  [ -n "$PARENT_PID" ] && kill -9 "$PARENT_PID" >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

oneline() { tr '\n' ' ' | sed 's/  */ /g; s/ $//' | cut -c1-400; }

fail() {  # $1 = part, $2 = error text
  echo "boundary: does not work: $1: $(printf '%s' "$2" | oneline)"
  exit 0
}

scope_state() { systemctl --user is-active "$UNIT.scope" 2>&1 | head -1; }
sleeper_count() { pgrep -fx "$SLEEP_CMD" 2>/dev/null | wc -l; }

wait_for() {  # wait_for SECONDS command...
  local n=$(( $1 * 5 )); shift
  while [ "$n" -gt 0 ]; do "$@" && return 0; sleep 0.2; n=$((n-1)); done
  return 1
}
is_running() { [ "$(scope_state)" = active ] && [ "$(sleeper_count)" -ge 1 ]; }
is_gone()    { [ "$(scope_state)" != active ] && [ "$(sleeper_count)" -eq 0 ]; }

# Part 1: start a command inside the boundary. The launching parent is a bash
# that is not exec'd into the boundary, so it can be killed on its own in part 2.
bash -c '
  systemd-run --user --scope --quiet --unit="$1" \
    bwrap --unshare-pid --die-with-parent --bind / / --dev /dev --proc /proc \
    sleep "$2"
  echo "launcher exited with status $?"
' _ "$UNIT" "$SLEEP_SECS" >"$WORK/launch.out" 2>&1 &
PARENT_PID=$!

if wait_for 15 is_running; then
  echo "1 run: started '$SLEEP_CMD' in scope $UNIT.scope; saw scope $(scope_state) and $(sleeper_count) matching process(es)"
else
  fail "part 1 (run a command inside the boundary)" "scope $(scope_state), matching processes $(sleeper_count), launcher output: $(cat "$WORK/launch.out")"
fi

# Part 2: kill the launching parent hard; everything inside must die.
kill -9 "$PARENT_PID" 2>/dev/null
wait "$PARENT_PID" 2>/dev/null
if wait_for 15 is_gone; then
  echo "2 parent kill: sent SIGKILL to the launching parent; saw scope $(scope_state) and $(sleeper_count) matching process(es)"
else
  fail "part 2 (kill the parent)" "after SIGKILL to the parent, scope $(scope_state), matching processes $(sleeper_count)"
fi
PARENT_PID=""

# Part 3: start a second, fresh boundary, see it running, stop it by exact
# name while it is running, then see the boundary empty.
UNIT2="shuttle-boundary-check-$$-$RANDOM-b"
SLEEP2_SECS=$((3600 + RANDOM % 500))
SLEEP2_CMD="sleep $SLEEP2_SECS"
UNIT2_STARTED=1
bash -c '
  systemd-run --user --scope --quiet --unit="$1" \
    bwrap --unshare-pid --die-with-parent --bind / / --dev /dev --proc /proc \
    sleep "$2"
' _ "$UNIT2" "$SLEEP2_SECS" >"$WORK/launch2.out" 2>&1 &
PARENT_PID=$!
state2() { systemctl --user is-active "$UNIT2.scope" 2>&1 | head -1; }
count2() { pgrep -fx "$SLEEP2_CMD" 2>/dev/null | wc -l; }
running2() { [ "$(state2)" = active ] && [ "$(count2)" -ge 1 ]; }
if ! wait_for 15 running2; then
  fail "part 3 (second boundary did not start)" "scope $(state2), matching processes $(count2), launcher output: $(cat "$WORK/launch2.out")"
fi
CG=$(systemctl --user show -p ControlGroup --value "$UNIT2.scope" 2>/dev/null)
BEFORE=0
[ -n "$CG" ] && [ -r "/sys/fs/cgroup$CG/cgroup.procs" ] && BEFORE=$(wc -l < "/sys/fs/cgroup$CG/cgroup.procs")
STOP_ERR=$(systemctl --user stop "$UNIT2.scope" 2>&1)
STOP_RC=$?
wait_for 15 bash -c '[ "$(systemctl --user is-active "$0" 2>&1 | head -1)" != active ]' "$UNIT2.scope"
PROCS=0
if [ -n "$CG" ] && [ -r "/sys/fs/cgroup$CG/cgroup.procs" ]; then
  PROCS=$(wc -l < "/sys/fs/cgroup$CG/cgroup.procs")
fi
if [ "$STOP_RC" -eq 0 ] && [ "$(state2)" != active ] && [ "$(count2)" -eq 0 ] && [ "$PROCS" -eq 0 ]; then
  echo "3 stop and empty: started second scope $UNIT2.scope (saw active, $BEFORE process(es) in its cgroup), stopped it by name while running; saw scope $(state2), $PROCS process(es) in its cgroup, $(count2) matching process(es)"
else
  fail "part 3 (stop a running boundary)" "stop exit $STOP_RC ($STOP_ERR); scope $(state2), cgroup processes $PROCS, matching processes $(count2)"
fi

echo "boundary: works"
exit 0
