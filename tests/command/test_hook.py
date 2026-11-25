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

    def commit_check(self, exit_code):
        """Commit a stand-in check script that exits with this code."""
        path = os.path.join(self.work, "checks", "all.sh")
        with open(path, "w") as f:
            f.write(f'#!/bin/sh\necho "check ran"\nexit {exit_code}\n')
        os.chmod(path, 0o755)
        self.commit_all("check")

    def commit_all(self, message):
        self.git("add", "-A", ".", ":!.githooks", cwd=self.work)
        self.git("commit", "-q", "-m", message, cwd=self.work)

    def commit_state(self, state):
        """Commit a stand-in check script that passes when state.txt says 'pass'."""
        path = os.path.join(self.work, "checks", "all.sh")
        with open(path, "w") as f:
            f.write(
                '#!/bin/sh\ncd "$(dirname "$0")/.." || exit 2\nread state < state.txt\necho "check saw $state"\n[ "$state" = pass ]\n'
            )
        os.chmod(path, 0o755)
        self.write_state(state)
        self.commit_all("state " + state)

    def write_state(self, state):
        with open(os.path.join(self.work, "state.txt"), "w") as f:
            f.write(state + "\n")

    def remote_has_main(self):
        return self.git("rev-parse", "--verify", "-q", "main", cwd=self.remote).returncode == 0

    def test_a_passing_check_lets_the_push_through(self):
        self.commit_check(0)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.remote_has_main())

    def test_a_failing_check_refuses_the_push_and_nothing_leaves(self):
        self.commit_check(1)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.remote_has_main())
        self.assertIn("push refused", result.stderr)

    def test_a_check_that_could_not_run_refuses_the_push(self):
        self.commit_check(2)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.remote_has_main())

    def test_a_pushed_commit_that_fails_is_refused_though_the_folder_is_fixed_and_passing(self):
        self.commit_state("fail")
        self.write_state("pass")  # an uncommitted fix
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.remote_has_main())
        self.assertIn("check saw fail", result.stdout + result.stderr)

    def test_a_pushed_commit_that_passes_is_allowed_though_the_folder_is_broken(self):
        self.commit_state("pass")
        self.write_state("fail")  # uncommitted breakage
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.remote_has_main())
        self.assertIn("check saw pass", result.stdout + result.stderr)

    def test_every_ref_pushed_is_checked(self):
        self.commit_state("pass")
        self.git("branch", "good", cwd=self.work)
        self.commit_state("fail")
        result = self.git("push", "origin", "main", "good", cwd=self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.remote_has_main())

    def test_deleting_a_remote_branch_needs_no_check(self):
        self.commit_check(0)
        self.git("push", "origin", "main:extra", cwd=self.work)
        self.commit_check(1)
        result = self.git("push", "origin", ":extra", cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_missing_check_script_refuses_the_push(self):
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.remote_has_main())
        self.assertIn("push refused", result.stderr)

    def test_the_hook_runs_the_check_script_and_nothing_else(self):
        self.commit_check(0)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertIn("check ran", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
