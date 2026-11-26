"""The place: a linked working copy of the caller's repository, as pure decisions.

Looking at the place and freezing it are done through the world's git operations
(shuttle.core.shapes.GitOperations); what is found, and what to make of it, is decided here.

Every git call Shuttle makes is given exactly the environment built here, so it reads nothing of
the caller's: not their global or system configuration, hooks, signing settings, identity,
editor, ignore file or attributes, and never asks a question. Settings written in the place's
own repository configuration are overridden the same way (git reads configuration passed through
`GIT_CONFIG_COUNT` last).
"""

import re

from shuttle.core import boundary
from shuttle.core.refusals import Found
from shuttle.core.shapes import FreezeAnswer, PlaceFacts, StepResult

_INPUT = "input_check"

# Settings that are the same for every call. A pair is (name, value).
_FIXED_SETTINGS = (
    ("core.hooksPath", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("core.untrackedCache", "false"),
    ("core.autocrlf", "false"),
    ("core.safecrlf", "false"),
    ("core.excludesFile", "/dev/null"),
    ("core.attributesFile", "/dev/null"),
    ("commit.gpgsign", "false"),
    ("tag.gpgsign", "false"),
    ("gc.auto", "0"),
    ("maintenance.auto", "false"),
)

NEUTRAL_NAME = "Shuttle"
# The neutral author and committer: a name, no address and a fixed date, so the same files give
# the same commit.
_NEUTRAL_DATE = "946684800 +0000"

# How many names an explanation of what is unclean lists.
_NAMES_SHOWN = 3


def git_environment(path: str | None) -> dict[str, str]:
    """The whole environment of a git call: PATH (so git is found) and what makes the call
    independent of the caller's configuration, with the neutral identity."""
    environment = {} if path is None else {"PATH": path}
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",  # looking never rewrites the caller's index
            "GIT_EDITOR": ":",
            "GIT_ASKPASS": ":",
            "GIT_CONFIG_COUNT": str(len(_FIXED_SETTINGS)),
            "GIT_AUTHOR_NAME": NEUTRAL_NAME,
            "GIT_AUTHOR_EMAIL": "",
            "GIT_AUTHOR_DATE": _NEUTRAL_DATE,
            "GIT_COMMITTER_NAME": NEUTRAL_NAME,
            "GIT_COMMITTER_EMAIL": "",
            "GIT_COMMITTER_DATE": _NEUTRAL_DATE,
            "LC_ALL": "C",
        }
    )
    for number, (name, value) in enumerate(_FIXED_SETTINGS):
        environment[f"GIT_CONFIG_KEY_{number}"] = name
        environment[f"GIT_CONFIG_VALUE_{number}"] = value
    return environment


def usable_place(place: object) -> bool:
    """A place that can be looked at: text, not empty, and a path (no NUL)."""
    return isinstance(place, str) and bool(place) and "\0" not in place


def _shown(names: list[str]) -> str:
    listed = ", ".join(repr(name) for name in names[:_NAMES_SHOWN])
    more = len(names) - _NAMES_SHOWN
    return listed + (f" and {more} more" if more > 0 else "")


def check_place(place: object, facts: PlaceFacts | None) -> Found | None:
    """The refusal for what looking at the place found, or None when the place may be run on.

    `facts` is None when the place could not be looked at (no usable path given). A nested
    repository is named before the unclean state it also causes (git lists it as a new file).
    """
    if facts is None or not usable_place(place) or not facts["exists"]:
        return _refused(
            "place_missing",
            f"the place {place!r} is not a folder that is there; give the path of a linked "
            "working copy of the repository",
        )
    if not facts["is_checkout"] or not facts["head"]:
        return _refused(
            "place_not_a_git_checkout",
            f"the place {place!r} is not the top of a git working copy with a commit; give a "
            "checkout made for this run (for instance with git worktree add)",
        )
    if facts["nested"]:
        return _refused(
            "place_has_nested_repository",
            f"the place {place!r} holds a repository of its own at {_shown(facts['nested'])}; "
            "remove it from the place",
        )
    if facts["unclean"]:
        return _refused(
            "place_has_uncommitted_changes",
            f"the place {place!r} has uncommitted or new unignored files: "
            f"{_shown(facts['unclean'])}; commit them, remove them or ignore them",
        )
    return None


def _refused(reason: str, problem: str) -> Found:
    return {"reason": reason, "step": _INPUT, "problem": problem}


_COMMIT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def opening_result(refusal: Found | None, facts: PlaceFacts | None, seconds: float) -> StepResult:
    """The opening fingerprint step's result: the place's own commit, taken after the checkout
    was confirmed clean. A place that is not clean now has no fingerprint."""
    if refusal or facts is None or facts["head"] is None:
        return {"ok": False, "duration_seconds": seconds}
    return {"ok": True, "fingerprint": facts["head"], "duration_seconds": seconds}


# The closing freeze. The place's files as they are, whatever the place's own history says, go
# into one commit made to a reference of Shuttle's own: a temporary index (never the place's own)
# is filled from the opening commit, then from every file in the place that the place's ignore
# rules do not exclude, and written as a tree. A tree equal to the opening commit's is the
# opening commit itself (nothing changed, nothing made); any other is committed with the opening
# commit as its parent, under the neutral identity of `git_environment`. Plumbing only: no hook
# runs and nothing is signed. The script is the whole of the freeze's git work, so one scope
# with one limit holds it. It is given the place, the opening commit, the reference and the
# message as arguments, never pasted into the text of the script. It ends by printing `done`.
FREEZE_SCRIPT = (
    "unset "
    + " ".join(boundary.BUS_VARIABLES)
    + r"""
set -e
cd -- "$1"
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
export GIT_INDEX_FILE="$scratch/index"
git read-tree "$2"
git add -A
tree=$(git write-tree)
commit=$2
if [ "$tree" != "$(git rev-parse "$2^{tree}")" ]; then
    commit=$(git commit-tree "$tree" -p "$2" -m "$4")
    git update-ref "$3" "$commit"
fi
git diff-tree -r -z --no-renames --name-only --diff-filter=A "$2" "$tree" > "$scratch/added"
git diff-tree -r -z --no-renames --name-only --diff-filter=MT "$2" "$tree" > "$scratch/changed"
git diff-tree -r -z --no-renames --name-only --diff-filter=D "$2" "$tree" > "$scratch/deleted"
echo "commit $commit"
echo "added $(tr -cd '\0' < "$scratch/added" | wc -c)"
echo "changed $(tr -cd '\0' < "$scratch/changed" | wc -c)"
echo "deleted $(tr -cd '\0' < "$scratch/deleted" | wc -c)"
echo done
"""
)


def freeze_reference(request_id: str) -> str:
    """The reference the closing commit is made to: Shuttle's own, one per run."""
    return f"refs/shuttle/freeze/{request_id}"


def freeze_message(request_id: str) -> str:
    return f"shuttle: the files of the place at the end of request {request_id}"


def freeze_argv(
    scope: str, limit_seconds: float, place: str, opening: str, request_id: str
) -> list[str]:
    """The command that runs the freeze in a scope of its own with the limit on the scope.

    Raises ValueError for an opening commit that is not a commit id (it is passed on to git, and
    must never read as an option)."""
    if not _COMMIT_ID.fullmatch(opening):
        raise ValueError("the opening fingerprint is not a commit id")
    return boundary.scoped_argv(
        scope,
        limit_seconds,
        [
            "sh",
            "-c",
            FREEZE_SCRIPT,
            "sh",
            place,
            opening,
            freeze_reference(request_id),
            freeze_message(request_id),
        ],
    )


def _count(value: str) -> int | None:
    return int(value) if value.isascii() and value.isdigit() else None


def parse_freeze_output(output: bytes) -> tuple[str, int, int, int] | None:
    """(commit, files added, changed, deleted) from what the script printed, or None when it is
    not exactly what the script prints on success (which ends with the line `done`)."""
    lines = output.decode("utf-8", errors="replace").split("\n")
    if lines[-2:] != ["done", ""] or len(lines) != 6:
        return None
    parts = [line.partition(" ") for line in lines[:4]]
    if [head for head, _, _ in parts] != ["commit", "added", "changed", "deleted"]:
        return None
    commit = parts[0][2]
    numbers = [_count(rest.strip()) for _, _, rest in parts[1:]]
    if not _COMMIT_ID.fullmatch(commit) or None in numbers:
        return None
    added, changed, deleted = (n for n in numbers if n is not None)
    return commit, added, changed, deleted


def closing_result(answer: FreezeAnswer | None, why_ended: str, seconds: float) -> StepResult:
    """The closing freeze step's result, from how the freeze's scope ended (`why_ended` is
    boundary.why_ended, read after the scope was stopped) and what the command said. Anything
    short of a full answer from a scope seen to end by itself is a failed freeze with no
    fingerprint and no counts."""
    failed: StepResult = {"ok": False, "duration_seconds": seconds}
    if answer is None:
        failed["problem"] = _failure("its command could not be started")
    elif why_ended == boundary.TIMED_OUT:
        failed["problem"] = _failure("it ran out of its limit")
    elif why_ended != boundary.ENDED:
        failed["problem"] = _failure("its scope could not be seen to end")
    elif answer.status != 0:
        failed["problem"] = _failure(f"git ended with status {answer.status}")
    elif (parsed := parse_freeze_output(answer.output)) is None:
        failed["problem"] = _failure("it did not give the answer it gives when it is done")
    else:
        commit, added, changed, deleted = parsed
        return {
            "ok": True,
            "fingerprint": commit,
            "files_added": added,
            "files_changed": changed,
            "files_deleted": deleted,
            "duration_seconds": seconds,
        }
    return failed


def _failure(why: str) -> str:
    return (
        f"the closing freeze failed ({why}); the files of the place were not frozen, so there is "
        "no closing fingerprint; the opening fingerprint stands and the place is left as found"
    )
