"""A real git checkout for a test to use as the place of a run: made with the real git, in a
folder the test owns, with a neutral identity so nothing of the machine's configuration is read.
"""

import os
import subprocess

HOME = os.path.join(os.sep, "nonexistent")


def environment():
    return {
        "PATH": os.environ["PATH"],
        "HOME": HOME,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }


def git(folder, *arguments, check=True):
    """Run git in `folder`; its standard output as text, stripped. A failure raises."""
    done = subprocess.run(
        ["git", "-C", folder, *arguments],
        env=environment(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=check,
    )
    return done.stdout.strip()


def commit_everything(folder, message="commit"):
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "--no-verify", "--allow-empty", "-m", message)
    return git(folder, "rev-parse", "HEAD")


def write(folder, name, text):
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def make_checkout(folder, files=None):
    """A git checkout at `folder` (made if it is not there) whose one commit holds `files`
    (name to text); returns the commit."""
    os.makedirs(folder, exist_ok=True)
    git(folder, "init", "-q", "-b", "main")
    for name, text in (files or {"README": "the place\n"}).items():
        write(folder, name, text)
    return commit_everything(folder, "the place")


def make_linked_checkout(main, folder):
    """A linked working copy of the checkout `main`, at `folder`, on a branch of its own."""
    git(main, "worktree", "add", "-q", "-b", os.path.basename(folder) + "-branch", folder)
    return git(folder, "rev-parse", "HEAD")
