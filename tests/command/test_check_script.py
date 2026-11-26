"""The check script, run for real: its exit code and its last line.

The script's tools are replaced by a stand-in Python (the PYTHON variable) that
passes or fails the stage it is told to, so these tests do not run the real suite.
"""

import os
import stat
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "checks", "all.sh")

STAND_IN = """#!/bin/sh
# Stand-in for python3. FAIL_STAGE is lint, format, types or tests; MISSING is ruff or mypy.
case "$*" in
  "-m ruff --version")  [ "$MISSING" = ruff ] && { echo "No module named ruff" >&2; exit 1; }; exit 0 ;;
  "-m mypy --version")  [ "$MISSING" = mypy ] && { echo "No module named mypy" >&2; exit 1; }; exit 0 ;;
  "-m ruff check"*)     stage=lint ;;
  "-m ruff format"*)    stage=format ;;
  "-m mypy"*)           stage=types ;;
  "-m unittest"*)       stage=tests ;;
  *fixmode.py)          echo "fix: stand-in"; exit 0 ;;
  *) echo "unexpected call: $*" >&2; exit 99 ;;
esac
echo "$stage: tool output"
[ "$FAIL_STAGE" = "$stage" ] && exit "${FAIL_CODE:-1}"
exit 0
"""


class CheckScriptTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.stand_in = os.path.join(folder.name, "python")
        with open(self.stand_in, "w") as f:
            f.write(STAND_IN)
        os.chmod(self.stand_in, os.stat(self.stand_in).st_mode | stat.S_IXUSR)

    def check(self, **env):
        return self.check_args(**env)

    def check_args(self, *args, **env):
        full = {"PATH": os.environ["PATH"], "PYTHON": self.stand_in, **env}
        return subprocess.run(
            [SCRIPT, *args], capture_output=True, text=True, env=full, cwd=REPO, timeout=60
        )

    def last_line(self, result):
        return result.stdout.rstrip("\n").split("\n")[-1]

    def test_all_stages_passing_exits_0_with_one_line_per_stage(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["lint: passed", "format: passed", "types: passed", "tests: passed", "check: passed"],
        )

    def test_a_failing_stage_exits_1_and_the_last_line_names_it(self):
        for stage in ("lint", "format", "types", "tests"):
            with self.subTest(stage=stage):
                result = self.check(FAIL_STAGE=stage)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(
                    self.last_line(result).startswith(f"check: failed: {stage}"),
                    self.last_line(result),
                )
                self.assertIn(f"{stage}: tool output", result.stderr)

    def test_a_failing_format_stage_names_the_command_that_fixes_it(self):
        last = self.last_line(self.check(FAIL_STAGE="format"))
        self.assertEqual(last, "check: failed: format; fix it with: ./checks/all.sh --fix")

    def test_a_tests_stage_ended_by_its_budget_says_it_timed_out(self):
        result = self.check(FAIL_STAGE="tests", FAIL_CODE="124")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.last_line(result), "check: failed: tests (timed out after 20 seconds)"
        )

    def test_a_tests_stage_that_fails_for_another_reason_does_not_say_timed_out(self):
        result = self.check(FAIL_STAGE="tests", FAIL_CODE="3")
        self.assertEqual(self.last_line(result), "check: failed: tests")

    def test_a_failing_stage_stops_the_later_stages(self):
        result = self.check(FAIL_STAGE="lint")
        self.assertEqual(result.stdout.splitlines(), ["lint: failed", "check: failed: lint"])

    def test_a_missing_tool_exits_2_and_names_the_tool_and_the_install_command(self):
        for tool in ("ruff", "mypy"):
            with self.subTest(tool=tool):
                result = self.check(MISSING=tool)
                self.assertEqual(result.returncode, 2)
                last = self.last_line(result)
                self.assertTrue(last.startswith("check: could not run: "), last)
                self.assertIn(tool, last)
                self.assertIn("python3 -m pip install -r requirements-dev.txt", last)

    def test_fix_mode_needs_ruff_only_so_a_missing_mypy_does_not_stop_it(self):
        result = self.check_args("--fix", MISSING="mypy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "fix: stand-in\n")

    def test_fix_mode_without_ruff_could_not_run_exit_2(self):
        result = self.check_args("--fix", MISSING="ruff")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.last_line(result).startswith("check: could not run: ruff"))

    def test_a_missing_tool_runs_no_stage(self):
        result = self.check(MISSING="mypy")
        self.assertNotIn("passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
