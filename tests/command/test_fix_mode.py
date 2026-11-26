"""./checks/all.sh --fix, run for real with the real ruff on small trees in temporary folders.

The decisions are tested by value (tests/by_value/test_check_helpers.py); these runs prove the
wiring: two trees that each hold several cases, so few real ruff runs.
Each tree carries the repository's own pyproject.toml, so the rules are the shipped rules.
"""

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "checks", "all.sh")

sys.path.insert(0, os.path.join(REPO, "tests"))
sys.path.insert(0, os.path.join(REPO, "checks"))
names = importlib.import_module("names")
names_table = importlib.import_module("hostile.names_table")
create_all = importlib.import_module("hostile.support").create_all
as_python = importlib.import_module("hostile.support").as_python
# Rows of the names table that ruff itself refuses: it fails on a name that is not valid UTF-8
# (test_a_name_that_is_not_valid_utf8_is_shown_escaped_and_ends_with_a_fix_line covers those).
RUFF_REFUSES = {
    row["label"]: "ruff 0.14.10 fails on a name that is not UTF-8"
    for row in names_table.NAMES
    if any(0xD800 <= ord(c) <= 0xDFFF for c in row["name"])
}

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


def fixmode_failed_line():
    return "fix: failed; ruff could not finish (its output is on standard error)"


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
            "[tool.ruff]\n",
            '[tool.ruff]\nunsafe-fixes = true\nextend-include = ["*.pyw"]\n',
            1,
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
        self.write("w.pyw", "x  =  1\n")  # a file type only the configuration includes
        os.symlink("my file.py", os.path.join(self.tree, "link.py"))  # counted once, not twice
        # a source folder named __pycache__ is not one ruff skips, so it is not skipped here
        os.mkdir(os.path.join(self.tree, "__pycache__"))
        self.write("__pycache__/cached.py", "x  =  1\n")
        # a link to a file outside the tree: ruff rewrites the target; the link is listed
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = os.path.join(outside.name, "outside.py")
        with open(target, "w") as f:
            f.write("x  =  1\n")
        os.symlink(target, os.path.join(self.tree, "out.py"))
        # every file name in the names table that this filesystem holds and ruff accepts
        in_table, _ = create_all(
            self.tree, names_table.NAMES, make=as_python, skip=RUFF_REFUSES, content="x  =  1\n"
        )
        changed = ["__pycache__/cached.py", "a.py", "my file.py", "out.py", "w.pyw"]
        if newline_name:
            changed.append("two\nlines.py")
        changed += in_table.values()
        expected = [f"changed: {names.escape_name(path)}" for path in sorted(changed)]
        expected.append(f"fix: changed {len(changed)} files; now run ./checks/all.sh")

        result = self.script("--fix")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), expected)
        self.assertEqual(self.read("my file.py"), "def f(a):\n    return a\n")
        self.assertEqual(self.read("w.pyw"), "x = 1\n")
        self.assertEqual(self.read("__pycache__/cached.py"), "x = 1\n")
        with open(target) as f:
            self.assertEqual(f.read(), "x = 1\n")
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

    def test_a_name_that_is_not_valid_utf8_is_shown_escaped_and_ends_with_a_fix_line(self):
        # ruff 0.14.10 itself fails on such a name (exit 2, "Failed to serialize cache data")
        try:
            with open(os.path.join(os.fsencode(self.tree), b"bad\xff.py"), "w") as f:
                f.write("import os\n")
        except OSError:
            self.skipTest("this filesystem refuses a name that is not valid UTF-8")
        self.write("ok.py", "import os\n")
        result = self.script("--fix")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(
            result.stdout.splitlines()[-1],
            "fix: failed; ruff could not finish (its output is on standard error)",
        )
        self.assertIn("changed: bad\\xff.py", result.stdout.splitlines())

    def test_whatever_goes_wrong_inside_the_helper_the_last_line_is_a_fix_line(self):
        stub = os.path.join(self.tree, "stub", "ruff")
        os.makedirs(stub)
        with open(os.path.join(stub, "__main__.py"), "w") as f:
            f.write('print(\'{"not": "a list"}\')\n')
        open(os.path.join(stub, "__init__.py"), "w").close()
        env = {"PATH": os.environ["PATH"], "PYTHONPATH": os.path.join(self.tree, "stub")}
        done = subprocess.run(
            [sys.executable, os.path.join(self.tree, "checks", "fixmode.py")],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tree,
            timeout=60,
        )
        self.assertEqual(done.returncode, 1)
        self.assertEqual(
            done.stdout.splitlines(),
            ["fix: failed; ruff could not finish (its output is on standard error)"],
        )

    def test_a_crash_inside_the_helper_still_ends_with_the_fix_line(self):
        env = {"PATH": os.environ["PATH"]}
        code = (
            "import sys; sys.path.insert(0, 'checks'); import fixmode; "
            "fixmode.run = lambda: 1 / 0; sys.exit(fixmode.main())"
        )
        done = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tree,
            timeout=60,
        )
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout.splitlines()[-1], fixmode_failed_line())
        self.assertIn("ZeroDivisionError", done.stderr)

    def test_a_helper_that_cannot_start_still_ends_with_the_fix_line(self):
        helper = os.path.join(self.tree, "checks", "fixmode.py")
        for what, content in (("missing", None), ("not parseable", "def f(:\n")):
            with self.subTest(what=what):
                if content is None:
                    os.remove(helper)
                else:
                    self.write("checks/fixmode.py", content)
                result = self.script("--fix")
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout.splitlines(), [fixmode_failed_line()])

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
