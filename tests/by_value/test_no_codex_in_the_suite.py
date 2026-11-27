"""Rule: nothing in the suite or the checks starts the program named codex.

The owner's words: "we don't want to run codex often -- it should be an isolated scenario for
one-off cases." A real Codex run is done once, by hand, on purpose. So:

- a test file that can start a real process (it imports subprocess, the os functions that exec,
  spawn or fork, the real operations, or the real-run harness) holds no string that names the
  program: a string that is, or ends a path with, the word followed by nothing or a space;
- no file under checks/ that is not Python names it at all, as a word.

A by-value test never starts a process (it is given the simulated world), so it may hold the word as
data: the driver's launch command is a list of text it compares. These rules read source text
only; they start nothing.
"""

import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROGRAM = "co" + "dex"  # written in two parts so this file never holds the word whole
NAMES_IT = re.compile(rf"(^|/){PROGRAM}(\s|$)")
WORD = re.compile(rf"\b{PROGRAM}\b", re.IGNORECASE)
REACHES_THE_WORLD = {"subprocess", "multiprocessing", "pty", "shuttle.world", "real_run"}
EXEC_NAMES = {"system", "popen", "execv", "execve", "execvp", "execvpe", "execl", "execlp"}
EXEC_NAMES |= {"execle", "execlpe", "spawnv", "spawnve", "spawnvp", "spawnl", "posix_spawn"}
EXEC_NAMES |= {"fork", "forkpty"}


def can_start_a_process(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or "", *(f"{node.module}.{a.name}" for a in node.names)]
        elif isinstance(node, ast.Call):
            # importlib.import_module("rehearsal.real_run") and the like
            modules = [a.value for a in node.args if isinstance(a, ast.Constant)]
            modules = [m for m in modules if isinstance(m, str)]
        elif isinstance(node, ast.Attribute) and node.attr in EXEC_NAMES:
            return True
        else:
            continue
        if any(
            m.split(".")[0] in REACHES_THE_WORLD
            or m in REACHES_THE_WORLD
            or m.endswith(".real_run")
            or m.startswith("shuttle.world")
            or m.endswith("real_run")
            for m in modules
        ):
            return True
    return False


def strings_naming_the_program(source):
    tree = ast.parse(source)
    if not can_start_a_process(tree):
        return []
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and NAMES_IT.search(node.value)
    ]


def files_under(folder):
    """(shown name, text) of each source file under a folder of the repository."""
    for where, folders, names in os.walk(os.path.join(ROOT, folder)):
        folders[:] = [f for f in folders if f != "__pycache__"]  # compiled files are not source
        for name in sorted(names):
            path = os.path.join(where, name)
            with open(path, encoding="utf-8", errors="replace") as f:
                yield os.path.relpath(path, ROOT), f.read()


def problems(folder, relative):
    found = []
    for shown, text in files_under(folder):
        python = shown.endswith(".py")
        if python and relative == "py" and strings_naming_the_program(text):
            found.append(f"{shown} can start a process and names the program {PROGRAM}")
        elif relative == "other" and not python and WORD.search(text):
            found.append(f"{shown} names the program {PROGRAM}")
    return found


class TheSuiteNeverStartsTheTool(unittest.TestCase):
    def test_no_test_file_that_can_start_a_process_names_the_program(self):
        self.assertEqual(problems("tests", "py"), [])

    def test_no_check_script_that_can_start_a_process_names_the_program(self):
        self.assertEqual(problems("checks", "py"), [])

    def test_no_file_under_checks_that_is_not_python_names_the_program(self):
        self.assertEqual(problems("checks", "other"), [])

    def test_the_rule_sees_the_ways_a_file_names_and_starts_it(self):
        starts = "import subprocess\n"
        for label, line in {
            "a list": f'subprocess.run(["{PROGRAM}", "exec"])',
            "a path": f'subprocess.run(["/usr/bin/{PROGRAM}"])',
            "a string with arguments": f'subprocess.run("{PROGRAM} exec -", shell=True)',
            "a document naming the executor": f'doc = {{"executor": {{"command": "{PROGRAM}"}}}}',
        }.items():
            with self.subTest(label):
                self.assertTrue(strings_naming_the_program(starts + line + "\n"))

    def test_the_rule_sees_each_way_a_file_can_start_a_process(self):
        line = f'x = "{PROGRAM}"\n'
        for label, head in {
            "subprocess": "import subprocess\n",
            "from subprocess": "from subprocess import run\n",
            "os.system": "import os\nos.system('')\n",
            "os.execvp": "import os\nos.execvp('', [])\n",
            "the real operations": "from shuttle.world import real\n",
            "the real-run harness": "import rehearsal.real_run as real_run\n",
            "the harness by name": 'import importlib\nx = importlib.import_module("rehearsal.real_run")\n',
        }.items():
            with self.subTest(label):
                self.assertTrue(strings_naming_the_program(head + line), label)

    def test_the_rule_lets_a_by_value_file_hold_the_word_as_data_and_other_words_pass(self):
        self.assertEqual(strings_naming_the_program(f'launch = ["{PROGRAM}", "exec"]\n'), [])
        self.assertEqual(
            strings_naming_the_program(f'import subprocess\nx = "{PROGRAM}-notes"\n'), []
        )
        self.assertEqual(
            strings_naming_the_program(f'import subprocess\nx = "~/.{PROGRAM}/a"\n'), []
        )


if __name__ == "__main__":
    unittest.main()
