"""A function in checks/ that takes file names must be run against the names table.

Every helper script in checks/ handles file names, which are data: a space, a newline, a
backtick, bytes that are not UTF-8, a link. Five reviews in a row found the same two kinds of
defect (a guard that did not guard, a name treated as text), each time by hand. The names
table (tests/hostile/names_table.py) holds the cases; tests/by_value/test_names_table.py runs
every function that takes a name against all of them. This rule keeps the list of such
functions from going stale: it reads every .py under checks/ (any depth) with `ast`, looks at
every function definition in each (any nesting: methods, nested functions, definitions under
an `if` or `try`, sync or async) and fails on one that takes names unless it is registered in
tests/hostile/registry.py, either as table-tested (with the test that does it) or as exempt
(with the reason).

The rule's job is to catch NEW functions. A function that takes names is recognised by its
signature alone: a parameter (positional, keyword-only, *args or **kwargs) whose lower-cased
name contains one of NAME_PARTS (path, file, name, folder, root, link, source) or has the
word dir in it (dir_path, but not dirty), or whose
annotation mentions Path. A function already registered stays registered whatever its
parameters are called. What this cannot see: a name-carrying parameter called something else
(`item`, `entry`, `x`, `facts`, `lines`), a name inside another value under such a parameter,
a function reading a name from the environment or a global, and a lambda. When it misses a word
a function really uses, add the word to NAME_PARTS. The rule is a net with wide holes; the
table tests of the existing functions are the real guard.

A registered test has to exist, be a test method, and refer to the names table (directly or
through one helper it calls), or registering against an unrelated test would pass.

The checking logic is in functions over source text; these tests start no process and touch
nothing but the files they read.
"""

import ast
import os
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TESTS)
CHECKS = os.path.join(ROOT, "checks")
sys.path.insert(0, TESTS)

from hostile import registry  # noqa: E402  (the path is set above)

NAME_PARTS = (
    "path",
    "file",
    "name",
    "folder",
    "root",
    "link",
    "source",
    "changed",
    "failed",
    "entries",
    "listing",
    "target",
    "location",
)
# "dir" is a word of its own, or "dirs", "dirname", "dirpath": inside another word it is not
# (`dirty`).
DIR_WORDS = ("dir", "dirs", "dirname", "dirpath")
ANNOTATION_PARTS = ("Path",)
# What a test that loops the names table refers to (tests/by_value/test_names_table.py).
TABLE_REFERENCES = frozenset({"ROWS", "NO_NUL", "HOLDABLE", "NAMES"})
WHERE = (
    "run it against the whole names table in tests/by_value/test_names_table.py, then register "
    "it in TABLE_TESTED in tests/hostile/registry.py (with the test that does it); or, if it "
    "does not carry file names, give it a reason in EXEMPT in the same file"
)


def carries_names(arg):
    """Whether a parameter (an ast.arg) looks as if it carries file names or paths."""
    lowered = arg.arg.lower()
    if any(part in lowered for part in NAME_PARTS) or any(
        word in DIR_WORDS for word in lowered.split("_")
    ):
        return True
    text = ast.unparse(arg.annotation) if arg.annotation is not None else ""
    return any(part in text for part in ANNOTATION_PARTS)


def functions(source, module):
    """{"module.outer.inner": [parameters that carry names]} for every function definition in
    the source, at any depth and of either kind; a function with none maps to []."""
    found = {}

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                args = child.args
                every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
                every += [a for a in (args.vararg, args.kwarg) if a is not None]
                found[f"{prefix}{child.name}"] = [a.arg for a in every if carries_names(a)]
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(ast.parse(source), f"{module}.")
    return found


def unregistered(found, tested, exempt, test_exists):
    """Problems: functions that take names and are neither table-tested nor exempt, entries
    that are both, exemptions without a reason or that no function needs (it does not take
    names under the recognition above), entries for functions that do not exist any more (a
    stale registration hides a missing one) and registered tests that do not exist or do not
    refer to the names table.

    found: functions' result, over every module. tested: key to a test reference. exempt: key
    to a reason. test_exists: a test reference to whether it is a test that loops the table."""
    problems = []
    for key, params in sorted(found.items()):
        if params and key not in tested and key not in exempt:
            problems.append(
                f"{key} takes names or paths ({', '.join(params)}) and is not registered: {WHERE}"
            )
    for key in sorted(set(tested) & set(exempt)):
        problems.append(f"{key} is both table-tested and exempt: keep one")
    for key, reason in sorted(exempt.items()):
        if not reason or not str(reason).strip():
            problems.append(f"{key} is exempt with no reason: say why it does not carry names")
        elif key in found and not found[key]:
            problems.append(
                f"{key} is exempt but takes no parameter that looks like a name: drop it"
            )
    for key, ref in sorted(tested.items()):
        if not test_exists(ref):
            problems.append(
                f"{key} is registered as tested by {ref}, which is not a test that loops the "
                "names table (it must exist, start with test, and refer to ROWS, NO_NUL, "
                "HOLDABLE or NAMES, directly or through a helper)"
            )
    for key in sorted((set(tested) | set(exempt)) - set(found)):
        problems.append(
            f"{key} is registered but no such function exists in checks/: "
            "take the entry out of tests/hostile/registry.py"
        )
    return problems


def python_files(folder=CHECKS):
    """Every .py file under folder, at any depth, as a path relative to it, sorted."""
    return sorted(
        os.path.relpath(os.path.join(where, name), folder)
        for where, _, names in os.walk(folder)
        for name in names
        if name.endswith(".py")
    )


def module_of(relative):
    """checks/sub/x.py is the module "sub.x"."""
    return relative[: -len(".py")].replace(os.sep, ".")


def checks_functions(folder=CHECKS):
    found = {}
    for relative in python_files(folder):
        with open(os.path.join(folder, relative), encoding="utf-8") as f:
            found.update(functions(f.read(), module_of(relative)))
    return found


def _names_in(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }


def test_exists(ref, tests=TESTS):
    """A reference "folder/file.py::Class.method" names a test method in that file that refers
    to the names table, directly or through one helper (a method of the class, or a function
    of the module) that does."""
    path, _, where = ref.partition("::")
    cls, _, method = where.partition(".")
    try:
        with open(os.path.join(tests, path), encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except OSError:
        return False
    helpers = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            methods = {m.name: m for m in node.body if isinstance(m, ast.FunctionDef)}
            helpers.update(methods)
            target = methods.get(method)
            if target is None or not method.startswith("test"):
                return False
            used = _names_in(target)
            if used & TABLE_REFERENCES:
                return True
            return any(_names_in(helpers[h]) & TABLE_REFERENCES for h in used if h in helpers)
    return False


class TestRecognition(unittest.TestCase):
    def test_a_parameter_with_a_name_like_part_makes_a_function_one_that_takes_names(self):
        source = (
            "def f(path): pass\ndef g(a, *, root=None): pass\ndef h(*names): pass\n"
            "def i(file_path): pass\ndef j(dir_path, sources): pass\ndef k(self, Link): pass\n"
            "def l(folder, filename): pass\n"
            "def m(dir, dirty, mydir_path): pass\n"
        )
        found = {k: v for k, v in functions(source, "m").items() if v}
        self.assertEqual(
            found,
            {
                "m.f": ["path"],
                "m.g": ["root"],
                "m.h": ["names"],
                "m.i": ["file_path"],
                "m.j": ["dir_path", "sources"],
                "m.k": ["Link"],
                "m.l": ["folder", "filename"],
                "m.m": ["dir", "mydir_path"],
            },
        )

    def test_an_annotation_mentioning_path_makes_the_parameter_one_that_takes_names(self):
        source = "def f(target: Path, other: int, p: 'pathlib.Path | None'): pass\n"
        self.assertEqual(functions(source, "m"), {"m.f": ["target", "p"]})

    def test_general_words_and_unrelated_parameters_are_not_names(self):
        source = "def f(lines, facts, before, after, known, raw, item, x): pass\n"
        self.assertEqual(functions(source, "m"), {"m.f": []})

    def test_the_reviewers_24_signatures_that_carry_a_file_name_are_twelve_flagged_twelve_missed(
        self,
    ):
        # Round-two review of pull request #12, note N1: 24 plausible new signatures. The word
        # rule saw 6 of them (the first six) and now sees 12; the other 12 are the holes
        # the README names. The list is the reviewer's, the annotations are filled in.
        flagged = [
            "def a(file: str): pass",
            "def b(file_path: str): pass",
            "def c(paths: list[str]): pass",
            "def d(names: list[str]): pass",
            "def e(fname: str): pass",
            "def f(handle: Path): pass",
            "def g(changed: list[str]): pass",
            "def h(failed: list[str]): pass",
            "def i(entries: list[str]): pass",
            "def j(listing: list[str]): pass",
            "def k(target: str): pass",
            "def l(location: str): pass",
        ]
        missed = [
            "def m(p: str): pass",
            "def n(entry: str): pass",
            "def o(base: str, rel: str): pass",
            "def q(candidate: str): pass",
            "def r(items: list[str]): pass",
            "def s(fn: str): pass",
            "def t(top: str): pass",
            "def u(label: str): pass",
            "def v(f: str): pass",
            "def w(where: str): pass",
            "def x(out: str): pass",
            "def y(rows: list[str]): pass",
        ]
        source = "\n".join(flagged + missed) + "\n"
        self.assertEqual(len(flagged + missed), 24)
        found = functions(source, "m")
        self.assertEqual(sum(1 for params in found.values() if params), 12)
        self.assertEqual([k for k, v in found.items() if v], [f"m.{c}" for c in "abcdefghijkl"])

    def test_a_method_is_named_with_its_class(self):
        self.assertEqual(
            functions("class C:\n    def m(self, files): pass\n", "mod"),
            {"mod.C.m": ["files"]},
        )

    def test_every_kind_of_definition_is_seen(self):
        source = (
            "async def a(path): pass\n"
            "def outer():\n    def inner(path): pass\n"
            "if True:\n    def conditional(path): pass\n"
            "try:\n    def in_try(path): pass\nexcept ImportError:\n"
            "    def in_except(path): pass\n"
            "class C:\n    async def method(self, path): pass\n"
            "    class D:\n        def deep(self, path): pass\n"
        )
        found = {k: v for k, v in functions(source, "m").items() if v}
        self.assertEqual(
            sorted(found),
            [
                "m.C.D.deep",
                "m.C.method",
                "m.a",
                "m.conditional",
                "m.in_except",
                "m.in_try",
                "m.outer.inner",
            ],
        )


class TestTheWalkSeesEverything(unittest.TestCase):
    """The class of defect #7 found in the package walk: a rule that reads only direct children
    of a folder passes everything below it."""

    def tree(self, files):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for relative, text in files.items():
            path = os.path.join(folder.name, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return folder.name

    def test_a_function_taking_a_path_in_a_sub_folder_and_a_sub_sub_folder_is_seen(self):
        root = self.tree(
            {
                "top.py": "def a(path): pass\n",
                "sub/x.py": "def in_sub(path: str) -> str:\n    return path\n",
                "sub/deeper/y.py": "def in_sub_sub(file_path): pass\n",
                "sub/data.txt": "def not_python(path): pass\n",
            }
        )
        found = {k for k, v in checks_functions(root).items() if v}
        self.assertEqual(found, {"top.a", "sub.x.in_sub", "sub.deeper.y.in_sub_sub"})

    def test_a_nested_conditional_async_and_method_definition_in_a_sub_folder_is_seen(self):
        root = self.tree(
            {
                "sub/z.py": (
                    "def outer():\n    def inner(path): pass\n"
                    "if True:\n    def cond(path): pass\n"
                    "async def acoro(path): pass\n"
                    "class C:\n    def meth(self, path): pass\n"
                )
            }
        )
        found = {k for k, v in checks_functions(root).items() if v}
        self.assertEqual(
            found,
            {"sub.z.outer.inner", "sub.z.cond", "sub.z.acoro", "sub.z.C.meth"},
        )

    def test_each_of_those_fails_the_rule_until_it_is_registered(self):
        root = self.tree({"sub/deeper/y.py": "async def f(path): pass\n"})
        found = checks_functions(root)
        problems = unregistered(found, {}, {}, lambda ref: True)
        self.assertEqual(len(problems), 1)
        self.assertIn("sub.deeper.y.f", problems[0])
        tested = {"sub.deeper.y.f": "x/t.py::T.test_a"}
        self.assertEqual(unregistered(found, tested, {}, lambda ref: True), [])

    def test_the_modules_the_rule_sees_are_the_python_files_under_checks(self):
        seen = {module_of(r) for r in python_files()}
        seen_by_functions = {key.rsplit(".", 1)[0] for key in checks_functions()}
        found = set()
        for where, _, names in os.walk(CHECKS):
            for name in names:
                if name.endswith(".py"):
                    relative = os.path.relpath(os.path.join(where, name), CHECKS)
                    found.add(relative[: -len(".py")].replace(os.sep, "."))
        self.assertEqual(seen, found)
        # a module that defines no function has no key, so only the other direction is exact
        for module in seen_by_functions:
            self.assertTrue(any(m == module or module.startswith(m + ".") for m in seen), module)
        self.assertTrue(seen)


class TestTheGuardOfTheRule(unittest.TestCase):
    def run_rule(self, source, tested=None, exempt=None, exists=lambda ref: True):
        found = functions(source, "newmod")
        return unregistered(found, tested or {}, exempt or {}, exists)

    def test_a_new_function_with_a_path_parameter_fails_naming_it_and_where_to_add_it(self):
        (problem,) = self.run_rule("def shorten(path):\n    return path\n")
        self.assertIn("newmod.shorten", problem)
        self.assertIn("tests/hostile/registry.py", problem)
        self.assertIn("tests/by_value/test_names_table.py", problem)

    def test_a_new_async_function_with_a_path_parameter_fails_too(self):
        (problem,) = self.run_rule("async def shorten(path):\n    return path\n")
        self.assertIn("newmod.shorten", problem)

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

    def test_an_exemption_no_function_needs_fails(self):
        (problem,) = self.run_rule("def f(count):\n    return count\n", exempt={"newmod.f": "why"})
        self.assertIn("takes no parameter that looks like a name", problem)

    def test_a_function_without_such_a_parameter_needs_nothing(self):
        self.assertEqual(self.run_rule("def f(count, text):\n    return count\n"), [])

    def test_a_registered_function_stays_registered_whatever_its_parameters_are_called(self):
        source = "def f(lines):\n    return lines\n"
        self.assertEqual(self.run_rule(source, tested={"newmod.f": "x/t.py::T.test_a"}), [])

    def test_a_registration_whose_test_is_not_one_fails(self):
        source = "def shorten(path):\n    return path\n"
        problems = self.run_rule(
            source, tested={"newmod.shorten": "x/t.py::T.test_gone"}, exists=lambda ref: False
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("not a test that loops the names table", problems[0])

    def test_a_registration_for_a_function_that_does_not_exist_fails(self):
        problems = self.run_rule("def f(count): pass\n", tested={"newmod.gone": "x/t.py::T.t"})
        self.assertEqual(len(problems), 1)
        self.assertIn("newmod.gone", problems[0])
        self.assertIn("no such function exists", problems[0])

    def test_a_function_both_tested_and_exempt_fails(self):
        source = "def shorten(path):\n    return path\n"
        problems = self.run_rule(
            source, tested={"newmod.shorten": "x"}, exempt={"newmod.shorten": "why"}
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("both", problems[0])


class TestARegisteredTestLoopsTheTable(unittest.TestCase):
    SOURCE = (
        "import unittest\n"
        "ROWS = []\n"
        "def module_helper():\n    return ROWS\n"
        "class T(unittest.TestCase):\n"
        "    def helper(self):\n        return NO_NUL\n"
        "    def test_direct(self):\n        for r in HOLDABLE: pass\n"
        "    def test_through_a_method(self):\n        self.helper()\n"
        "    def test_through_a_function(self):\n        module_helper()\n"
        "    def test_unrelated(self):\n        self.assertTrue(True)\n"
        "    def helper_not_a_test(self):\n        return ROWS\n"
    )

    def check(self, method):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "d"))
            with open(os.path.join(folder, "d", "t.py"), "w", encoding="utf-8") as f:
                f.write(self.SOURCE)
            return test_exists(f"d/t.py::{method}", tests=folder)

    def test_a_test_that_refers_to_the_table_directly_or_through_one_helper_counts(self):
        for method in ("T.test_direct", "T.test_through_a_method", "T.test_through_a_function"):
            with self.subTest(method=method):
                self.assertTrue(self.check(method))

    def test_a_test_that_never_touches_the_table_does_not(self):
        self.assertFalse(self.check("T.test_unrelated"))

    def test_a_method_without_the_test_prefix_does_not_count_even_if_it_refers_to_the_table(self):
        self.assertFalse(self.check("T.helper_not_a_test"))
        self.assertFalse(self.check("T.helper"))

    def test_a_missing_class_method_or_file_does_not_count(self):
        self.assertFalse(self.check("Nope.test_direct"))
        self.assertFalse(self.check("T.test_missing"))
        self.assertFalse(test_exists("d/absent.py::T.test_direct", tests=TESTS))

    def test_a_registration_against_an_unrelated_test_in_this_repository_fails(self):
        mine = os.path.join("by_value", "test_name_functions.py")
        self.assertFalse(
            test_exists(f"{mine}::TestRecognition.test_a_method_is_named_with_its_class")
        )


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
