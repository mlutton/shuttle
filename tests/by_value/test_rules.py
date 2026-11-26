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
- No file under shuttle/ carries a lint ignore that covers the banned-import rule (TID251):
  without this, a file could start with `# ruff: noqa: TID251` and import what it likes,
  and the linter would pass it. See `noqa_problems` for the spellings.

`check_module` is the checking logic: source text and a module's name in, a list of
problems out. The file walking is a thin layer over it. These tests read source text; they
start no process and write nothing.
"""

import ast
import importlib
import io
import os
import re
import sys
import tempfile
import tokenize
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE = os.path.join(ROOT, "shuttle")
sys.path.insert(0, os.path.join(ROOT, "checks"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
report = importlib.import_module("report")  # find_markers: the one definition of a marker
# The reviewers' attack lists, as data (see the README, "Hostile-case tables").
IMPORTS = importlib.import_module("hostile.imports_table").IMPORTS
SUPPRESSIONS = importlib.import_module("hostile.suppressions_table").SUPPRESSIONS

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


# Classification is by the file's place, a path relative to shuttle/ with "/" separators
# ("core/decisions.py"), never by a dotted name: shuttle/core.py and shuttle/core/ share a name.
ROOT_FILES = {"__init__.py": "core", "__main__.py": "shell"}
FOLDERS = ("core", "shell")


def classify(path):
    """ "core", "shell", or None when the file sits where neither rule covers it."""
    parts = path.split("/")
    if len(parts) == 1:
        return ROOT_FILES.get(path)
    if parts[0] in FOLDERS and path.endswith(".py"):
        return parts[0]
    return None


def dotted_of(path):
    """The module a file is, for resolving its relative imports: core/m.py is shuttle.core.m."""
    parts = path[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ["shuttle", *parts]


def _resolve(prefix, name):
    """The module `from <prefix> import <name>` would actually load."""
    if name == "*" or (prefix == "shuttle" and name == "__version__"):
        return prefix
    return f"{prefix}.{name}"


def _targets(node, path):
    """The modules an import statement reaches, as dotted names; relative forms resolved."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:
        base = dotted_of(path)
        # A package's __init__ is named by the package; any other module sits one level below.
        package = base if path.endswith("__init__.py") else base[:-1]
        package = package[: len(package) - (node.level - 1)]
        prefix = ".".join(package + ([node.module] if node.module else []))
    else:
        prefix = node.module or ""
    return [_resolve(prefix, alias.name) for alias in node.names]


def _entry_problems(tree, path):
    """The root files stay thin: __main__.py hands to the shell, __init__.py holds the version."""
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # a docstring
    if path == "__main__.py":
        ok = (
            len(body) == 2
            and isinstance(body[0], ast.ImportFrom)
            and body[0].module == "shuttle.shell"
            and body[0].level == 0
            and isinstance(body[1], ast.Expr)
            and isinstance(body[1].value, ast.Call)
        )
        what = "a docstring, one import from shuttle.shell and one call"
    elif path == "__init__.py":
        ok = (
            len(body) == 1
            and isinstance(body[0], ast.Assign)
            and [t.id for t in body[0].targets if isinstance(t, ast.Name)] == ["__version__"]
            and len(body[0].targets) == 1
        )
        what = "a docstring and the __version__ assignment"
    else:
        return []
    if ok:
        return []
    return [f"shuttle/{path} holds more than {what}: move the code into shuttle/shell/"]


BANNED_IMPORT_RULE = "TID251"
# What ruff accepts as a lint ignore, found in comments only (never in a string): the
# line-level and file-level noqa (also spelled `flake8: noqa`) and the range comments
# `ruff: disable[...]` / `ruff: ignore[...]`. Case is ignored here although ruff is stricter
# about some spellings, so a misspelling that happens not to work today is still refused.
_NOQA = re.compile(r"#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa\b(?P<rest>[^#]*)", re.IGNORECASE)
_RANGE = re.compile(r"#\s*ruff\s*:\s*(?:disable|ignore)\s*\[(?P<codes>[^\]]*)\]", re.IGNORECASE)
_CODE = re.compile(r"[A-Za-z]+[0-9]*")


def _covers_rule(codes):
    """Whether a list of rule codes (text) covers TID251: none named (a blanket ignore), the
    rule itself, a prefix of it (TID, TID2) or ALL."""
    named = [c.upper() for c in _CODE.findall(codes)]
    return not named or any(BANNED_IMPORT_RULE.startswith(c) or c == "ALL" for c in named)


def _leading_codes(text):
    """The rule codes (letters then digits) a noqa lists, in order, up to the first word that
    is not one: in `E501 all callers pass it` the code is E501 and the rest is prose."""
    codes = []
    for word in re.split(r"[,\s]+", text.strip()):
        if not re.fullmatch(r"[A-Za-z]+[0-9]+", word):
            break
        codes.append(word)
    return codes


def _noqa_covers_rule(rest):
    """`rest` is what follows the word noqa in a comment: nothing or other words (blanket), or
    a colon and a list of codes (a colon with no valid code is treated as blanket)."""
    stripped = rest.lstrip()
    if not stripped.startswith(":"):
        return True  # a blanket ignore covers every rule
    codes = _leading_codes(stripped[1:])
    return not codes or _covers_rule(" ".join(codes))


def noqa_problems(source, path):
    """A lint ignore that covers TID251 anywhere in the file: file-level or line-level, blanket
    or naming the rule, in any spelling ruff accepts."""
    problems = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        found = [m for m in _NOQA.finditer(token.string) if _noqa_covers_rule(m["rest"])]
        found += [m for m in _RANGE.finditer(token.string) if _covers_rule(m["codes"])]
        if found:
            problems.append(
                f"shuttle/{path} line {token.start[0]} carries a lint ignore ({token.string.strip()}) "
                f"that covers the banned-import rule {BANNED_IMPORT_RULE}: take it out; code that "
                "needs a banned library belongs in shuttle/shell/"
            )
    return problems


def check_module(source, path):
    """Problems with one module's source, judged by where its file sits.

    path: the file's place relative to shuttle/, "/" separators, e.g. "core/decisions.py".
    """
    classification = classify(path)
    if classification is None:
        return [
            f"shuttle/{path} sits outside the two folders: move it into "
            "shuttle/core/ (it decides, touching nothing) or shuttle/shell/ (it reaches the "
            "world). Only __init__.py and __main__.py may sit at the package root",
            *noqa_problems(source, path),
        ]
    problems = noqa_problems(source, path)
    tree = ast.parse(source)
    problems += _entry_problems(tree, path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for target in _targets(node, path):
                problems += _import_problems(target, classification)
        elif classification == "core" and isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(
                f"the core mentions {node.id}, which reaches the world: "
                "move that code to the shell and pass the value in"
            )
    return sorted(set(problems))


def _place(target):
    """Where the module a dotted target names sits: root, core, shell, entry or other."""
    parts = target.split(".")
    if len(parts) == 1:
        return "root"
    return {"core": "core", "shell": "shell", "__main__": "entry"}.get(parts[1], "other")


def _import_problems(target, classification):
    top = target.split(".")[0]
    if top == "shuttle":
        place = _place(target)
        if place in ("root", "core") or (place in ("shell", "entry") and classification == "shell"):
            return []
        if place == "shell":
            return [
                f"the core imports {target}, a shell module: "
                "move the code that needs it into the shell and pass the value in"
            ]
        if place == "entry":
            return [
                f"the core imports {target}, the entry file, which belongs to the shell "
                "(a shell module): move the code that needs it into the shell"
            ]
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


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def python_files(root):
    """Every .py file under root, recursively, sorted. No folder is skipped by name: a source
    file inside a folder called __pycache__ is still a module Python can import (as a
    namespace package), and a folder whose name merely contains that text is just a folder.
    The interpreter's own files there end in .pyc and are not .py files."""
    return sorted(
        os.path.join(folder, name)
        for folder, _, files in os.walk(root)
        for name in files
        if name.endswith(".py")
    )


def package_files(root=PACKAGE):
    """(path relative to shuttle/, source) for every .py file under shuttle/, recursively."""
    return [
        (os.path.relpath(path, root).replace(os.sep, "/"), _read(path))
        for path in python_files(root)
    ]


def check_package(files):
    """Problems across a whole package: files is what package_files returns."""
    problems = []
    for path, source in files:
        problems += [f"{path}: {p}" for p in check_module(source, path)]
    return problems


# ----------------------------------------------------------------- the checking logic

CORE = "core/decisions.py"
SHELL = "shell/run.py"


def problems_of(source, path=CORE):
    return check_module(source, path)


class TestClassification(unittest.TestCase):
    def test_the_two_folders_and_the_two_entry_files_are_classified_by_path(self):
        self.assertEqual(classify("core/decisions.py"), "core")
        self.assertEqual(classify("core/drivers/command.py"), "core")
        self.assertEqual(classify("core/__init__.py"), "core")
        self.assertEqual(classify("__init__.py"), "core")
        self.assertEqual(classify("shell/run.py"), "shell")
        self.assertEqual(classify("shell/deep/er/thing.py"), "shell")
        self.assertEqual(classify("__main__.py"), "shell")

    def test_a_new_file_in_each_folder_is_covered_with_nothing_to_register(self):
        self.assertEqual(problems_of("import math", "core/brand_new.py"), [])
        self.assertTrue(problems_of("import os", "core/brand_new.py"))
        self.assertEqual(problems_of("import os", "shell/brand_new.py"), [])
        self.assertTrue(problems_of("import yaml", "shell/brand_new.py"))

    def test_a_new_sub_folder_in_each_folder_is_covered_with_nothing_to_register(self):
        self.assertTrue(problems_of("import os", "core/drivers/nested/thing.py"))
        self.assertTrue(problems_of("print(1)", "core/fresh/thing.py"))
        self.assertEqual(problems_of("import math", "core/fresh/thing.py"), [])
        self.assertTrue(problems_of("from shuttle.shell import run", "core/fresh/thing.py"))
        self.assertEqual(problems_of("import os\nprint(1)", "shell/fresh/thing.py"), [])
        self.assertTrue(problems_of("import yaml", "shell/fresh/thing.py"))

    def test_a_stray_module_at_the_package_root_is_refused_naming_the_file_and_the_fix(self):
        (problem,) = problems_of("x = 1", "stray.py")
        self.assertIn("shuttle/stray.py sits outside the two folders", problem)
        self.assertIn("move it into shuttle/core/", problem)
        self.assertIn("shuttle/shell/", problem)

    def test_a_root_file_named_like_a_folder_is_refused_whatever_its_name(self):
        for name in ("core.py", "shell.py", "decisions.py", "cli.py", "__version__.py"):
            with self.subTest(name=name):
                (problem,) = problems_of("X = 1", name)
                self.assertIn(f"shuttle/{name} sits outside the two folders", problem)

    def test_a_module_in_a_third_folder_is_refused_naming_the_file_and_the_fix(self):
        (problem,) = problems_of("import yaml", "extra/thing.py")
        self.assertIn("shuttle/extra/thing.py sits outside the two folders", problem)
        (problem,) = problems_of("", "extra/__init__.py")
        self.assertIn("shuttle/extra/__init__.py sits outside the two folders", problem)

    def test_where_a_name_is_not_a_place(self):
        # A folder named like a module, or a folder name only starting like a classified one.
        self.assertIsNone(classify("core.py/x.py"))
        self.assertIsNone(classify("shell.py/x.py"))
        self.assertIsNone(classify("core_extras/thing.py"))
        self.assertIsNone(classify("shellac/thing.py"))
        # A module that merely has a folder's name inside a folder is judged by the folder.
        self.assertEqual(classify("core/shell.py"), "core")
        self.assertTrue(problems_of("import os", "core/shell.py"))
        self.assertEqual(classify("shell/core/x.py"), "shell")
        self.assertEqual(problems_of("import os", "shell/core/x.py"), [])
        self.assertEqual(classify("shell/core.py"), "shell")
        # A root __init__.py or __main__.py in a sub-folder is not the package's own entry file.
        self.assertEqual(classify("extra/__main__.py"), None)
        # Only exactly __init__.py and __main__.py sit at the root.
        self.assertIsNone(classify("__main__2.py"))
        self.assertIsNone(classify("__init__.pyc.py"))

    def test_the_package_init_is_judged_as_core(self):
        self.assertTrue(problems_of("import os", "__init__.py"))

    def test_main_is_judged_as_shell(self):
        self.assertEqual(
            problems_of("import os", "__main__.py")[0].startswith("shuttle/__main__.py"), True
        )


class TestTheRootFilesStayThin(unittest.TestCase):
    MAIN = "from shuttle.shell import cli\n\ncli.entry()\n"

    def test_the_thin_main_is_fine_with_or_without_a_docstring(self):
        self.assertEqual(problems_of(self.MAIN, "__main__.py"), [])
        self.assertEqual(problems_of('"""Hands over."""\n' + self.MAIN, "__main__.py"), [])

    def test_main_with_anything_more_is_refused_saying_the_code_belongs_in_the_shell(self):
        for source in (
            self.MAIN + "x = 1\n",
            "import sys\n" + self.MAIN,
            "from shuttle.shell import cli\nif True:\n    cli.entry()\n",
            "from shuttle.shell import cli\ndef f():\n    cli.entry()\ncli.entry()\n",
            "from shuttle.shell import cli\n",
            "cli.entry()\n",
            "from shuttle.core import decisions\ndecisions.x()\n",
            "from shuttle.shell import cli\nx = cli.entry()\n",
            "from shuttle.shell import cli\ncli.entry()\ncli.entry()\n",
            "",
        ):
            with self.subTest(source=source):
                problems = [p for p in problems_of(source, "__main__.py") if "holds more" in p]
                self.assertEqual(len(problems), 1, source)
                self.assertIn("move the code into shuttle/shell/", problems[0])

    def test_the_init_holds_a_docstring_and_the_version_and_nothing_else(self):
        self.assertEqual(problems_of('__version__ = "1"', "__init__.py"), [])
        self.assertEqual(problems_of('"""Doc."""\n\n__version__ = "1"\n', "__init__.py"), [])
        for source in (
            '__version__ = "1"\nOTHER = 2\n',
            '__version__ = "1"\ndef f():\n    return 1\n',
            "OTHER = 2\n",
            "",
            '__version__ = other = "1"\n',
            "import math\n" + '__version__ = "1"\n',
        ):
            with self.subTest(source=source):
                problems = [p for p in problems_of(source, "__init__.py") if "holds more" in p]
                self.assertEqual(len(problems), 1, source)
                self.assertIn("move the code into shuttle/shell/", problems[0])

    def test_other_files_are_not_held_to_the_thin_rule(self):
        self.assertEqual(problems_of("x = 1\ny = 2\n", "core/__init__.py"), [])
        self.assertEqual(problems_of("x = 1\ny = 2\n", "shell/__init__.py"), [])


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

    def test_core_importing_the_entry_file_in_any_form_is_refused(self):
        for source in (
            "from shuttle import __main__",
            "from shuttle import __main__ as entry",
            "from .. import __main__",
            "import shuttle.__main__",
            "import shuttle.__main__ as entry",
            "from shuttle.__main__ import anything",
            "def f():\n    from shuttle import __main__\n    return __main__",
            "def f():\n    import shuttle.__main__\n",
            "from shuttle import __version__, __main__",
        ):
            with self.subTest(source=source):
                problems = problems_of(source, "core/new.py")
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("the entry file", problems[0])
                self.assertIn("belongs to the shell", problems[0])

    def test_a_relative_form_from_a_sub_folder_reaches_the_entry_file_too(self):
        (problem,) = problems_of("from ... import __main__", "core/drivers/new.py")
        self.assertIn("belongs to the shell", problem)

    def test_the_only_dunder_the_core_may_take_from_the_package_is_the_version(self):
        self.assertEqual(problems_of("from shuttle import __version__"), [])
        self.assertEqual(problems_of("from shuttle import __version__ as v"), [])
        for name in ("__main__", "__path__", "__file__", "__doc__", "__anything__"):
            with self.subTest(name=name):
                (problem,) = problems_of(f"from shuttle import {name}")
                self.assertIn(f"shuttle.{name}", problem)

    def test_core_importing_a_module_outside_both_folders_is_refused(self):
        for source in ("from shuttle import run", "import shuttle.stray"):
            with self.subTest(source=source):
                (problem,) = problems_of(source)
                self.assertIn("neither shuttle/core/ nor shuttle/shell/", problem)

    def test_a_relative_import_from_a_sub_folder_resolves_to_its_real_module(self):
        drivers = "core/drivers/command.py"
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


class TestNoLintIgnoreCoversTheBannedImportRule(unittest.TestCase):
    # Every spelling the rule test must refuse, from the suppression table
    # (tests/hostile/suppressions_table.py): all that ruff honours and the ones it does not.
    SPELLINGS = tuple(source for _, source, _, refused in SUPPRESSIONS if refused)

    def test_every_spelling_is_refused_naming_the_file_and_where_the_code_belongs(self):
        for source in self.SPELLINGS:
            for path in (CORE, "core/drivers/x.py", SHELL, "__main__.py", "stray.py"):
                with self.subTest(source=source, path=path):
                    problems = [p for p in problems_of(source, path) if "lint ignore" in p]
                    self.assertEqual(len(problems), 1, problems)
                    self.assertIn(f"shuttle/{path} line ", problems[0])
                    self.assertIn("TID251", problems[0])
                    self.assertIn("belongs in shuttle/shell/", problems[0])

    def test_the_line_number_is_the_comments(self):
        (problem,) = noqa_problems("x = 1\ny = 2\nimport os  # noqa: TID251\n", CORE)
        self.assertIn("shuttle/core/decisions.py line 3 ", problem)

    def test_each_comment_is_one_problem(self):
        self.assertEqual(len(noqa_problems("a = 1  # noqa\nb = 2  # noqa: TID251\n", CORE)), 2)

    def test_ignores_of_other_rules_and_words_that_only_look_alike_are_fine(self):
        for source in (
            "x = 1  # noqa: E501",
            "x = 1  # noqa: E501, F401",
            "x = 1  # noqa: E501 all callers pass it",
            "x = 1  # noqa: E501 t",
            "x = 1  # noqa: E501,F401 ti and tid are words",
            "# ruff: noqa: F401\nx = 1",
            "# ruff: disable[E501]\nx = 1",
            "x = 1  # a noqa mention in prose is not an ignore",
            "x = 'import os  # noqa'",
            'x = """\n# noqa\n"""',
            "x = 1  # nota bene",
            "x = 1  # noqanything",
            "x = 1  # type: ignore",
        ):
            with self.subTest(source=source):
                self.assertEqual(noqa_problems(source, CORE), [])

    def test_the_package_as_it_stands_carries_none(self):
        for path, source in package_files():
            with self.subTest(path=path):
                self.assertEqual(noqa_problems(source, path), [])


def top_modules_imported(source):
    """The top-level modules a source text imports, by parsing it (never by matching text)."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module.split(".")[0])
    return found


class TestTheImportTable(unittest.TestCase):
    """tests/hostile/imports_table.py: the forms the reviews tried, each with its verdict."""

    @staticmethod
    def place(index, folder):
        return folder if folder.endswith(".py") else f"{folder}/row_{index:03d}.py"

    def test_the_rule_test_refuses_each_row_marked_both_or_rule_test_for_the_stated_reason(self):
        for index, (label, source, folder, caught_by, _, problem) in enumerate(IMPORTS):
            with self.subTest(label=label, source=source):
                self.assertIn(caught_by, ("both", "rule test", "lint", None))
                problems = check_module(source, self.place(index, folder))
                if caught_by in ("both", "rule test"):
                    self.assertTrue(problem, "a refused row says what the refusal must say")
                    self.assertTrue(
                        any(problem in p for p in problems),
                        f"refused, but not for that reason ({problem!r}): {problems}",
                    )
                else:
                    self.assertEqual(problem, "")
                    self.assertEqual(problems, [])

    def test_every_standard_library_module_on_the_allow_list_has_an_allowed_row(self):
        imported = set()
        for _, source, folder, caught_by, *_ in IMPORTS:
            if caught_by is None and folder.startswith("core"):
                imported |= top_modules_imported(source)
        self.assertEqual(CORE_STDLIB_ALLOWED - imported, set())

    def test_the_table_has_each_kind_of_row_and_no_row_twice(self):
        kinds = {caught for _, _, _, caught, *_ in IMPORTS}
        self.assertEqual(kinds, {"both", "rule test", "lint", None})
        labels = [label for label, *_ in IMPORTS]
        self.assertEqual(len(labels), len(set(labels)))
        places = [(source, folder) for _, source, folder, *_ in IMPORTS]
        self.assertEqual(len(places), len(set(places)))

    def test_a_known_gap_says_why_in_words(self):
        for label, _, _, caught_by, note, _ in IMPORTS:
            if "known gap" in note:
                with self.subTest(label=label):
                    self.assertIsNone(caught_by)
                    self.assertGreaterEqual(len(note.split()), 8, "say why, in a sentence")


class TestTheSuppressionTable(unittest.TestCase):
    """tests/hostile/suppressions_table.py: what the rule test must do with each spelling."""

    def test_the_rule_test_refuses_exactly_the_spellings_the_table_says_it_refuses(self):
        for label, source, _, refused in SUPPRESSIONS:
            with self.subTest(label=label, source=source):
                problems = [p for p in check_module(source, CORE) if "lint ignore" in p]
                self.assertEqual(bool(problems), refused)

    def test_the_rule_test_refuses_every_spelling_the_table_says_ruff_honours(self):
        # the table's column is checked against the real ruff in tests/command/
        # test_hostile_tables.py, which also derives "honoured" from ruff's own answer
        for label, source, honoured, _ in SUPPRESSIONS:
            if honoured:
                with self.subTest(label=label, source=source):
                    problems = [p for p in check_module(source, CORE) if "lint ignore" in p]
                    self.assertTrue(problems, "ruff honours it and the rule test lets it by")

    def test_the_table_holds_each_kind_of_spelling_once(self):
        sources = [source for _, source, _, _ in SUPPRESSIONS]
        self.assertEqual(len(sources), len(set(sources)))
        self.assertTrue(any(h for _, _, h, _ in SUPPRESSIONS))
        self.assertTrue(any(r and not h for _, _, h, r in SUPPRESSIONS))
        self.assertTrue(any(not r for _, _, _, r in SUPPRESSIONS))


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
        for name in (CORE, SHELL, "core/drivers/command.py", "shell/deep/thing.py"):
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
        files = [(CORE, "x = 1"), ("stray.py", "x = 1"), ("extra/thing.py", "import yaml")]
        problems = check_package(files)
        self.assertTrue(any(p.startswith("stray.py: shuttle/stray.py sits") for p in problems))
        self.assertTrue(any("shuttle/extra/thing.py sits outside" in p for p in problems))
        self.assertEqual(len(problems), 2)

    def test_a_root_file_named_core_or_shell_fails_the_walk_beside_the_real_folder(self):
        files = [("core/__init__.py", ""), ("core.py", "X = 1"), ("shell.py", "X = 1")]
        problems = check_package(files)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("sits outside the two folders" in p for p in problems))

    def test_a_new_file_and_a_new_sub_folder_fail_the_walk_when_they_break_a_rule(self):
        files = [
            ("core/new_file.py", "import os"),
            ("core/fresh/thing.py", "import os"),
            ("shell/fresh/thing.py", "import os"),
        ]
        problems = check_package(files)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("the core imports os" in p for p in problems))

    def test_the_walk_names_files_by_their_path_under_the_package(self):
        names = [path for path, _ in package_files()]
        self.assertIn("core/decisions.py", names)
        self.assertIn("core/drivers/command.py", names)
        self.assertIn("__main__.py", names)
        self.assertTrue(all("\\" not in n for n in names))


# ------------------------------------------------------------------ the real package


class TestThePackageItself(unittest.TestCase):
    def test_the_whole_package_tree_obeys_the_rules(self):
        files = package_files()
        self.assertGreater(len(files), 8)
        self.assertEqual(check_package(files), [])

    def test_the_walk_sees_every_python_file_under_the_package(self):
        counted = sum(name.endswith(".py") for _, _, files in os.walk(PACKAGE) for name in files)
        self.assertEqual(len(package_files()), counted)

    def test_a_folder_with_the_text_pycache_in_its_name_is_walked_and_so_is_a_real_one(self):
        with tempfile.TemporaryDirectory() as root:
            for place in ("core/p__pycache__q", "core/__pycache__", "core/__pycache__/deep"):
                os.makedirs(os.path.join(root, place))
                with open(os.path.join(root, place, "m.py"), "w") as f:
                    f.write("# ruff: noqa\nimport os\n")
            with open(os.path.join(root, "core", "__pycache__", "m.cpython-312.pyc"), "wb") as f:
                f.write(b"\0")
            found = [path for path, _ in package_files(root)]
            self.assertEqual(
                found,
                ["core/__pycache__/deep/m.py", "core/__pycache__/m.py", "core/p__pycache__q/m.py"],
            )
            problems = check_package(package_files(root))
            self.assertEqual(len(problems), 6, problems)  # a lint ignore and the import, each
            self.assertTrue(all(p.startswith("core/") for p in problems))


class TestNotTestedMarkers(unittest.TestCase):
    """A line left deliberately untested says why: `# not tested: <reason>` (see report.py)."""

    def test_a_marker_with_a_reason_is_fine_and_one_without_fails_naming_the_file(self):
        self.assertEqual(report.find_markers("shuttle/a.py", "x = 1  # not tested: why\n")[1], [])
        problems = report.find_markers("shuttle/a.py", "x = 1  # not tested:\n")[1]
        self.assertEqual(len(problems), 1)
        self.assertIn("shuttle/a.py line 1", problems[0])
        self.assertIn("no reason", problems[0])

    def test_every_marker_in_the_package_and_the_checks_has_a_reason(self):
        paths = [
            os.path.join(where, name)
            for folder in ("shuttle", "checks")
            for where, _, names in os.walk(os.path.join(ROOT, folder))
            for name in sorted(names)
            if name.endswith(".py")
        ]
        problems = []
        for path in paths:
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            problems += report.find_markers(rel, _read(path))[1]
        self.assertEqual(problems, [])


class TestTheLinterAgreesWithTheFolders(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            config = tomllib.load(f)["tool"]
        self.lint = config["ruff"]["lint"]
        self.assertNotIn("shuttle", config, "the folders are the classification: no table")

    def test_the_one_ban_list_bans_the_shell_folder_and_the_entry_file_and_nothing_else(self):
        banned = set(self.lint["flake8-tidy-imports"]["banned-api"])
        ours = {m for m in banned if m.split(".")[0] == "shuttle"}
        self.assertEqual(ours, {"shuttle.shell", "shuttle.__main__"})

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
