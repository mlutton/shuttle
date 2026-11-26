"""./checks/report.sh, run for real (one real coverage run) on a tiny temporary project.

The report's content is tested by value (tests/by_value/test_report.py); these runs prove the
wiring: that the numbers in a real report match the project they were run on, that code run
in a child process is counted, and that a report that cannot be made still says so in a line.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODULE = """def add(a, b):
    return a + b


def never(x):
    y = x + 1
    return y


def elsewhere():  # not tested: reached only on a machine this project does not have
    return 1


def in_a_child():
    return 2
"""
TESTS = """import subprocess
import sys
import unittest

from shuttle.core import m


class Tiny(unittest.TestCase):
    def test_add(self):
        self.assertEqual(m.add(1, 2), 3)

    def test_child(self):
        code = "from shuttle.core import m; raise SystemExit(m.in_a_child() - 2)"
        self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 0)

    @unittest.skip("no reason but this one")
    def test_skipped(self):
        pass
"""
COULD_NOT = "The test report could not be produced"


class ReportTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tree = folder.name
        os.mkdir(os.path.join(self.tree, "checks"))
        for name in ("report.sh", "report.py", "timed_tests.py", "names.py"):
            shutil.copy(os.path.join(REPO, "checks", name), os.path.join(self.tree, "checks"))
        with open(os.path.join(REPO, "pyproject.toml"), encoding="utf-8") as f:
            config = f.read().replace('source = ["shuttle", "checks"]', 'source = ["shuttle"]')
        self.write("pyproject.toml", config)
        for name in (
            "shuttle/__init__.py",
            "shuttle/core/__init__.py",
            "tests/by_value/__init__.py",
        ):
            self.write(name, "")
        self.write("shuttle/core/m.py", MODULE)
        self.write("tests/by_value/test_m.py", TESTS)

    def write(self, name, text):
        path = os.path.join(self.tree, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def report(self, **extra):
        env = {"PATH": os.environ["PATH"], "PYTHON": sys.executable, **extra}
        return subprocess.run(
            [os.path.join(self.tree, "checks", "report.sh")],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.tree,
            timeout=120,
        )

    def test_the_numbers_match_the_project_and_the_child_process_is_counted(self):
        result = self.report()
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertIn("- 3 run: 2 passed, 1 skipped, 0 failed, 0 errors.", lines)
        self.assertIn("by_value.test_m.Tiny.test_skipped: no reason but this one", lines)
        self.assertTrue(any(re.fullmatch(r"- Total time: \d+\.\d{3} s .*", x) for x in lines))
        self.assertTrue(any(x.startswith("- Peak memory: ") for x in lines))
        self.assertTrue(any(re.fullmatch(r"by_value\s+3 tests\s+\d+\.\d{3} s", x) for x in lines))
        # statements: 2 in add, 3 in never, 2 in in_a_child; elsewhere is marked, so not counted.
        # Never run: lines 6-7 of never. in_a_child ran only in a child process.
        row = next(x for x in lines if x.startswith("shuttle/core/m.py "))
        self.assertRegex(row, r"shuttle/core/m\.py\s+7\s+2\s+71%\s+6-7$")
        self.assertIn(
            "shuttle/core/m.py:10  reached only on a machine this project does not have", lines
        )
        self.assertTrue(any(x.startswith("Commit `unknown (") for x in lines), result.stdout)
        self.assertIn("command `./checks/report.sh`", result.stdout)
        # nothing was left behind in the tree
        left = [n for n in os.listdir(self.tree) if n.startswith(".coverage")]
        self.assertEqual(left, [])

    def test_a_report_that_cannot_be_made_is_one_line_saying_so_and_why(self):
        os.remove(os.path.join(self.tree, "pyproject.toml"))
        result = self.report()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        self.assertTrue(result.stdout.startswith(COULD_NOT), result.stdout)
        self.assertIn("FileNotFoundError", result.stdout)

    def test_a_helper_that_cannot_start_or_prints_nothing_still_gets_the_line(self):
        for what in ("missing", "not parseable", "prints nothing"):
            with self.subTest(what=what):
                helper = os.path.join(self.tree, "checks", "report.py")
                python = sys.executable
                if what == "missing":
                    os.remove(helper)
                elif what == "not parseable":
                    self.write("checks/report.py", "def f(:\n")
                else:
                    python = "/bin/true"
                result = self.report(PYTHON=python)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    result.stdout.splitlines(),
                    ["The test report could not be produced; see the job log for why."],
                )


if __name__ == "__main__":
    unittest.main()
