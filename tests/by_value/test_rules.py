"""Rules about the package's imports and built-ins, read from the source with `ast`.

Every module in `shuttle/` (sub-folders included) is classified as core or shell in
pyproject.toml, under [tool.shuttle.modules]. The classification is the rule:

- The core touches nothing. A core module may import only other core modules and the
  short allow-list of standard library modules below, and may not mention the built-ins
  that reach the world.
- The package uses the standard library only: no module, core or shell, imports a third-party
  package.

`check_module` is the checking logic: source text and a module's name in, a list of
problems out. The file walking is a thin layer over it. These tests read source text; they
start no process and write nothing.
"""

import ast
import os
import sys
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE = os.path.join(ROOT, "shuttle")

# Standard library modules a core module may import: each touches nothing. A module not on
# this list is refused in the core, so a module nobody thought of (codecs, zipfile, fcntl)
# fails closed.
CORE_STDLIB_ALLOWED = frozenset(
    {
        "__future__",  # compiler directives only
        "collections",  # containers (collections.abc: Mapping, Sequence, ...)
        "dataclasses",  # plain records
        "enum",  # plain enumerations
        "functools",  # pure helpers over functions
        "itertools",  # pure iteration helpers
        "json",  # dumps and loads over values; files are the shell's (nothing here opens one)
        "math",  # arithmetic
        "re",  # pattern matching over text
        "typing",  # annotations
    }
)

# Built-ins that reach the world, or reach it by import. A core module may not mention
# them at all: called, assigned (f = open) or passed.
FORBIDDEN_NAMES = frozenset(
    {
        "open",
        "print",
        "input",
        "exec",
        "eval",
        "compile",
        "__import__",
        "breakpoint",
        "builtins",
        "__builtins__",
    }
)


def load_table():
    """The classification: {"core": set of module names, "shell": set of module names}."""
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        modules = tomllib.load(f)["tool"]["shuttle"]["modules"]
    return {"core": set(modules["core"]), "shell": set(modules["shell"])}


def _targets(node, module_name, known):
    """The modules an import statement reaches, as dotted names; relative forms resolved."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        base = module_name.split(".")
        # A package's __init__ is named by the package; any other module sits one level below.
        package = base if module_name in known["packages"] else base[:-1]
        package = package[: len(package) - (node.level - 1)]
        prefix = ".".join(package + ([node.module] if node.module else []))
    else:
        prefix = node.module or ""
    names = [alias.name for alias in node.names]
    # "from shuttle import run" reaches shuttle.run when that is a module of the package.
    return [
        f"{prefix}.{name}" if f"{prefix}.{name}" in known["modules"] else prefix for name in names
    ]


def check_module(source, module_name, table, packages=frozenset({"shuttle"})):
    """Problems with one module's source, judged by its classification in the table.

    module_name: dotted name, e.g. "shuttle.core"; the package itself is "shuttle".
    packages: the dotted names of modules that are packages (their __init__.py).
    """
    core, shell = table["core"], table["shell"]
    known = {"modules": core | shell, "core_modules": core, "packages": packages}
    if module_name in core:
        classification = "core"
    elif module_name in shell:
        classification = "shell"
    else:
        return [
            f"{module_name} is not classified: add it to core or shell "
            "in pyproject.toml, under [tool.shuttle.modules]"
        ]
    problems = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for target in _targets(node, module_name, known):
                problems += _import_problems(target, classification, known)
        elif classification == "core" and isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(
                f"the core mentions {node.id}, which reaches the world: "
                "move that code to the shell and pass the value in"
            )
    return sorted(set(problems))


def _import_problems(target, classification, known):
    top = target.split(".")[0]
    if top == "shuttle":
        if target not in known["modules"] and target != "shuttle":
            return [
                f"imports {target}, which is not a classified module: "
                "add it to core or shell in pyproject.toml"
            ]
        if classification == "core" and target not in known["core_modules"]:
            return [
                f"the core imports {target}, a shell module: "
                "move the code that needs it into the shell and pass the value in"
            ]
        return []
    if top not in sys.stdlib_module_names:
        return [f"imports {top}, a third-party package: the package uses the standard library only"]
    if classification == "core" and top not in CORE_STDLIB_ALLOWED:
        return [
            f"the core imports {top}, which is not on the allow-list of standard library "
            "modules that touch nothing: move that code to the shell, or justify the module "
            "in CORE_STDLIB_ALLOWED"
        ]
    return []


def module_name_of(relative_path):
    """The dotted name of a file under shuttle/, e.g. sub/m.py is shuttle.sub.m."""
    parts = relative_path[: -len(".py")].split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["shuttle", *parts])


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def package_files():
    """(dotted name, source, is a package) for every module under shuttle/, recursively."""
    paths = [
        os.path.join(folder, name)
        for folder, dirs, files in os.walk(PACKAGE)
        if "__pycache__" not in folder
        for name in sorted(files)
        if name.endswith(".py")
    ]
    return [
        (
            module_name_of(os.path.relpath(path, PACKAGE)),
            _read(path),
            os.path.basename(path) == "__init__.py",
        )
        for path in sorted(paths)
    ]


def check_package(files, table):
    """Problems across a whole package: files is what package_files returns."""
    packages = frozenset(name for name, _, is_package in files if is_package)
    classified = table["core"] | table["shell"]
    problems = []
    for name, source, _ in files:
        problems += [f"{name}: {p}" for p in check_module(source, name, table, packages)]
    for name in sorted(classified - {name for name, _, _ in files}):
        problems.append(f"{name}: is classified in pyproject.toml but has no file")
    return problems


# ----------------------------------------------------------------- the checking logic

TABLE = {
    "core": {"shuttle", "shuttle.core", "shuttle.fixed", "shuttle.sub.pure"},
    "shell": {"shuttle.run", "shuttle.cli", "shuttle.records", "shuttle.sub.reach"},
}


def problems_of(source, name="shuttle.core"):
    return check_module(source, name, TABLE, packages=frozenset({"shuttle", "shuttle.sub"}))


class TestClassification(unittest.TestCase):
    def test_a_module_that_is_in_neither_list_is_refused_with_what_to_do(self):
        (problem,) = problems_of("x = 1", "shuttle.new_thing")
        self.assertIn("shuttle.new_thing is not classified", problem)
        self.assertIn("add it to core or shell", problem)

    def test_a_module_in_a_new_sub_folder_is_refused_until_classified(self):
        self.assertEqual(len(problems_of("import yaml", "shuttle.extra.thing")), 1)
        self.assertIn("not classified", problems_of("import yaml", "shuttle.extra.thing")[0])

    def test_a_classified_module_in_a_sub_folder_is_judged_by_its_class(self):
        self.assertEqual(problems_of("import math", "shuttle.sub.pure"), [])
        self.assertEqual(problems_of("import os", "shuttle.sub.reach"), [])
        self.assertTrue(problems_of("import os", "shuttle.sub.pure"))


class TestTheCoreImportsOnlyTheCoreAndAnAllowList(unittest.TestCase):
    def test_core_importing_a_shell_module_in_any_form_is_refused(self):
        for source in (
            "from shuttle import run",
            "import shuttle.run",
            "from shuttle.run import end_child",
            "from . import run",
            "from .run import end_child",
            "def f():\n    from shuttle import records\n    return records",
            "def f():\n    from . import cli\n    return cli",
        ):
            with self.subTest(source=source):
                problems = problems_of(source)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("the core imports shuttle.", problems[0])
                self.assertIn("a shell module", problems[0])

    def test_core_importing_another_core_module_is_fine(self):
        for source in (
            "from shuttle import fixed",
            "from shuttle.fixed import NONE",
            "from . import fixed",
            "import shuttle.fixed",
            "from shuttle import __version__",
        ):
            with self.subTest(source=source):
                self.assertEqual(problems_of(source), [])

    def test_a_relative_import_from_a_sub_folder_resolves_to_its_real_module(self):
        self.assertEqual(problems_of("from . import pure", "shuttle.sub.reach"), [])
        self.assertEqual(problems_of("from .. import fixed", "shuttle.sub.pure"), [])
        self.assertTrue(problems_of("from .. import run", "shuttle.sub.pure"))

    def test_core_importing_a_standard_library_module_off_the_allow_list_is_refused(self):
        for name in ("codecs", "zipfile", "tarfile", "fcntl", "gzip", "os", "sys", "builtins"):
            with self.subTest(name=name):
                problems = problems_of(f"import {name}")
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(f"the core imports {name}", problems[0])
                self.assertIn("allow-list", problems[0])

    def test_core_importing_an_allowed_standard_library_module_is_fine(self):
        for name in sorted(CORE_STDLIB_ALLOWED):
            with self.subTest(name=name):
                self.assertEqual(problems_of(f"import {name}"), [])
        self.assertEqual(problems_of("from collections.abc import Mapping"), [])
        self.assertEqual(problems_of("from typing import Any"), [])

    def test_the_shell_may_import_any_standard_library_module_and_the_core(self):
        self.assertEqual(problems_of("import os, subprocess, codecs", "shuttle.run"), [])
        self.assertEqual(problems_of("from shuttle import core, records", "shuttle.run"), [])


class TestTheCoreMentionsNoBuiltinThatReachesTheWorld(unittest.TestCase):
    def test_every_form_of_mentioning_one_is_refused(self):
        for source in (
            "x = open('f')",
            "print('x')",
            "f = open\nf('x')",
            "g = print",
            "run(open)",
            "input()",
            "exec('1')",
            "eval('1')",
            "compile('1', 'f', 'eval')",
            "__import__('os')",
            "breakpoint()",
            "x = builtins",
            "f = __builtins__",
            "def f(open=1):\n    return open",
        ):
            with self.subTest(source=source):
                problems = problems_of(source)
                self.assertTrue(problems, source)
                self.assertIn("the core mentions", problems[0])
                self.assertIn("move that code to the shell", problems[0])

    def test_builtins_open_is_refused_by_the_import_and_by_the_name(self):
        problems = problems_of("import builtins\nbuiltins.open('f')")
        self.assertTrue(any("the core imports builtins" in p for p in problems))
        self.assertTrue(any("the core mentions builtins" in p for p in problems))

    def test_a_name_that_only_looks_similar_is_fine(self):
        self.assertEqual(problems_of("opened = 1\nprinter = 2\nx = {'open': 1}['open']"), [])
        self.assertEqual(problems_of("def f(record):\n    return record.open"), [])

    def test_the_shell_may_use_them(self):
        self.assertEqual(problems_of("print(open('f').read())", "shuttle.run"), [])


class TestStandardLibraryOnly(unittest.TestCase):
    def test_a_third_party_import_is_refused_in_the_core_the_shell_and_sub_folders(self):
        for name in ("shuttle.core", "shuttle.run", "shuttle.sub.pure", "shuttle.sub.reach"):
            for source in ("import requests", "from yaml import safe_load", "import numpy.linalg"):
                with self.subTest(name=name, source=source):
                    problems = problems_of(source, name)
                    self.assertTrue(
                        any("third-party" in p and "standard library only" in p for p in problems),
                        problems,
                    )

    def test_a_third_party_import_inside_a_function_is_refused(self):
        self.assertTrue(problems_of("def f():\n    import yaml", "shuttle.run"))

    def test_the_standard_library_and_the_package_itself_are_fine(self):
        self.assertEqual(problems_of("import json\nfrom shuttle import fixed", "shuttle.run"), [])

    def test_an_import_of_a_package_module_nobody_classified_is_refused(self):
        problems = problems_of("from shuttle.ghost import x", "shuttle.run")
        self.assertIn("not a classified module", problems[0])


class TestThePackageWalk(unittest.TestCase):
    def test_a_module_in_a_new_sub_folder_fails_the_walk_until_it_is_classified(self):
        files = [("shuttle.core", "x = 1", False), ("shuttle.extra.thing", "import yaml", False)]
        problems = check_package(files, {"core": {"shuttle.core"}, "shell": set()})
        self.assertTrue(
            any("shuttle.extra.thing: shuttle.extra.thing is not classified" in p for p in problems)
        )

    def test_a_classified_name_with_no_file_fails_the_walk(self):
        problems = check_package([], {"core": {"shuttle.gone"}, "shell": set()})
        self.assertEqual(
            problems, ["shuttle.gone: is classified in pyproject.toml but has no file"]
        )

    def test_the_names_of_files_in_sub_folders(self):
        self.assertEqual(module_name_of("core.py"), "shuttle.core")
        self.assertEqual(module_name_of("__init__.py"), "shuttle")
        self.assertEqual(module_name_of(os.path.join("sub", "m.py")), "shuttle.sub.m")
        self.assertEqual(module_name_of(os.path.join("sub", "__init__.py")), "shuttle.sub")


# ------------------------------------------------------------------ the real package


class TestThePackageItself(unittest.TestCase):
    def test_the_whole_package_tree_obeys_the_rules(self):
        files = package_files()
        self.assertGreater(len(files), 8)
        self.assertEqual(check_package(files, load_table()), [])

    def test_the_walk_sees_every_python_file_under_the_package(self):
        counted = sum(
            name.endswith(".py")
            for folder, _, files in os.walk(PACKAGE)
            if "__pycache__" not in folder
            for name in files
        )
        self.assertEqual(len(package_files()), counted)


class TestTheLinterReadsTheSameTable(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            self.lint = tomllib.load(f)["tool"]["ruff"]["lint"]
        self.table = load_table()

    def test_every_shell_module_is_banned_in_the_core_by_the_linter(self):
        banned = set(self.lint["flake8-tidy-imports"]["banned-api"])
        self.assertLessEqual(self.table["shell"], banned)

    def test_only_the_shell_is_exempt_from_the_ban(self):
        exempt = {
            path.removesuffix(".py").replace("/", ".")
            for path, rules in self.lint["per-file-ignores"].items()
            if path.startswith("shuttle/") and "TID251" in rules
        }
        self.assertEqual(exempt, self.table["shell"])

    def test_relative_imports_are_banned_so_the_ban_cannot_be_walked_around(self):
        self.assertEqual(self.lint["flake8-tidy-imports"]["ban-relative-imports"], "all")

    def test_every_standard_library_module_the_linter_bans_is_off_the_core_allow_list(self):
        banned = {m for m in self.lint["flake8-tidy-imports"]["banned-api"] if "." not in m}
        self.assertEqual(banned & CORE_STDLIB_ALLOWED, set())


if __name__ == "__main__":
    unittest.main()
