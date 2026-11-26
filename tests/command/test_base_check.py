"""checks/guard-files.sh and checks/base-check.sh, run for real in temporary git repositories."""

import os
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


class TemporaryRepositoryTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tree = folder.name
        self.git("init", "-q", "-b", "main")
        os.mkdir(os.path.join(self.tree, "checks"))
        for name in ("guard-files.sh", "base-check.sh"):
            shutil.copy(os.path.join(REPO, "checks", name), os.path.join(self.tree, "checks"))
        self.write("checks/all.sh", "#!/bin/sh\necho base script ran\nexit 0\n", executable=True)
        self.write("README.md", "x\n")
        self.base = self.commit("base")

    def git(self, *args):
        result = subprocess.run(
            ["git", *args], cwd=self.tree, env=GIT_ENV, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, name, text, executable=False):
        path = os.path.join(self.tree, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755 if executable else 0o644)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def run_script(self, name, *args):
        return subprocess.run(
            [os.path.join(self.tree, "checks", name), *args],
            cwd=self.tree,
            env=GIT_ENV,
            capture_output=True,
            text=True,
            timeout=60,
        )


class GuardFilesTest(TemporaryRepositoryTest):
    def listed(self, *paths):
        for path in paths:
            self.write(path, "changed\n")
        self.commit("pull request")
        result = self.run_script("guard-files.sh", self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_every_kind_of_guard_file_is_listed_one_line_each_under_a_heading(self):
        guards = [
            "checks/all.sh",
            ".githooks/pre-push",
            ".github/workflows/tests.yml",
            "pyproject.toml",
            "requirements-dev.txt",
            "tests/by_value/test_rules.py",
        ]
        lines = self.listed(*guards)
        self.assertEqual(lines[0], "## This pull request changes the guardrails")
        self.assertIn("The reviewer should read these files:", lines)
        self.assertEqual(
            sorted(line for line in lines if line.startswith("- ")),
            sorted(f"- `{g}`" for g in guards),
        )

    def test_other_files_are_not_listed_even_when_the_name_is_similar(self):
        lines = self.listed(
            "shuttle/core/x.py", "tests/by_value/test_other.py", "docs/pyproject.toml", "checks.md"
        )
        self.assertEqual(lines, ["No guard files changed in this pull request."])

    def test_only_the_guard_files_among_the_changes_are_listed(self):
        lines = self.listed("shuttle/x.py", "pyproject.toml")
        self.assertEqual([x for x in lines if x.startswith("- ")], ["- `pyproject.toml`"])

    def test_no_change_says_so_and_exits_0(self):
        result = self.run_script("guard-files.sh", self.base)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout.splitlines(), ["No guard files changed in this pull request."]
        )

    def test_a_missing_argument_is_refused(self):
        self.assertEqual(self.run_script("guard-files.sh").returncode, 2)


class BaseCheckTest(TemporaryRepositoryTest):
    def pull_request_all_sh(self, exit_code):
        self.write("checks/all.sh", f"#!/bin/sh\necho pr script ran\nexit {exit_code}\n", True)
        self.commit("pull request")

    def test_the_base_script_judges_the_tree_even_when_the_pull_request_weakened_its_own(self):
        self.write("checks/all.sh", "#!/bin/sh\necho base script ran\nexit 1\n", True)
        failing_base = self.commit("a base whose check fails")
        self.pull_request_all_sh(0)  # the weakened copy always passes
        result = self.run_script("base-check.sh", failing_base)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "base check: checks/all.sh differs from the base; running the base's copy",
                "base script ran",
            ],
        )

    def test_a_passing_base_script_passes_and_the_trees_own_script_is_left_in_place(self):
        self.pull_request_all_sh(1)
        result = self.run_script("base-check.sh", self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("base script ran", result.stdout)
        self.assertNotIn("pr script ran", result.stdout)
        with open(os.path.join(self.tree, "checks", "all.sh")) as f:
            self.assertIn("exit 1", f.read())
        self.assertFalse(os.path.exists(os.path.join(self.tree, "checks", "base-all.sh")))

    def test_an_unchanged_script_is_reported_as_the_same(self):
        result = self.run_script("base-check.sh", self.base)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout.splitlines()[0], "base check: checks/all.sh is the same as in the base"
        )

    def test_a_base_without_the_script_could_not_run_exit_2(self):
        self.git("rm", "-q", "checks/all.sh")
        no_script = self.commit("no script")
        result = self.run_script("base-check.sh", no_script)
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not read checks/all.sh", result.stderr)

    def test_a_missing_argument_is_refused_with_exit_3(self):
        self.assertEqual(self.run_script("base-check.sh").returncode, 3)


if __name__ == "__main__":
    unittest.main()
