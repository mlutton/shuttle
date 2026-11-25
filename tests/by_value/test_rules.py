"""Rules about the package's own imports, read from the source with `ast`.

The core touches nothing, and the package uses the standard library only.
These tests read source text; they start no process and write nothing.
"""

import ast
import os
import sys
import tomllib
import unittest

PACKAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "shuttle")

# The core: modules that decide and must touch nothing. fixed.py holds constants and
# shapes.py holds types; both are read by the core. Every other module is the shell.
CORE_MODULES = ("__init__.py", "core.py", "fixed.py", "shapes.py")


def _pyproject():
    with open(os.path.join(os.path.dirname(PACKAGE), "pyproject.toml"), "rb") as f:
        return tomllib.load(f)["tool"]["ruff"]["lint"]


# Standard library modules that reach files, processes, the clock, signals, the network or
# the environment. The one list is the linter's banned-api table in pyproject.toml; the
# linter bans them across the package, and this test checks the core by the same list.
REACHING_MODULES = frozenset(_pyproject()["flake8-tidy-imports"]["banned-api"])

# The shell, exempted from the ban by name in pyproject.toml.
SHELL_EXEMPTIONS = frozenset(
    name.removeprefix("shuttle/")
    for name, rules in _pyproject()["per-file-ignores"].items()
    if name.startswith("shuttle/") and "TID251" in rules
)

# Names that reach the world without an import.
REACHING_CALLS = frozenset({"open", "__import__", "exec", "eval", "input", "print"})


def imported_modules(source):
    """The top-level module name of each absolute import in the source."""
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module.split(".")[0])
    return names


def reaching_problems(source):
    """What in this source reaches files, processes, the clock, signals, the network or the environment."""
    problems = [f"imports {name}" for name in imported_modules(source) if name in REACHING_MODULES]
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in REACHING_CALLS
        ):
            problems.append(f"calls {node.func.id}")
    return problems


def third_party_problems(source):
    """Imports that are neither the standard library nor the package itself."""
    return [
        f"imports {name}"
        for name in imported_modules(source)
        if name not in sys.stdlib_module_names and name != "shuttle"
    ]


def package_sources():
    for name in sorted(os.listdir(PACKAGE)):
        if name.endswith(".py"):
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
                yield name, f.read()


class TestTheCoreTouchesNothing(unittest.TestCase):
    def test_no_core_module_reaches_the_world(self):
        for name in CORE_MODULES:
            with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
                self.assertEqual(reaching_problems(f.read()), [], name)

    def test_the_checker_sees_a_module_that_reaches(self):
        for source, expected in (
            ("import os", ["imports os"]),
            ("import signal as s", ["imports signal"]),
            ("from time import monotonic", ["imports time"]),
            ("from os.path import join", ["imports os"]),
            ("import json\nx = open('f')", ["calls open"]),
            ("import json, math", []),
            ("from shuttle import fixed", []),
        ):
            self.assertEqual(reaching_problems(source), expected, source)

    def test_the_linter_ban_and_this_test_agree_on_which_modules_are_the_shell(self):
        modules = {name for name, _ in package_sources()}
        self.assertEqual(SHELL_EXEMPTIONS, modules - set(CORE_MODULES))

    def test_the_ban_list_names_the_modules_that_reach_the_world(self):
        for name in ("os", "sys", "subprocess", "time", "datetime", "signal", "socket", "pathlib"):
            self.assertIn(name, REACHING_MODULES)

    def test_every_core_module_exists(self):
        for name in CORE_MODULES:
            self.assertTrue(os.path.exists(os.path.join(PACKAGE, name)), name)


class TestStandardLibraryOnly(unittest.TestCase):
    def test_no_module_imports_a_third_party_package(self):
        seen = list(package_sources())
        self.assertGreater(len(seen), 5)
        for name, source in seen:
            self.assertEqual(third_party_problems(source), [], name)

    def test_the_checker_sees_a_third_party_import(self):
        self.assertEqual(third_party_problems("import requests"), ["imports requests"])
        self.assertEqual(third_party_problems("from yaml import safe_load"), ["imports yaml"])
        self.assertEqual(third_party_problems("import json\nfrom shuttle import core"), [])


if __name__ == "__main__":
    unittest.main()
