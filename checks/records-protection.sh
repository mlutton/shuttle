#!/bin/bash
# Checks whether the Shuttle boundary can stop the command inside it from writing
# two protected folders (records, kept) while still letting it write the place.
# The boundary is as in checks/boundary.sh, plus two read-only binds placed after
# the whole-filesystem bind:
#   systemd-run --user --scope  around
#   bwrap --unshare-pid --die-with-parent --bind / / --ro-bind R R --ro-bind K K
#         --dev /dev --proc /proc <command>
# From inside it tries, one output line each:
#   a create a file in records      b overwrite the file in records
#   c delete the file in records    d rename the records folder
#   e create a file in kept         f create a file in the place (must succeed)
#   g remount records read-write    h write to records by a second path
# (h is two tries: via /proc/self/root, and via a symlink made in the place.)
# After the command exits, from outside, records and kept are checked by content
# and the place is checked for the new file. Last line:
#   records protection: works
#   records protection: does not work: <which attempt got through>
# Only the unit this script starts is stopped, by exact name.
#
# Exit codes:
#   0  the check ran to a conclusion (works, or does not work)
#   2  the check itself could not run (systemd-run, systemctl or bwrap is missing)

for t in systemd-run systemctl bwrap; do
  command -v "$t" >/dev/null 2>&1 || { echo "check could not run: $t is not installed"; exit 2; }
done

UNIT="shuttle-records-check-$$-$RANDOM"
WORK=$(mktemp -d)
cleanup() {
  systemctl --user stop "$UNIT.scope" >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

P="$WORK/place"; R="$WORK/records"; K="$WORK/kept"
mkdir "$P" "$R" "$K"
echo "place original" > "$P/old.txt"
echo "records original" > "$R/old.txt"
echo "kept original" > "$K/old.txt"

# The command that runs inside the boundary. It lives outside the three folders.
# Each line: <code> <status> <what was tried and what was seen>
cat > "$WORK/inner.sh" <<'INNER'
R=$1; K=$2; P=$3
one() { tr '\n' ' ' | sed 's/  */ /g; s/ $//' | cut -c1-300; }
try() {  # try CODE DESCRIPTION COMMAND... ; status is "got-through" if the command succeeded
  local code=$1 desc=$2; shift 2
  local out; out=$("$@" 2>&1); local rc=$?
  if [ $rc -eq 0 ]; then echo "$code got-through $desc: succeeded"
  else echo "$code refused $desc: refused (exit $rc): $(printf '%s' "$out" | one)"; fi
}
try a "create a new file in records" bash -c 'echo new > "$1/new.txt"' _ "$R"
try b "overwrite the existing file in records" bash -c 'echo changed > "$1/old.txt"' _ "$R"
try c "delete the existing file in records" rm "$R/old.txt"
try d "rename the records folder" mv "$R" "$R.renamed"
try e "create a new file in kept" bash -c 'echo new > "$1/new.txt"' _ "$K"
if echo new > "$P/new.txt" 2>/dev/null; then echo "f ok create a file in the place: succeeded"
else echo "f bad create a file in the place: refused"; fi
try g "remount records read-write" mount -o remount,rw "$R"
try h1 "write to records via /proc/self/root" bash -c 'echo via-proc > "/proc/self/root$1/h1.txt"' _ "$R"
if ln -s "$R" "$P/link" 2>/dev/null; then
  try h2 "write to records via a symlink in the place" bash -c 'echo via-link > "$1/link/h2.txt"' _ "$P"
else echo "h2 refused h2 write to records via a symlink in the place: could not make the symlink"; fi
INNER

systemd-run --user --scope --quiet --unit="$UNIT" \
  bwrap --unshare-pid --die-with-parent --bind / / --ro-bind "$R" "$R" --ro-bind "$K" "$K" \
  --dev /dev --proc /proc bash "$WORK/inner.sh" "$R" "$K" "$P" >"$WORK/inner.out" 2>"$WORK/inner.err"
RC=$?

if ! grep -q '^f ' "$WORK/inner.out"; then
  echo "records protection: does not work: the boundary did not run the command (exit $RC): $(tr '\n' ' ' < "$WORK/inner.err" | cut -c1-300)"
  exit 0
fi

THROUGH=""
while read -r code status text; do
  echo "$code: $text"
  [ "$status" = got-through ] && THROUGH="$THROUGH $code"
  [ "$code" = f ] && [ "$status" = bad ] && THROUGH="$THROUGH f(place not writable)"
done < "$WORK/inner.out"

# Verify from outside, by content.
V=""
[ -d "$R" ] && [ "$(ls -A "$R")" = "old.txt" ] && [ "$(cat "$R/old.txt")" = "records original" ] \
  && echo "outside: records unchanged (only old.txt, content 'records original')" \
  || { echo "outside: records CHANGED (listing: $(ls -A "$R" 2>&1 | tr '\n' ' '))"; V="$V records-changed"; }
[ "$(ls -A "$K")" = "old.txt" ] && [ "$(cat "$K/old.txt")" = "kept original" ] \
  && echo "outside: kept unchanged (only old.txt, content 'kept original')" \
  || { echo "outside: kept CHANGED (listing: $(ls -A "$K" 2>&1 | tr '\n' ' '))"; V="$V kept-changed"; }
[ "$(cat "$P/new.txt" 2>/dev/null)" = "new" ] \
  && echo "outside: place holds new.txt with the written content" \
  || { echo "outside: place does not hold new.txt"; V="$V place-missing-new-file"; }

if [ -z "$THROUGH$V" ]; then echo "records protection: works"
else echo "records protection: does not work: got through:${THROUGH:- none inside}; outside check:${V:- clean}"; fi
exit 0
