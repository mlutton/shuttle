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

    def git(self, *args, cwd, **env):
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env={**GIT_ENV, **env},
            capture_output=True,
            text=True,
            timeout=60,
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

    def commit_python_reporting_check(self):
        """Commit a check script that reports which PYTHON the hook handed it."""
        path = os.path.join(self.work, "checks", "all.sh")
        with open(path, "w") as f:
            f.write('#!/bin/sh\necho "python=${PYTHON:-none}"\n')
        os.chmod(path, 0o755)
        self.commit_all("check")

    def make_environment(self, folder):
        """A stand-in virtual environment: only its path matters to the hook."""
        python = os.path.join(folder, ".venv", "bin", "python")
        os.makedirs(os.path.dirname(python))
        with open(python, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(python, 0o755)
        return os.path.realpath(python)

    def linked_worktree(self):
        path = os.path.join(os.path.dirname(self.work), "linked")
        result = self.git("worktree", "add", "-q", "-b", "feature", path, cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def push_feature(self, worktree, **env):
        result = self.git("push", "origin", "feature", cwd=worktree, **env)
        return result, result.stdout + result.stderr

    def test_a_push_from_a_linked_worktree_uses_the_main_working_trees_environment(self):
        self.commit_python_reporting_check()
        main_python = self.make_environment(self.work)
        result, output = self.push_feature(self.linked_worktree())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"python={main_python}", output)

    def test_an_explicit_python_wins_over_any_environment_found(self):
        self.commit_python_reporting_check()
        self.make_environment(self.work)
        worktree = self.linked_worktree()
        self.make_environment(worktree)
        _, output = self.push_feature(worktree, PYTHON="/explicit/python")
        self.assertIn("python=/explicit/python", output)

    def test_a_worktree_with_its_own_environment_uses_its_own(self):
        self.commit_python_reporting_check()
        self.make_environment(self.work)
        worktree = self.linked_worktree()
        own_python = self.make_environment(worktree)
        _, output = self.push_feature(worktree)
        self.assertIn(f"python={own_python}", output)

    def test_with_no_environment_anywhere_python_is_left_unset(self):
        self.commit_python_reporting_check()
        _, output = self.push_feature(self.linked_worktree())
        self.assertIn("python=none", output)

    def test_a_push_from_the_main_working_tree_still_uses_its_own_environment(self):
        self.commit_python_reporting_check()
        python = self.make_environment(self.work)
        result = self.git("push", "origin", "main", cwd=self.work)
        self.assertIn(f"python={python}", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
