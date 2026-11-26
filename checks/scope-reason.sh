#!/bin/bash
# Answers: can a systemd user scope be given a maximum runtime, does it stop everything inside
# when that runs out, and can the reason it ended be read afterwards? One line per case, then:
#   scope reason: works
#   scope reason: does not work: <which case and what was seen>
# Cases: timed out (maximum runtime reached), exited (the command ended by itself), stopped by
# name (systemctl stop). The reason is read with systemctl show: the unit's Result and ActiveState.
# Only the units this script starts are stopped or reset, by exact name.
#
# Exit codes:
#   0  the check ran to a conclusion (works, or does not work)
#   2  the check itself could not run (systemd-run, systemctl or bwrap is missing)

for t in systemd-run systemctl bwrap; do
  command -v "$t" >/dev/null 2>&1 || { echo "check could not run: $t is not installed"; exit 2; }
done

BASE="shuttle-scope-reason-$$-$RANDOM"
BOUNDARY=(bwrap --unshare-pid --die-with-parent --bind / / --dev /dev --proc /proc)
PROBLEMS=""

cleanup() {
  for n in timeout exit stop; do
    systemctl --user stop "$BASE-$n.scope" >/dev/null 2>&1
    systemctl --user reset-failed "$BASE-$n.scope" >/dev/null 2>&1
  done
  [ -n "$STOPPER_PID" ] && kill "$STOPPER_PID" >/dev/null 2>&1
}
trap cleanup EXIT

# what <name>: the unit's state as one line
what() { systemctl --user show "$BASE-$1.scope" -p LoadState,ActiveState,Result 2>&1 | tr '\n' ' ' | sed 's/ $//'; }
problem() { PROBLEMS="$PROBLEMS $1;"; }

# 1. timed out: a maximum runtime of 2 seconds, and a process that would run for an hour.
systemd-run --user --scope --quiet --unit="$BASE-timeout" -p RuntimeMaxSec=2 \
  "${BOUNDARY[@]}" sh -c 'sleep 3600 & wait' >/dev/null 2>&1
echo "timeout: command exit $?; $(what timeout)"
case "$(what timeout)" in
  *ActiveState=failed*Result=timeout*) ;;
  *) problem "timeout case did not read Result=timeout" ;;
esac

# 2. exited: the command ends by itself well before the maximum runtime.
systemd-run --user --scope --quiet --unit="$BASE-exit" -p RuntimeMaxSec=60 \
  "${BOUNDARY[@]}" true >/dev/null 2>&1
echo "exit: command exit $?; $(what exit)"
case "$(what exit)" in
  *Result=timeout*|*ActiveState=failed*) problem "exit case read as timed out or failed" ;;
esac

# 3. stopped by name: the unit is stopped with systemctl while the command is running.
systemd-run --user --scope --quiet --unit="$BASE-stop" -p RuntimeMaxSec=60 \
  "${BOUNDARY[@]}" sleep 3601 >/dev/null 2>&1 &
STOPPER_PID=$!
for _ in $(seq 1 50); do
  [ "$(systemctl --user is-active "$BASE-stop.scope" 2>/dev/null)" = active ] && break
  sleep 0.1
done
systemctl --user stop "$BASE-stop.scope"
wait "$STOPPER_PID"
echo "stop: command exit $?; $(what stop)"
case "$(what stop)" in
  *Result=timeout*) problem "stop case read as timed out" ;;
esac

# Nothing may be left: the timed-out command's background sleep and the stopped one.
sleep 0.5
LEFT=$(pgrep -x sleep -a | grep -c -E ' 360[01]$')
echo "left running: $LEFT"
[ "$LEFT" -eq 0 ] || problem "$LEFT process(es) left running"

# The three readings must differ: timeout is the only one that reads Result=timeout.
if [ -z "$PROBLEMS" ]; then echo "scope reason: works"
else echo "scope reason: does not work:$PROBLEMS"; fi
exit 0
