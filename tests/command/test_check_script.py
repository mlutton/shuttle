"""The check script, run for real: its exit code and its last line.

The script's tools are replaced by a stand-in Python (the PYTHON variable) that
passes or fails the stage it is told to, so these tests do not run the real suite.
"""

import os
import resource
import shutil
import stat
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "checks", "all.sh")
INTERPRETER = os.path.join(REPO, "checks", "interpreter.sh")
FILE_BLOCKS = 262144  # the limits the script sets on its real stage, as `ulimit -f` and `-v` count
ADDRESS_KB = 3145728
FIX_FAILED = "fix: failed; ruff could not finish (its output is on standard error)"

STAND_IN = """#!/bin/sh
# Stand-in for python3. FAIL_STAGE is lint, format, types, tests or real; MISSING is ruff, mypy or coverage.
case "$*" in
  "-m ruff --version")  [ "$MISSING" = ruff ] && { echo "No module named ruff" >&2; exit 1; }; exit 0 ;;
  "-m mypy --version")  [ "$MISSING" = mypy ] && { echo "No module named mypy" >&2; exit 1; }; exit 0 ;;
  "-m coverage --version")  [ "$MISSING" = coverage ] && { echo "No module named coverage" >&2; exit 1; }; exit 0 ;;
  "-m ruff check"*)     stage=lint ;;
  "-m ruff format"*)    stage=format ;;
  "-m mypy"*)           stage=types ;;
  "-m unittest discover -s tests/by_value"*)  stage=tests ;;
  "-m unittest discover -s tests/command"*)   stage=real ;;
  "-m unittest discover -s tests/boundary"*)  stage=real ;;
  *fixmode.py)          echo "fix: stand-in"; exit "${FIX_EXIT:-0}" ;;
  *) echo "unexpected call: $*" >&2; exit 99 ;;
esac
[ -n "$LIMITS_FILE" ] && echo "$stage: file blocks $(ulimit -f), address kilobytes $(ulimit -v)" >> "$LIMITS_FILE"
echo "$stage: tool output"
[ "$FAIL_STAGE" = "$stage" ] && exit "${FAIL_CODE:-1}"
exit 0
"""


def outer_limit_is_lower(which, kilobytes):
    """Whether this process's own hard limit is below what the script sets (a limit counted in
    kilobytes here), so the script would refuse to run."""
    hard = resource.getrlimit(which)[1]
    return hard != resource.RLIM_INFINITY and hard < kilobytes * 1024


def skip_when_the_script_would_refuse(case):
    if outer_limit_is_lower(resource.RLIMIT_AS, ADDRESS_KB) or outer_limit_is_lower(
        resource.RLIMIT_FSIZE, FILE_BLOCKS // 2
    ):
        case.skipTest("this shell's own limit is below the script's; the script refuses to run")


class CheckScriptTest(unittest.TestCase):
    def setUp(self):
        skip_when_the_script_would_refuse(self)
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
            [
                "lint: passed",
                "format: passed",
                "types: passed",
                "tests: passed",
                "real: passed",
                "check: passed",
            ],
        )

    def test_a_failing_stage_exits_1_and_the_last_line_names_it(self):
        for stage in ("lint", "format", "types", "tests", "real"):
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

    def test_a_real_stage_ended_by_its_budget_says_it_timed_out(self):
        result = self.check(FAIL_STAGE="real", FAIL_CODE="124")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            self.last_line(result), "check: failed: real (timed out after 120 seconds)"
        )

    def test_a_real_stage_that_fails_for_another_reason_does_not_say_timed_out(self):
        result = self.check(FAIL_STAGE="real", FAIL_CODE="3")
        self.assertEqual(self.last_line(result), "check: failed: real")

    def test_the_real_stage_runs_under_a_file_size_limit_and_an_address_space_limit(self):
        record = os.path.join(os.path.dirname(self.stand_in), "limits")
        result = self.check(LIMITS_FILE=record)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(record) as f:
            lines = f.read().splitlines()
        limits = f"file blocks {FILE_BLOCKS}, address kilobytes {ADDRESS_KB}"
        self.assertEqual(
            [line for line in lines if line.startswith("real:")],
            [f"real: {limits}", f"real: {limits}"],
        )

    def test_a_limit_the_shell_will_not_raise_is_could_not_run_naming_the_limit_and_the_fix(self):
        lowered = {
            "address-space": (resource.RLIMIT_AS, ADDRESS_KB * 1024 // 2, "-v"),
            "file-size": (resource.RLIMIT_FSIZE, FILE_BLOCKS * 512 // 2, "-f"),
        }
        for name, (which, size, option) in lowered.items():
            with self.subTest(limit=name):
                result = subprocess.run(
                    [SCRIPT],
                    capture_output=True,
                    text=True,
                    env={"PATH": os.environ["PATH"], "PYTHON": self.stand_in},
                    cwd=REPO,
                    timeout=60,
                    preexec_fn=lambda which=which, size=size: resource.setrlimit(
                        which, (size, size)
                    ),
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(
                    self.last_line(result),
                    f"check: could not run: the real stage's {name} limit cannot be set, because "
                    f"this shell's own limit is lower; raise it (ulimit {option}) or start a "
                    "shell without it",
                )
                self.assertNotIn("real:", result.stdout)

    def test_a_failing_stage_stops_the_later_stages(self):
        result = self.check(FAIL_STAGE="lint")
        self.assertEqual(result.stdout.splitlines(), ["lint: failed", "check: failed: lint"])

    def test_a_missing_tool_exits_2_and_names_the_tool_and_the_install_command(self):
        for tool in ("ruff", "mypy", "coverage"):
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

    def test_fix_mode_does_not_need_coverage_either(self):
        result = self.check_args("--fix", MISSING="coverage")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_helper_that_dies_by_signal_after_its_last_line_still_gives_a_documented_code(self):
        for code in (139, 2):
            with self.subTest(code=code):
                result = self.check_args("--fix", FIX_EXIT=str(code))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.last_line(result), FIX_FAILED)

    def test_fix_mode_without_ruff_could_not_run_exit_2(self):
        result = self.check_args("--fix", MISSING="ruff")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(self.last_line(result).startswith("check: could not run: ruff"))

    def test_a_missing_tool_runs_no_stage(self):
        result = self.check(MISSING="mypy")
        self.assertNotIn("passed", result.stdout)


GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}
# A stand-in interpreter that names itself on standard error and fails the lint stage.
NAMING = '#!/bin/sh\ncase "$*" in *--version) exit 0 ;; esac\necho "ran: LABEL" >&2\nexit 1\n'


class InterpreterLookupTest(unittest.TestCase):
    """Which interpreter all.sh picks when PYTHON is unset, in a clone and a linked worktree."""

    def setUp(self):
        skip_when_the_script_would_refuse(self)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = folder.name
        self.main = os.path.join(self.root, "main")
        self.linked = os.path.join(self.root, "linked")
        self.git("init", "-q", "-b", "main", self.main, cwd=self.root)
        os.mkdir(os.path.join(self.main, "checks"))
        shutil.copy(SCRIPT, os.path.join(self.main, "checks", "all.sh"))
        shutil.copy(INTERPRETER, os.path.join(self.main, "checks", "interpreter.sh"))
        self.git("add", ".", cwd=self.main)
        self.git("commit", "-q", "-m", "x", cwd=self.main)
        self.git("worktree", "add", "-q", "-b", "feature", self.linked, cwd=self.main)

    def git(self, *args, cwd):
        env = {"PATH": os.environ["PATH"], **GIT_ENV}
        subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)

    def interpreter(self, path, label):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(NAMING.replace("LABEL", label))
        os.chmod(path, 0o755)

    def run_in(self, tree, **env):
        bin_dir = os.path.join(self.root, "bin")
        self.interpreter(os.path.join(bin_dir, "python3"), "python3")
        full = {"PATH": bin_dir + os.pathsep + os.environ["PATH"], **GIT_ENV, **env}
        result = subprocess.run(
            [os.path.join(tree, "checks", "all.sh")],
            capture_output=True,
            text=True,
            env=full,
            cwd=tree,
            timeout=60,
        )
        return result.stderr

    def test_a_linked_worktree_without_an_environment_uses_the_main_working_trees(self):
        self.interpreter(os.path.join(self.main, ".venv", "bin", "python"), "main venv")
        self.assertIn("ran: main venv", self.run_in(self.linked))

    def test_unchanged_behaviour_a_tree_with_its_own_environment_uses_its_own(self):
        self.interpreter(os.path.join(self.main, ".venv", "bin", "python"), "main venv")
        self.interpreter(os.path.join(self.linked, ".venv", "bin", "python"), "own venv")
        self.assertIn("ran: own venv", self.run_in(self.linked))

    def test_unchanged_behaviour_an_explicit_python_wins_over_any_environment(self):
        self.interpreter(os.path.join(self.main, ".venv", "bin", "python"), "main venv")
        explicit = os.path.join(self.root, "explicit", "python")
        self.interpreter(explicit, "explicit")
        self.assertIn("ran: explicit", self.run_in(self.linked, PYTHON=explicit))

    def test_a_lookup_file_that_is_missing_empty_or_a_folder_could_not_run_exit_2(self):
        lookup = os.path.join(self.linked, "checks", "interpreter.sh")
        bin_dir = os.path.join(self.root, "bin")
        self.interpreter(os.path.join(bin_dir, "python3"), "python3")
        env = {"PATH": bin_dir + os.pathsep + os.environ["PATH"], **GIT_ENV}
        for what in ("missing", "empty", "folder"):
            with self.subTest(what=what):
                os.remove(lookup) if os.path.isfile(lookup) else shutil.rmtree(lookup, True)
                if what == "empty":
                    open(lookup, "w").close()
                elif what == "folder":
                    os.mkdir(lookup)
                result = subprocess.run(
                    [os.path.join(self.linked, "checks", "all.sh")],
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=self.linked,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(
                    result.stdout.strip(),
                    "check: could not run: checks/interpreter.sh is missing or unusable; "
                    "set PYTHON or restore the file",
                )

    def test_a_path_with_a_backslash_is_kept_whole(self):
        odd = os.path.join(self.root, "back\\tslash")
        shutil.copytree(self.main, odd, ignore=shutil.ignore_patterns(".git"))
        self.interpreter(os.path.join(odd, ".venv", "bin", "python"), "odd venv")
        self.assertIn("ran: odd venv", self.run_in(odd))

    def test_unchanged_behaviour_with_no_environment_anywhere_it_uses_python3(self):
        self.assertIn("ran: python3", self.run_in(self.linked))


if __name__ == "__main__":
    unittest.main()
