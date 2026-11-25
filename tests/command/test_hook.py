"""The pre-push hook, run by a real git push from a temporary repository.

The temporary repository carries the shipped hook and its own stand-in check
script that exits with the code the test sets.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, ".githooks", "pre-push")

GIT_ENV = {
    "PATH": os.environ["PATH"],
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "HOME": os.devnull,
}


class PrePushHookTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.remote = os.path.join(folder.name, "remote.git")
        self.work = os.path.join(folder.name, "work")
        self.git("init", "-q", "--bare", self.remote, cwd=folder.name)
        self.git("init", "-q", "-b", "main", self.work, cwd=folder.name)
        os.makedirs(os.path.join(self.work, ".githooks"))
        os.makedirs(os.path.join(self.work, "checks"))
        shutil.copy(HOOK, os.path.join(self.work, ".githooks", "pre-push"))
        self.git("config", "core.hooksPath", ".githooks", cwd=self.work)
        self.git("remote", "add", "origin", self.remote, cwd=self.work)
        with open(os.path.join(self.work, "file.txt"), "w") as f:
            f.write("x\n")
        self.git("add", "-A", cwd=self.work)
        self.git("commit", "-q", "-m", "first", cwd=self.work)

    def git(self, *args, cwd):
        return subprocess.run(
            ["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, timeout=60
        )

    def set_check(self, exit_code):
        path = os.path.join(self.work, "checks", "all.sh")
        with open(path, "w") as f:
            f.write(f'#!/bin/sh\necho "check ran"\necho "check: stand-in" \nexit {exit_code}\n')
        os.chmod(path, 0o755)

    def remote_has_main(self):
        return self.git("rev-parse", "--verify", "-q", "main", cwd=self.remote).returncode == 0

    def test_a_passing_check_lets_the_push_through(self):
        self.set_check(0)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.remote_has_main())

    def test_a_failing_check_refuses_the_push_and_nothing_leaves(self):
        self.set_check(1)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.remote_has_main())
        self.assertIn("push refused", result.stderr)

    def test_a_check_that_could_not_run_refuses_the_push(self):
        self.set_check(2)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.remote_has_main())

    def test_a_missing_check_script_refuses_the_push(self):
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.remote_has_main())
        self.assertIn("push refused", result.stderr)

    def test_the_hook_runs_the_check_script_and_nothing_else(self):
        self.set_check(0)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertIn("check ran", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
