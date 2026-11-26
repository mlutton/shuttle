"""A function in checks/ that takes file names must be run against the names table.

Every helper script in checks/ handles file names, which are data: a space, a newline, a
backtick, bytes that are not UTF-8, a link. Five reviews in a row found the same two kinds of
defect (a guard that did not guard, a name treated as text), each time by hand. The names
table (tests/hostile/names_table.py) holds the cases; tests/by_value/test_names_table.py runs
every function that takes a name against all of them. This rule keeps the list of such
functions from going stale: it reads checks/*.py with `ast` and fails on a function that takes
a parameter likely to carry names or paths unless the function is registered in
tests/hostile/registry.py, either as table-tested (with the test that does it) or as exempt
(with the reason).

How a function "takes names" is recognised, mechanically and only by its signature: any
parameter (positional, keyword-only, *args or **kwargs) whose name is in NAME_PARAMETERS.
What that cannot see: a parameter called something else (`item`, `entry`, `x`), a name that
travels inside another value (a dataclass field, a dict key, the text of a tool's output) when
the parameter has an unlisted name, a function that reads a name from the environment or a
global, and a nested function (only module-level functions and class methods are read). The
set is short on purpose; when it misses a word a function uses, add the word here.

The checking logic is `unregistered`, over source text: these tests start no process and
touch nothing but the files they read.
"""

import ast
import os
import sys
import unittest

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TESTS)
CHECKS = os.path.join(ROOT, "checks")
sys.path.insert(0, TESTS)

from hostile import registry  # noqa: E402  (the path is set above)

NAME_PARAMETERS = frozenset(
    {
        "name",
        "names",
        "filename",
        "filenames",
        "file",
        "files",
        "path",
        "paths",
        "folder",
        "root",
        "changed",
        "changes",
        "failed",
        "known",
        "guards",
        "links",
        "walked",
        "before",
        "after",
        "raw",
        "lines",
        "diagnostics",
        "facts",
    }
)
WHERE = (
    "run it against the whole names table in tests/by_value/test_names_table.py, then register "
    "it in TABLE_TESTED in tests/hostile/registry.py (with the test that does it); or, if it "
    "does not carry file names, give it a reason in EXEMPT in the same file"
)


def name_functions(source, module):
    """{"module.function": [parameters in NAME_PARAMETERS]} for each module-level function and
    class method in the source whose signature has any."""
    found = {}

    def visit(body, prefix):
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                args = node.args
                every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
                every += [a for a in (args.vararg, args.kwarg) if a is not None]
                hits = [a.arg for a in every if a.arg in NAME_PARAMETERS]
                if hits:
                    found[f"{module}.{prefix}{node.name}"] = hits

    visit(ast.parse(source).body, "")
    return found


def unregistered(found, tested, exempt, test_exists):
    """Problems: functions that take names and are neither table-tested nor exempt, entries
    that are both, exemptions without a reason, registered tests that do not exist and entries
    for functions that no longer take names (a stale registration hides a missing one).

    found: name_functions' result, over every module. tested: key to a test reference.
    exempt: key to a reason. test_exists: a test reference to whether it exists."""
    problems = []
    for key, params in sorted(found.items()):
        if key not in tested and key not in exempt:
            problems.append(
                f"{key} takes names or paths ({', '.join(params)}) and is not registered: {WHERE}"
            )
    for key in sorted(set(tested) & set(exempt)):
        problems.append(f"{key} is both table-tested and exempt: keep one")
    for key, reason in sorted(exempt.items()):
        if not reason or not str(reason).strip():
            problems.append(f"{key} is exempt with no reason: say why it does not carry names")
    for key, ref in sorted(tested.items()):
        if not test_exists(ref):
            problems.append(f"{key} is registered as tested by {ref}, which does not exist")
    for key in sorted((set(tested) | set(exempt)) - set(found)):
        problems.append(
            f"{key} is registered but no function of that name takes names or paths any more: "
            "take the entry out of tests/hostile/registry.py"
        )
    return problems


def checks_functions(folder=CHECKS):
    found = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".py"):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                found.update(name_functions(f.read(), name[: -len(".py")]))
    return found


def test_exists(ref, tests=TESTS):
    """A reference "folder/file.py::Class.method" names a test method that is in that file."""
    path, _, where = ref.partition("::")
    cls, _, method = where.partition(".")
    try:
        with open(os.path.join(tests, path), encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except OSError:
        return False
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return any(
                isinstance(m, ast.FunctionDef) and m.name == method and method.startswith("test")
                for m in node.body
            )
    return False


class TestRecognition(unittest.TestCase):
    def test_a_parameter_in_the_set_makes_a_function_one_that_takes_names(self):
        source = "def f(path): pass\ndef g(a, *, root=None): pass\ndef h(*names): pass\n"
        found = name_functions(source, "m")
        self.assertEqual(found, {"m.f": ["path"], "m.g": ["root"], "m.h": ["names"]})

    def test_other_parameters_and_nested_functions_are_not_seen(self):
        source = "def f(item, count): pass\ndef g(a):\n    def inner(path): pass\n"
        self.assertEqual(name_functions(source, "m"), {})

    def test_a_method_is_named_with_its_class(self):
        self.assertEqual(
            name_functions("class C:\n    def m(self, files): pass\n", "mod"),
            {"mod.C.m": ["files"]},
        )


class TestTheGuardOfTheRule(unittest.TestCase):
    def run_rule(self, source, tested=None, exempt=None, exists=lambda ref: True):
        found = name_functions(source, "newmod")
        return unregistered(found, tested or {}, exempt or {}, exists)

    def test_a_new_function_with_a_path_parameter_fails_naming_it_and_where_to_add_it(self):
        (problem,) = self.run_rule("def shorten(path):\n    return path\n")
        self.assertIn("newmod.shorten", problem)
        self.assertIn("tests/hostile/registry.py", problem)
        self.assertIn("tests/by_value/test_names_table.py", problem)

    def test_registering_it_makes_it_pass(self):
        source = "def shorten(path):\n    return path\n"
        self.assertEqual(self.run_rule(source, tested={"newmod.shorten": "x/t.py::T.test_a"}), [])

    def test_an_exemption_with_a_reason_passes_and_without_one_fails(self):
        source = "def shorten(path):\n    return path\n"
        self.assertEqual(self.run_rule(source, exempt={"newmod.shorten": "it is a version"}), [])
        for reason in ("", "   ", None):
            with self.subTest(reason=reason):
                (problem,) = self.run_rule(source, exempt={"newmod.shorten": reason})
                self.assertIn("exempt with no reason", problem)

    def test_a_function_without_such_a_parameter_needs_nothing(self):
        self.assertEqual(self.run_rule("def f(count, text):\n    return count\n"), [])

    def test_a_registration_whose_test_does_not_exist_fails(self):
        source = "def shorten(path):\n    return path\n"
        problems = self.run_rule(
            source, tested={"newmod.shorten": "x/t.py::T.test_gone"}, exists=lambda ref: False
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("does not exist", problems[0])

    def test_a_stale_registration_fails(self):
        problems = self.run_rule("def f(count): pass\n", tested={"newmod.gone": "x/t.py::T.t"})
        self.assertEqual(len(problems), 1)
        self.assertIn("newmod.gone", problems[0])
        self.assertIn("no function of that name", problems[0])

    def test_a_function_both_tested_and_exempt_fails(self):
        source = "def shorten(path):\n    return path\n"
        problems = self.run_rule(
            source, tested={"newmod.shorten": "x"}, exempt={"newmod.shorten": "why"}
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("both", problems[0])

    def test_a_reference_names_a_real_test_method_or_it_does_not_exist(self):
        mine = os.path.join("by_value", "test_name_functions.py")
        self.assertTrue(
            test_exists(f"{mine}::TestRecognition.test_a_method_is_named_with_its_class")
        )
        self.assertFalse(test_exists(f"{mine}::TestRecognition.test_nothing_of_the_kind"))
        self.assertFalse(test_exists(f"{mine}::NoClass.test_a_method_is_named_with_its_class"))
        self.assertFalse(test_exists("by_value/no_such_file.py::C.test_x"))
        self.assertFalse(test_exists(f"{mine}::TestRecognition.name_functions"))


class TestTheChecksFolder(unittest.TestCase):
    def test_every_function_in_checks_that_takes_names_is_table_tested_or_exempt(self):
        problems = unregistered(
            checks_functions(), registry.TABLE_TESTED, registry.EXEMPT, test_exists
        )
        self.assertEqual(problems, [])

    def test_the_walk_sees_the_helper_scripts(self):
        keys = checks_functions()
        for key in ("guards.is_guard", "names.escape_name", "fixmode.render_lines"):
            self.assertIn(key, keys)


if __name__ == "__main__":
    unittest.main()
