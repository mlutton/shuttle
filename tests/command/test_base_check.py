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


COULD_NOT = "The guard file listing could not be produced; see the job log for why."


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

    def run_script(self, name, *args, path="", python=None):
        env = {**GIT_ENV, "PATH": path + GIT_ENV["PATH"]}
        if python:
            env["PYTHON"] = python
        return subprocess.run(
            [os.path.join(self.tree, "checks", name), *args],
            cwd=self.tree,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )


class GuardFilesTest(TemporaryRepositoryTest):
    def setUp(self):
        super().setUp()
        for name in ("guards.py", "names.py"):
            shutil.copy(os.path.join(REPO, "checks", name), os.path.join(self.tree, "checks"))
        self.write("pyproject.toml", "x\n")
        self.write(".github/w.yml", "x\n")
        self.base = self.commit("base with guards")

    def listing(self):
        self.commit("pull request")
        result = self.run_script("guard-files.sh", self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_changed_added_and_deleted_guard_files_are_listed_with_what_happened(self):
        self.write("pyproject.toml", "changed\n")
        self.write("requirements-dev.txt", "new\n")
        self.write("shuttle/x.py", "not a guard\n")
        self.git("rm", "-q", ".github/w.yml")
        out = self.listing()
        self.assertIn("## This pull request changes the guardrails", out)
        lines = out.splitlines()
        self.assertIn("changed pyproject.toml", lines)
        self.assertIn("added   requirements-dev.txt", lines)
        self.assertIn("deleted .github/w.yml", lines)
        self.assertNotIn("shuttle/x.py", out)

    def test_a_guard_file_moved_away_is_listed_as_deleted(self):
        os.makedirs(os.path.join(self.tree, ".githubx"))
        self.git("mv", "pyproject.toml", "old.toml")
        self.git("mv", ".github/w.yml", ".githubx/w.yml")
        lines = self.listing().splitlines()
        self.assertIn("deleted pyproject.toml", lines)
        self.assertIn("deleted .github/w.yml", lines)
        self.assertNotIn("old.toml", "\n".join(lines))

    def test_a_non_ascii_guard_file_is_listed(self):
        self.write("checks/\u00e9.sh", "x\n")
        self.assertIn("checks/\u00e9.sh", self.listing())

    def test_names_with_a_backtick_or_a_newline_cannot_break_the_block(self):
        self.write("checks/a`b.sh", "x\n")
        try:
            self.write("checks/x\n```\n# injected.sh", "x\n")
        except OSError:
            self.skipTest("this filesystem does not allow a newline in a file name")
        lines = self.listing().splitlines()
        fences = [x for x in lines if x.startswith("```")]
        self.assertEqual(len(fences), 2, lines)
        self.assertEqual(fences[0], fences[1])
        self.assertNotIn("# injected.sh", lines)
        self.assertTrue(any(x.endswith("checks/x\\n```\\n# injected.sh") for x in lines))

    def test_no_change_says_so_and_exits_0(self):
        result = self.run_script("guard-files.sh", self.base)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout.splitlines(), ["No guard files changed in this pull request."]
        )

    def test_a_comparison_git_cannot_make_says_so_on_standard_output_and_exits_1(self):
        result = self.run_script("guard-files.sh", "0" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [COULD_NOT],
        )
        self.assertNotEqual(result.stderr, "")

    def test_a_guard_file_whose_name_is_not_valid_utf8_is_listed_escaped(self):
        try:
            with open(os.path.join(os.fsencode(self.tree), b"checks", b"bad\xff.sh"), "w") as f:
                f.write("x\n")
        except OSError:
            self.skipTest("this filesystem refuses a name that is not valid UTF-8")
        self.assertIn("added   checks/bad\\xff.sh", self.listing().splitlines())

    def test_an_unexpected_failure_still_ends_with_the_could_not_be_produced_line(self):
        stub = os.path.join(self.tree, "stub")
        os.mkdir(stub)
        git = os.path.join(stub, "git")
        with open(git, "w") as f:
            f.write("#!/bin/sh\nprintf 'M\\0a\\0D'\n")  # an odd count of fields
        os.chmod(git, 0o755)
        result = self.run_script("guard-files.sh", self.base, path=stub + os.pathsep)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.splitlines(), [COULD_NOT])
        self.assertIn("Traceback", result.stderr)

    def test_a_helper_that_cannot_run_or_prints_nothing_still_gets_the_line_and_a_failure(self):
        for python in ("/nonexistent/python", "/bin/true"):
            with self.subTest(python=python):
                result = self.run_script("guard-files.sh", self.base, python=python)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout.splitlines(), [COULD_NOT])

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

    def test_a_tree_that_already_has_base_all_sh_is_refused_and_the_file_is_left_alone(self):
        self.write("checks/base-all.sh", "mine\n")
        result = self.run_script("base-check.sh", self.base)
        self.assertEqual(result.returncode, 2)
        self.assertIn("checks/base-all.sh already exists", result.stderr)
        with open(os.path.join(self.tree, "checks", "base-all.sh")) as f:
            self.assertEqual(f.read(), "mine\n")

    def test_a_missing_argument_is_refused_with_exit_3(self):
        self.assertEqual(self.run_script("base-check.sh").returncode, 3)


if __name__ == "__main__":
    unittest.main()
