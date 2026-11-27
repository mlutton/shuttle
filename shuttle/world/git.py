"""The place's repository: the real set.

Every call is made with exactly the environment it is given and nothing from the caller's; the
shell builds it (shuttle.core.place.git_environment).
"""

import os
import re
import subprocess
from collections.abc import Mapping, Sequence

from shuttle.core.shapes import FreezeAnswer, GitOperations, PlaceFacts

_COMMIT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _git(
    place: str, environment: Mapping[str, str], *arguments: str, given: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", place, *arguments],
        env=dict(environment),
        input=given,
        stdin=None if given is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _nested_repositories(place: str) -> list[str]:
    """Folders below the top of the place that hold a `.git` (a folder or a file), whether or
    not git ignores them. Links are not followed and a repository found is not entered."""

    def refuse(error: OSError) -> None:
        raise error

    found: list[str] = []
    for folder, names, files in os.walk(place, onerror=refuse):
        if folder == place:
            names[:] = [name for name in names if name != ".git"]
            continue
        if ".git" in names or ".git" in files:
            found.append(os.path.relpath(folder, place))
            names.clear()
    return found


def _filtered_paths(place: str, environment: Mapping[str, str]) -> list[str]:
    """Tracked paths that carry a `filter` attribute (set, unset or given a value), by every
    source git reads attributes from. Reading attributes runs no command."""
    listed = _git(place, environment, "ls-files", "-z")
    if listed.returncode != 0:
        raise OSError(f"git ls-files failed with status {listed.returncode}")
    if not listed.stdout:
        return []
    asked = _git(place, environment, "check-attr", "-z", "--stdin", "filter", given=listed.stdout)
    if asked.returncode != 0:
        raise OSError(f"git check-attr failed with status {asked.returncode}")
    fields = asked.stdout.split(b"\0")
    triples = zip(fields[0::3], fields[2::3], strict=False)
    return sorted({os.fsdecode(path) for path, value in triples if value != b"unspecified"})


def look_at_place(place: str, environment: Mapping[str, str]) -> PlaceFacts:
    missing: PlaceFacts = {
        "exists": False,
        "is_checkout": False,
        "head": None,
        "unclean": [],
        "nested": [],
        "filtered": [],
    }
    if not os.path.isdir(place):
        return missing
    top = _git(place, environment, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or os.path.realpath(os.fsdecode(top.stdout.rstrip(b"\n"))) != (
        os.path.realpath(place)
    ):
        return {**missing, "exists": True}
    commit = _git(place, environment, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    text = os.fsdecode(commit.stdout).strip()
    head = text if commit.returncode == 0 and _COMMIT_ID.fullmatch(text) else None
    if head is None:
        return {**missing, "exists": True, "is_checkout": True}
    # before the status: comparing a file with a driver's attribute would run the driver
    filtered = _filtered_paths(place, environment)
    if filtered:
        return {
            "exists": True,
            "is_checkout": True,
            "head": head,
            "unclean": [],
            "nested": [],
            "filtered": filtered,
        }
    status = _git(
        place,
        environment,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=normal",
        "--no-renames",
    )
    if status.returncode != 0:
        raise OSError(f"git status failed with status {status.returncode}")
    entries = [os.fsdecode(entry[3:]) for entry in status.stdout.split(b"\0") if entry]
    return {
        "exists": True,
        "is_checkout": True,
        "head": head,
        "unclean": entries,
        "nested": _nested_repositories(place),
        "filtered": [],
    }


def git_folders(place: str, environment: Mapping[str, str]) -> list[str]:
    found: list[str] = []
    for option in ("--git-dir", "--git-common-dir"):
        done = _git(place, environment, "rev-parse", "--path-format=absolute", option)
        if done.returncode != 0 or not done.stdout.endswith(b"\n"):
            return []
        # one name and its line end: the name may hold a line end itself, so it is cut by one
        found.append(os.path.realpath(os.fsdecode(done.stdout[:-1])))
    return list(dict.fromkeys(found))


def freeze(command: Sequence[str], environment: Mapping[str, str]) -> FreezeAnswer:
    done = subprocess.run(
        list(command),
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return FreezeAnswer(done.returncode, done.stdout)


GIT = GitOperations(look_at_place=look_at_place, git_folders=git_folders, freeze=freeze)
