"""Rules about the package's imports and built-ins, read from the source with `ast`.

Where a module sits is its classification. Nothing is registered anywhere:

- `shuttle/core/` (sub-folders included) decides and touches nothing. A module there may
  import only other modules under `shuttle/core/` and the short allow-list of standard
  library modules below, and may not mention the built-ins that reach the world.
- `shuttle/shell/` (sub-folders included) reaches the world and may import the core.
- At the package root only `__init__.py` (the version string; judged as core) and
  `__main__.py` (hands to the shell; judged as shell) may sit. A module anywhere else
  fails with the file's name and what to do.
- No module imports a third-party package.

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


ROOT_CORE = "shuttle"  # __init__.py: the version string, judged as core
ROOT_SHELL = "shuttle.__main__"  # hands straight to the shell's command line, judged as shell
CORE_PREFIX = "shuttle.core"
SHELL_PREFIX = "shuttle.shell"


def _under(name, folder):
    return name == folder or name.startswith(folder + ".")


def classify(module_name):
    """ "core", "shell", or None when the module sits where neither rule covers it."""
    if module_name == ROOT_CORE or _under(module_name, CORE_PREFIX):
        return "core"
    if module_name == ROOT_SHELL or _under(module_name, SHELL_PREFIX):
        return "shell"
    return None


def file_of(module_name, packages):
    path = module_name.replace(".", "/")
    return f"{path}/__init__.py" if module_name in packages else f"{path}.py"


def _targets(node, module_name, packages):
    """The modules an import statement reaches, as dotted names; relative forms resolved."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        base = module_name.split(".")
        # A package's __init__ is named by the package; any other module sits one level below.
        package = base if module_name in packages else base[:-1]
        package = package[: len(package) - (node.level - 1)]
        prefix = ".".join(package + ([node.module] if node.module else []))
    else:
        prefix = node.module or ""
    # "from shuttle import shell" reaches shuttle.shell; "from shuttle import __version__"
    # reaches only the package itself.
    return [
        prefix if name.startswith("__") or name == "*" else f"{prefix}.{name}"
        for name in (alias.name for alias in node.names)
    ]


def check_module(source, module_name, packages=frozenset({"shuttle"})):
    """Problems with one module's source, judged by where the module sits.

    module_name: dotted name, e.g. "shuttle.core.decisions"; the package itself is "shuttle".
    packages: the dotted names of modules that are packages (their __init__.py).
    """
    classification = classify(module_name)
    if classification is None:
        return [
            f"{file_of(module_name, packages)} sits outside the two folders: move it into "
            "shuttle/core/ (it decides, touching nothing) or shuttle/shell/ (it reaches the "
            "world). Only __init__.py and __main__.py may sit at the package root"
        ]
    problems = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for target in _targets(node, module_name, packages):
                problems += _import_problems(target, classification)
        elif classification == "core" and isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(
                f"the core mentions {node.id}, which reaches the world: "
                "move that code to the shell and pass the value in"
            )
    return sorted(set(problems))


def _import_problems(target, classification):
    top = target.split(".")[0]
    if top == "shuttle":
        if target == "shuttle" or _under(target, CORE_PREFIX):
            return []
        if _under(target, SHELL_PREFIX):
            if classification == "core":
                return [
                    f"the core imports {target}, a shell module: "
                    "move the code that needs it into the shell and pass the value in"
                ]
            return []
        return [
            f"imports {target}, which is in neither shuttle/core/ nor shuttle/shell/: "
            "import from one of the two folders"
        ]
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
    """The dotted name of a file under shuttle/, e.g. core/m.py is shuttle.core.m."""
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


def check_package(files):
    """Problems across a whole package: files is what package_files returns."""
    packages = frozenset(name for name, _, is_package in files if is_package)
    problems = []
    for name, source, _ in files:
        problems += [f"{name}: {p}" for p in check_module(source, name, packages)]
    return problems


# ----------------------------------------------------------------- the checking logic

PACKAGES = frozenset({"shuttle", "shuttle.core", "shuttle.core.drivers", "shuttle.shell"})
CORE = "shuttle.core.decisions"
SHELL = "shuttle.shell.run"


def problems_of(source, name=CORE, packages=PACKAGES):
    return check_module(source, name, packages=packages)


class TestClassification(unittest.TestCase):
    def test_the_two_folders_and_the_two_entry_files_are_classified(self):
        self.assertEqual(classify("shuttle.core.decisions"), "core")
        self.assertEqual(classify("shuttle.core.drivers.command"), "core")
        self.assertEqual(classify("shuttle.core"), "core")
        self.assertEqual(classify("shuttle"), "core")
        self.assertEqual(classify("shuttle.shell.run"), "shell")
        self.assertEqual(classify("shuttle.shell.deep.er.thing"), "shell")
        self.assertEqual(classify("shuttle.__main__"), "shell")

    def test_a_new_file_in_each_folder_is_covered_with_nothing_to_register(self):
        self.assertEqual(problems_of("import math", "shuttle.core.brand_new"), [])
        self.assertTrue(problems_of("import os", "shuttle.core.brand_new"))
        self.assertEqual(problems_of("import os", "shuttle.shell.brand_new"), [])
        self.assertTrue(problems_of("import yaml", "shuttle.shell.brand_new"))

    def test_a_new_sub_folder_in_each_folder_is_covered_with_nothing_to_register(self):
        self.assertTrue(problems_of("import os", "shuttle.core.drivers.nested.thing"))
        self.assertTrue(problems_of("print(1)", "shuttle.core.fresh.thing"))
        self.assertEqual(problems_of("import math", "shuttle.core.fresh.thing"), [])
        self.assertTrue(problems_of("from shuttle.shell import run", "shuttle.core.fresh.thing"))
        self.assertEqual(problems_of("import os\nprint(1)", "shuttle.shell.fresh.thing"), [])
        self.assertTrue(problems_of("import yaml", "shuttle.shell.fresh.thing"))

    def test_a_stray_module_at_the_package_root_is_refused_naming_the_file_and_the_fix(self):
        (problem,) = problems_of("x = 1", "shuttle.stray")
        self.assertIn("shuttle/stray.py sits outside the two folders", problem)
        self.assertIn("move it into shuttle/core/", problem)
        self.assertIn("shuttle/shell/", problem)

    def test_a_module_in_a_third_folder_is_refused_naming_the_file_and_the_fix(self):
        (problem,) = problems_of("import yaml", "shuttle.extra.thing")
        self.assertIn("shuttle/extra/thing.py sits outside the two folders", problem)
        (problem,) = problems_of("", "shuttle.extra", packages=frozenset({"shuttle.extra"}))
        self.assertIn("shuttle/extra/__init__.py sits outside the two folders", problem)

    def test_a_folder_whose_name_only_starts_like_a_classified_one_is_not_classified(self):
        self.assertIsNone(classify("shuttle.core_extras.thing"))
        self.assertIsNone(classify("shuttle.shellac"))

    def test_the_named_entry_files_at_the_root_are_fine(self):
        self.assertEqual(problems_of('__version__ = "1"', "shuttle"), [])
        main = "from shuttle.shell import cli\ncli.entry()"
        self.assertEqual(problems_of(main, "shuttle.__main__"), [])

    def test_the_package_init_is_judged_as_core(self):
        self.assertTrue(problems_of("import os", "shuttle"))


class TestTheCoreImportsOnlyTheCoreAndAnAllowList(unittest.TestCase):
    def test_core_importing_a_shell_module_in_any_form_is_refused(self):
        for source in (
            "from shuttle import shell",
            "import shuttle.shell.run",
            "from shuttle.shell import run",
            "from shuttle.shell.run import end_child",
            "from .. import shell",
            "from ..shell import run",
            "from ..shell.run import end_child",
            "def f():\n    from shuttle.shell import records\n    return records",
            "def f():\n    from ..shell import cli\n    return cli",
        ):
            with self.subTest(source=source):
                problems = problems_of(source)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("the core imports shuttle.shell", problems[0])
                self.assertIn("a shell module", problems[0])

    def test_core_importing_a_module_outside_both_folders_is_refused(self):
        for source in ("from shuttle import run", "import shuttle.stray"):
            with self.subTest(source=source):
                (problem,) = problems_of(source)
                self.assertIn("neither shuttle/core/ nor shuttle/shell/", problem)

    def test_core_importing_another_core_module_is_fine(self):
        for source in (
            "from shuttle.core import fixed",
            "from shuttle.core.fixed import NONE",
            "from . import fixed",
            "from .fixed import NONE",
            "import shuttle.core.fixed",
            "from shuttle import __version__",
        ):
            with self.subTest(source=source):
                self.assertEqual(problems_of(source), [])

    def test_a_relative_import_from_a_sub_folder_resolves_to_its_real_module(self):
        drivers = "shuttle.core.drivers.command"
        self.assertEqual(problems_of("from .. import fixed", drivers), [])
        self.assertEqual(problems_of("from ..shapes import StepResult", drivers), [])
        self.assertEqual(problems_of("from . import sibling", drivers), [])
        self.assertTrue(problems_of("from ... import shell", drivers))
        self.assertTrue(problems_of("from ...shell import run", drivers))

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
        self.assertEqual(problems_of("import os, subprocess, codecs", SHELL), [])
        self.assertEqual(problems_of("from shuttle.core import decisions", SHELL), [])
        self.assertEqual(problems_of("from shuttle.shell import records", SHELL), [])


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
        self.assertEqual(problems_of("print(open('f').read())", SHELL), [])


class TestStandardLibraryOnly(unittest.TestCase):
    def test_a_third_party_import_is_refused_in_the_core_the_shell_and_sub_folders(self):
        for name in (CORE, SHELL, "shuttle.core.drivers.command", "shuttle.shell.deep.thing"):
            for source in ("import requests", "from yaml import safe_load", "import numpy.linalg"):
                with self.subTest(name=name, source=source):
                    problems = problems_of(source, name)
                    self.assertTrue(
                        any("third-party" in p and "standard library only" in p for p in problems),
                        problems,
                    )

    def test_a_third_party_import_inside_a_function_is_refused(self):
        self.assertTrue(problems_of("def f():\n    import yaml", SHELL))

    def test_the_standard_library_and_the_package_itself_are_fine(self):
        self.assertEqual(problems_of("import json\nfrom shuttle.core import fixed", SHELL), [])

    def test_an_import_of_a_package_module_in_neither_folder_is_refused(self):
        problems = problems_of("from shuttle.ghost import x", SHELL)
        self.assertIn("neither shuttle/core/ nor shuttle/shell/", problems[0])


class TestThePackageWalk(unittest.TestCase):
    def test_a_stray_module_and_a_third_folder_fail_the_walk(self):
        files = [
            (CORE, "x = 1", False),
            ("shuttle.stray", "x = 1", False),
            ("shuttle.extra.thing", "import yaml", False),
        ]
        problems = check_package(files)
        self.assertTrue(any(p.startswith("shuttle.stray: shuttle/stray.py sits") for p in problems))
        self.assertTrue(any("shuttle/extra/thing.py sits outside" in p for p in problems))
        self.assertEqual(len(problems), 2)

    def test_a_new_file_and_a_new_sub_folder_fail_the_walk_when_they_break_a_rule(self):
        files = [
            ("shuttle.core.new_file", "import os", False),
            ("shuttle.core.fresh.thing", "import os", False),
            ("shuttle.shell.fresh.thing", "import os", False),
        ]
        problems = check_package(files)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("the core imports os" in p for p in problems))

    def test_the_names_of_files_in_sub_folders(self):
        self.assertEqual(module_name_of("decisions.py"), "shuttle.decisions")
        self.assertEqual(module_name_of("__init__.py"), "shuttle")
        self.assertEqual(module_name_of(os.path.join("core", "m.py")), "shuttle.core.m")
        self.assertEqual(module_name_of(os.path.join("core", "__init__.py")), "shuttle.core")


# ------------------------------------------------------------------ the real package


class TestThePackageItself(unittest.TestCase):
    def test_the_whole_package_tree_obeys_the_rules(self):
        files = package_files()
        self.assertGreater(len(files), 8)
        self.assertEqual(check_package(files), [])

    def test_the_walk_sees_every_python_file_under_the_package(self):
        counted = sum(
            name.endswith(".py")
            for folder, _, files in os.walk(PACKAGE)
            if "__pycache__" not in folder
            for name in files
        )
        self.assertEqual(len(package_files()), counted)


class TestTheLinterAgreesWithTheFolders(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            config = tomllib.load(f)["tool"]
        self.lint = config["ruff"]["lint"]
        self.assertNotIn("shuttle", config, "the folders are the classification: no table")

    def test_the_one_ban_list_bans_the_shell_folder_and_nothing_else_of_the_package(self):
        banned = set(self.lint["flake8-tidy-imports"]["banned-api"])
        self.assertEqual({m for m in banned if m.split(".")[0] == "shuttle"}, {"shuttle.shell"})

    def test_ban_messages_name_the_shell_folder(self):
        banned = self.lint["flake8-tidy-imports"]["banned-api"]
        for name, entry in banned.items():
            with self.subTest(name=name):
                self.assertIn("shuttle/shell/", entry["msg"])
                self.assertNotIn("per-file-ignores", entry["msg"])

    def test_only_the_shell_folder_the_entry_file_and_the_tests_are_exempt_from_the_ban(self):
        exempt = {
            path for path, rules in self.lint["per-file-ignores"].items() if "TID251" in rules
        }
        self.assertEqual(exempt, {"shuttle/shell/**", "shuttle/__main__.py", "tests/**"})

    def test_relative_imports_are_banned_so_the_ban_cannot_be_walked_around(self):
        self.assertEqual(self.lint["flake8-tidy-imports"]["ban-relative-imports"], "all")

    def test_every_standard_library_module_the_linter_bans_is_off_the_core_allow_list(self):
        banned = {m for m in self.lint["flake8-tidy-imports"]["banned-api"] if "." not in m}
        self.assertEqual(banned & CORE_STDLIB_ALLOWED, set())


if __name__ == "__main__":
    unittest.main()
