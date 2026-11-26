#!/bin/sh
# Runs the base commit's checks/all.sh against this tree, so a pull request cannot pass by
# weakening the script that judges it.
# Usage: checks/base-check.sh <base commit>   (run inside the pull request's tree)
# all.sh finds its root from its own location, so the base copy is fetched to a temporary
# file, then placed beside the tree's own as checks/base-all.sh (removed on exit). The tree's
# checks/all.sh stays in place, so the tests that exercise it still see the pull request's.
# Prints whether the two copies differ, then the base script's own output.
# Exit codes: the base script's (0, 1, 2); 2 also when it could not be fetched; 3 on misuse.
[ "$#" -eq 1 ] || { echo "usage: checks/base-check.sh <base commit>" >&2; exit 3; }
root=$(git rev-parse --show-toplevel) || exit 2
scratch=$(mktemp -d) || exit 2
copy="$root/checks/base-all.sh"
trap 'rm -rf "$scratch" "$copy"' EXIT
git -C "$root" show "$1:checks/all.sh" >"$scratch/all.sh" || {
    echo "base check: could not read checks/all.sh at $1" >&2
    exit 2
}
if cmp -s "$scratch/all.sh" "$root/checks/all.sh"; then
    echo "base check: checks/all.sh is the same as in the base"
else
    echo "base check: checks/all.sh differs from the base; running the base's copy"
fi
cp "$scratch/all.sh" "$copy" && chmod +x "$copy" || exit 2
"$copy"
