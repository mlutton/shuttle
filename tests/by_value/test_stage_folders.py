"""Every folder of tests is run by exactly one stage of the check script.

`folder_problems` is the decision: the script's text and the folders of `tests/` in, what is
wrong out. The walk over the real script and folder is a thin layer over it.
"""

import fnmatch
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGES = ("tests", "real")


def stage_folders(script: str) -> dict[str, list[str]]:
    """For each stage of `STAGES` the script calls, the folders its command discovers tests in,
    in order, a folder named twice listed twice. Comments are not read; a line ending in a
    backslash continues on the next."""
    found: dict[str, list[str]] = {}
    for line in script.replace("\\\n", " ").splitlines():
        words = line.split()
        if len(words) > 1 and words[0] == "stage" and words[1] in STAGES:
            found.setdefault(words[1], []).extend(re.findall(r"unittest discover -s (\S+)", line))
    return found


def holds_tests(names: list[str]) -> bool:
    """Whether a folder with these file names holds tests: the pattern `unittest discover` uses
    when it is not given another."""
    return any(fnmatch.fnmatch(name, "test*.py") for name in names)


def folder_problems(script: str, existing: set[str], holding: set[str]) -> list[str]:
    """What is wrong between the script and the folders: one entry per folder that holds tests
    and is named by no stage, per folder named by more than one stage or more than once, and per
    folder named that does not exist. `existing` and `holding` are `tests/<name>` paths."""
    named = [f for folders in stage_folders(script).values() for f in folders]
    result = []
    for folder in sorted(holding - set(named)):
        result.append(f"{folder} holds tests and no stage runs it")
    for folder in sorted({f for f in named if named.count(f) > 1}):
        result.append(f"{folder} is named more than once")
    for folder in sorted(set(named) - existing):
        result.append(f"{folder} is named by a stage and does not exist")
    return result


class StageFoldersTest(unittest.TestCase):
    SCRIPT = (
        "# stage tests: tests/ignored in a comment\n"
        'stage tests 20 timeout 20 "$PYTHON" -m unittest discover -s tests/a -t tests\n'
        "stage real 120 timeout 120 sh -c \\\n"
        '    \'"$0" -m unittest discover -s tests/b -t tests && "$0" -m unittest discover -s tests/c -t tests\' \\\n'
        '    "$PYTHON"\n'
        'stage lint 0 "$PYTHON" -m unittest discover -s tests/d\n'
    )

    def test_the_folders_of_each_stage_are_read_across_a_continued_line(self):
        self.assertEqual(
            stage_folders(self.SCRIPT), {"tests": ["tests/a"], "real": ["tests/b", "tests/c"]}
        )

    def test_a_script_whose_folders_match_the_ones_holding_tests_has_no_problem(self):
        both = {"tests/a", "tests/b", "tests/c"}
        self.assertEqual(folder_problems(self.SCRIPT, both | {"tests/rehearsal"}, both), [])

    def test_a_folder_holding_tests_that_no_stage_runs_is_a_problem(self):
        everything = {"tests/a", "tests/b", "tests/c", "tests/new"}
        self.assertEqual(
            folder_problems(self.SCRIPT, everything, everything),
            ["tests/new holds tests and no stage runs it"],
        )

    def test_a_folder_in_a_comment_or_another_stage_is_not_run_by_either_of_the_two(self):
        everything = {"tests/a", "tests/b", "tests/c", "tests/d", "tests/ignored"}
        self.assertEqual(
            folder_problems(self.SCRIPT, everything, everything),
            [
                "tests/d holds tests and no stage runs it",
                "tests/ignored holds tests and no stage runs it",
            ],
        )

    def test_a_folder_run_by_both_stages_or_twice_is_a_problem(self):
        script = self.SCRIPT.replace("tests/c", "tests/a")
        both = {"tests/a", "tests/b"}
        self.assertEqual(folder_problems(script, both, both), ["tests/a is named more than once"])

    def test_a_folder_the_script_names_that_is_not_there_is_a_problem(self):
        present = {"tests/a", "tests/b"}
        self.assertEqual(
            folder_problems(self.SCRIPT, present, present),
            ["tests/c is named by a stage and does not exist"],
        )


class HoldsTestsTest(unittest.TestCase):
    def test_a_name_unittest_picks_up_by_default_counts(self):
        for name in ("test_x.py", "testing.py", "test.py", "testfoo.py"):
            with self.subTest(name=name):
                self.assertTrue(holds_tests(["README.md", name]))

    def test_a_name_it_does_not_pick_up_does_not_count(self):
        for name in ("mytest.py", "test_x.txt", "test_x.pyc", "helper.py", "Test_x.py"):
            with self.subTest(name=name):
                self.assertFalse(holds_tests([name]))

    def test_a_folder_with_no_files_holds_none(self):
        self.assertFalse(holds_tests([]))


class RealScriptTest(unittest.TestCase):
    def test_every_folder_of_tests_that_holds_tests_is_run_by_exactly_one_stage(self):
        with open(os.path.join(ROOT, "checks", "all.sh")) as f:
            script = f.read()
        top = os.path.join(ROOT, "tests")
        existing = {f"tests/{n}" for n in os.listdir(top) if os.path.isdir(os.path.join(top, n))}
        holding = {
            folder for folder in existing if holds_tests(os.listdir(os.path.join(ROOT, folder)))
        }
        self.assertEqual(folder_problems(script, existing, holding), [])
