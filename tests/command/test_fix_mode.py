"""./checks/all.sh --fix, run for real with the real ruff on small trees in temporary folders.

The decisions are tested by value (tests/by_value/test_check_helpers.py); these runs prove the
wiring: two trees that each hold several cases, so few real ruff runs.
Each tree carries the repository's own pyproject.toml, so the rules are the shipped rules.
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
UNUSED_VARIABLE = "def f():\n    x = 1\n    return 2\n"  # F841: its only fix is marked unsafe
CLEAN = "def f():\n    return 2\n"


class TreeTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tree = folder.name
        os.mkdir(os.path.join(self.tree, "checks"))
        shutil.copy(SCRIPT, os.path.join(self.tree, "checks", "all.sh"))
        for helper in ("fixmode.py", "names.py"):
            shutil.copy(os.path.join(REPO, "checks", helper), os.path.join(self.tree, "checks"))
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


class FixModeTest(TreeTest):
    def test_one_tree_with_every_kind_of_file(self):
        # unsafe-fixes = true in the configuration must not turn unsafe fixes on
        config = self.read("pyproject.toml").replace(
            "[tool.ruff]\n", "[tool.ruff]\nunsafe-fixes = true\n", 1
        )
        self.write("pyproject.toml", config)
        self.write("my file.py", UNFORMATTED_WITH_UNUSED_IMPORT)  # a space in the name
        self.write("a.py", UNFORMATTED_WITH_UNUSED_IMPORT)
        self.write("deep.py", TOO_DEEP)
        self.write("unused.py", UNUSED_VARIABLE)
        self.write("clean.py", CLEAN)
        newline_name = "two\nlines.py"
        try:
            self.write(newline_name, UNFORMATTED_WITH_UNUSED_IMPORT)
        except OSError:
            newline_name = None
        expected = ["changed: a.py", "changed: my file.py"]
        if newline_name:
            expected.append("changed: two\\nlines.py")
        expected.append(f"fix: changed {len(expected)} files; now run ./checks/all.sh")

        result = self.script("--fix")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), expected)
        self.assertEqual(self.read("my file.py"), "def f(a):\n    return a\n")
        self.assertEqual(self.read("deep.py"), TOO_DEEP)
        self.assertEqual(self.read("unused.py"), UNUSED_VARIABLE)
        self.assertEqual(self.read("clean.py"), CLEAN)
        self.assertIn("F841", result.stderr)

        again = self.script("--fix")  # nothing left for it to change
        self.assertEqual(again.returncode, 0)
        self.assertEqual(again.stdout.splitlines(), ["fix: nothing to change"])

        check = self.script()  # the unfixable findings still fail the check; the fixed files do not
        self.assertEqual(check.returncode, 1)
        self.assertEqual(check.stdout.splitlines(), ["lint: failed", "check: failed: lint"])
        self.assertIn("deep.py", check.stderr)
        self.assertNotIn("a.py", check.stderr.replace("deep.py", ""))
        self.assertNotIn("my file.py", check.stderr)

    def test_a_file_ruff_cannot_write_or_parse_fails_the_fix_but_what_changed_is_listed(self):
        self.write("ok.py", "import os\nx=1\n")
        self.write("bad.py", "def f(:\n")
        self.write("ro.py", "import os\nx=1\n")
        os.chmod(os.path.join(self.tree, "ro.py"), 0o444)
        if os.access(os.path.join(self.tree, "ro.py"), os.W_OK):
            self.skipTest("running as a user who can write read-only files (root)")
        result = self.script("--fix")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "changed: ok.py",
                "failed: bad.py",
                "failed: ro.py",
                "fix: failed; ruff could not finish (its output is on standard error)",
            ],
        )
        self.assertEqual(self.read("ok.py"), "x = 1\n")
        self.assertEqual(self.read("ro.py"), "import os\nx=1\n")

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
