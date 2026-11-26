"""./checks/all.sh --fix, run for real with the real ruff on a small tree in a temporary folder.

The tree carries the repository's own pyproject.toml, so the rules are the shipped rules.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "checks", "all.sh")

UNFORMATTED_WITH_UNUSED_IMPORT = "import os\ndef f( a ):\n  return a\n"
TOO_DEEP = """def g(a):
    if a:
        for i in a:
            while i:
                if i:
                    return 1
    return 0
"""
UNUSED_VARIABLE = "def f():\n    x = 1\n    return 2\n"
CLEAN = "def f():\n    return 2\n"


class FixModeTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tree = folder.name
        os.mkdir(os.path.join(self.tree, "checks"))
        shutil.copy(SCRIPT, os.path.join(self.tree, "checks", "all.sh"))
        shutil.copy(os.path.join(REPO, "pyproject.toml"), self.tree)

    def write(self, name, text):
        with open(os.path.join(self.tree, name), "w") as f:
            f.write(text)

    def read(self, name):
        with open(os.path.join(self.tree, name)) as f:
            return f.read()

    def script(self, *args):
        env = {"PATH": os.environ["PATH"], "PYTHON": sys.executable}
        return subprocess.run(
            [os.path.join(self.tree, "checks", "all.sh"), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tree,
            timeout=60,
        )

    def ruff(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "ruff", *args],
            capture_output=True,
            text=True,
            cwd=self.tree,
            timeout=60,
        )

    def test_an_unformatted_file_with_an_unused_import_is_clean_afterwards(self):
        self.write("a.py", UNFORMATTED_WITH_UNUSED_IMPORT)
        result = self.script("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["changed: a.py", "fix: changed 1 file; now run ./checks/all.sh"],
        )
        self.assertEqual(self.read("a.py"), "def f(a):\n    return a\n")
        self.assertEqual(self.ruff("check", ".").returncode, 0)
        self.assertEqual(self.ruff("format", "--check", ".").returncode, 0)

    def test_a_block_nested_too_deep_is_left_alone_and_still_fails_the_check(self):
        self.write("deep.py", TOO_DEEP)
        result = self.script("--fix")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines(), ["fix: nothing to change"])
        self.assertEqual(self.read("deep.py"), TOO_DEEP)
        check = self.script()
        self.assertEqual(check.returncode, 1)
        self.assertEqual(check.stdout.splitlines(), ["lint: failed", "check: failed: lint"])

    def test_a_fix_ruff_marks_unsafe_is_not_applied(self):
        self.write("unused.py", UNUSED_VARIABLE)  # F841: its only fix is marked unsafe
        result = self.script("--fix")
        self.assertEqual(result.stdout.splitlines(), ["fix: nothing to change"])
        self.assertEqual(self.read("unused.py"), UNUSED_VARIABLE)
        self.assertIn("F841", result.stderr)

    def test_on_a_clean_tree_it_changes_nothing_and_says_so(self):
        self.write("clean.py", CLEAN)
        result = self.script("--fix")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines(), ["fix: nothing to change"])
        self.assertEqual(self.read("clean.py"), CLEAN)

    def test_every_changed_file_gets_one_line_and_is_counted(self):
        self.write("a.py", UNFORMATTED_WITH_UNUSED_IMPORT)
        self.write("b.py", UNFORMATTED_WITH_UNUSED_IMPORT)
        self.write("clean.py", CLEAN)
        result = self.script("--fix")
        self.assertEqual(
            result.stdout.splitlines(),
            ["changed: a.py", "changed: b.py", "fix: changed 2 files; now run ./checks/all.sh"],
        )

    def test_a_file_ruff_cannot_parse_ends_with_a_failed_line_and_exit_1(self):
        self.write("broken.py", "def f(:\n")
        result = self.script("--fix")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            ["fix: failed; ruff could not finish (its output is on standard error)"],
        )

    def test_an_unknown_argument_is_refused_with_one_line_on_standard_error(self):
        for args in (["--bogus"], ["--fix", "extra"]):
            with self.subTest(args=args):
                result = self.script(*args)
                self.assertEqual(result.returncode, 3)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr.splitlines(),
                    ["usage: ./checks/all.sh   or   ./checks/all.sh --fix"],
                )


if __name__ == "__main__":
    unittest.main()
