"""The decisions inside the check's helper scripts (checks/*.py), as functions over plain data."""

import ast
import importlib
import os
import sys
import unittest

CHECKS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "checks")
sys.path.insert(0, CHECKS)
names = importlib.import_module("names")
guards = importlib.import_module("guards")
fixmode = importlib.import_module("fixmode")

AWKWARD = ["my file.py", "a`b.py", "a<b>|c.py", "é ü.py", "line\nbreak.py", "back\\slash.py"]


class EscapeNameTest(unittest.TestCase):
    def test_control_characters_and_backslash_are_escaped(self):
        self.assertEqual(names.escape_name("a\nb\tc\\d\x01"), "a\\nb\\tc\\\\d\\x01")

    def test_c1_controls_and_bidirectional_controls_are_escaped(self):
        self.assertEqual(names.escape_name("a\x85b\x9fc"), "a\\u0085b\\u009fc")
        self.assertEqual(
            names.escape_name("a\u202eb\u2066c\u200fd\u2029"), "a\\u202eb\\u2066c\\u200fd\\u2029"
        )

    def test_a_byte_that_is_not_valid_utf8_is_shown_as_an_escape_and_the_result_prints(self):
        name = os.fsdecode(b"bad\xff.py")
        shown = names.escape_name(name)
        self.assertEqual(shown, "bad\\xff.py")
        shown.encode("utf-8")  # no surrogate is left to crash a print
        self.assertEqual(names.escape_name("\ud800"), "\\ud800")

    def test_everything_else_is_kept(self):
        for name in ("my file.py", "a`b<c>|d", "é.sh"):
            self.assertEqual(names.escape_name(name), name)


class GitOutputTest(unittest.TestCase):
    def test_names_with_spaces_newlines_and_non_ascii_come_back_whole(self):
        raw = b"M\0my file.py\0A\0line\nbreak.py\0D\0\xc3\xa9.sh\0"
        self.assertEqual(
            guards.parse_name_status(raw),
            [("M", "my file.py"), ("A", "line\nbreak.py"), ("D", "é.sh")],
        )

    def test_a_name_that_is_not_valid_utf8_survives_and_renders_escaped(self):
        parsed = guards.parse_name_status(b"M\0checks/bad\xff.sh\0")
        text = guards.render_summary(guards.guard_changes(parsed))
        self.assertIn("changed checks/bad\\xff.sh", text)
        text.encode("utf-8")

    def test_no_output_is_no_changes(self):
        self.assertEqual(guards.parse_name_status(b""), [])


class GuardChangesTest(unittest.TestCase):
    def guards_in(self, *paths):
        return [path for _, path in guards.guard_changes([("M", p) for p in paths])]

    def test_each_kind_of_guard_file_is_one(self):
        paths = [
            "checks/all.sh",
            "checks/é.sh",
            ".githooks/pre-push",
            ".github/workflows/tests.yml",
            "pyproject.toml",
            "requirements-dev.txt",
            "tests/by_value/test_rules.py",
            "AGENTS.md",
            "CLAUDE.md",
            "CODING_STANDARDS.md",
            "docs/process.md",
            ".claude/agents/shuttle-builder.md",
            ".claude/agents/deeper/x.md",
            "tests/command/test_base_check.py",
            "tests/command/test_check_script.py",
            "tests/command/test_hook.py",
        ]
        self.assertEqual(self.guards_in(*paths), sorted(paths))

    def test_lookalikes_are_not_guard_files(self):
        self.assertEqual(
            self.guards_in(
                ".githubx/w.yml", "checks2/a.sh", "docs/pyproject.toml", "checks.md", "old.toml"
            )
            + self.guards_in(
                "docs/AGENTS.md",
                "docs/CLAUDE.md",
                "docs/process.md.bak",
                "docs/other.md",
                ".claude/settings.json",
                ".claude/agentsx/a.md",
                "CODING_STANDARDS.md.orig",
                "agents/AGENTS.md",
            ),
            [],
        )

    def test_what_happened_is_marked_for_added_deleted_and_the_rest(self):
        changes = [
            ("A", "checks/a.sh"),
            ("D", "checks/b.sh"),
            ("M", "checks/c.sh"),
            ("T", "pyproject.toml"),
        ]
        self.assertEqual(
            guards.guard_changes(changes),
            [
                ("added", "checks/a.sh"),
                ("deleted", "checks/b.sh"),
                ("changed", "checks/c.sh"),
                ("changed", "pyproject.toml"),
            ],
        )

    def test_a_guard_file_moved_away_is_listed_as_deleted_from_its_old_path(self):
        # git diff --no-renames reports a move as a deletion and an addition
        listed = guards.guard_changes([("D", "pyproject.toml"), ("A", "old.toml")])
        self.assertEqual(listed, [("deleted", "pyproject.toml")])


class TheAttackListsAreGuardFilesTest(unittest.TestCase):
    TESTS = os.path.join(os.path.dirname(CHECKS), "tests")

    def test_everything_in_the_hostile_folder_is_a_guard_file_whatever_it_is_called(self):
        for path in (
            "tests/hostile/names_table.py",
            "tests/hostile/a_table_not_yet_written.py",
            "tests/hostile/sub/deeper.py",
            "tests/hostile/data.json",
        ):
            with self.subTest(path=path):
                self.assertTrue(guards.is_guard(path))
        for path in ("tests/hostile2/x.py", "tests/hostilex.py", "docs/tests/hostile/x.py"):
            with self.subTest(path=path):
                self.assertFalse(guards.is_guard(path))

    def files_to_read(self):
        return [
            os.path.join(where, name)
            for where, _, files in os.walk(self.TESTS)
            for name in files
            if name.endswith(".py")
            and "hostile" not in os.path.relpath(os.path.join(where, name), self.TESTS)
        ]

    def reads_the_tables_in(self, path):
        with open(path, encoding="utf-8") as f:
            return any(self.reads_the_tables(node) for node in ast.walk(ast.parse(f.read())))

    @staticmethod
    def reads_the_tables(node):
        """`from hostile... import`, `import hostile...` or importlib.import_module("hostile..."),
        and the same through the package: `from tests.hostile import x`, `from tests import
        hostile`, `import tests.hostile`."""

        def hostile(dotted):
            parts = dotted.split(".")
            return parts[0] == "hostile" or parts[:2] == ["tests", "hostile"]

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            return hostile(module) or (
                module == "tests" and any(a.name == "hostile" for a in node.names)
            )
        if isinstance(node, ast.Import):
            return any(hostile(a.name) for a in node.names)
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and bool(node.args)
            and isinstance(node.args[0], ast.Constant)
            and hostile(str(node.args[0].value))
        )

    @staticmethod
    def first_node(source):
        node = ast.parse(source).body[0]
        return node.value if isinstance(node, ast.Expr) else node

    def test_every_form_of_importing_the_tables_is_seen_and_other_imports_are_not(self):
        for source in (
            "from hostile import x",
            "from hostile.names_table import NAMES",
            "import hostile",
            "import hostile.registry",
            "from tests.hostile import x",
            "from tests.hostile.names_table import NAMES",
            "from tests import hostile",
            "import tests.hostile",
            "import tests.hostile.registry as r",
            "importlib.import_module('hostile.registry')",
            "importlib.import_module('tests.hostile.registry')",
        ):
            with self.subTest(source=source):
                self.assertTrue(self.reads_the_tables(self.first_node(source)))
        for source in (
            "from tests import by_value",
            "from tests.by_value import x",
            "import tests",
            "from hostilex import x",
            "from tests.hostile2 import x",
            "from x.tests.hostile import y",
            "import os",
        ):
            with self.subTest(source=source):
                self.assertFalse(self.reads_the_tables(self.first_node(source)))

    def test_each_test_file_that_is_a_rule_or_loops_a_table_is_a_guard_file(self):
        # The rule: a test file under tests/ that imports from `hostile` (the attack lists) is
        # a guard file, so a pull request that weakens it is listed. A file that is a rule
        # without importing `hostile` has to be named in GUARD_FILES by hand.
        found = [
            os.path.relpath(path, os.path.dirname(self.TESTS))
            for path in self.files_to_read()
            if self.reads_the_tables_in(path)
        ]
        self.assertTrue(found)
        for path in found:
            with self.subTest(path=path):
                self.assertTrue(
                    guards.is_guard(path.replace(os.sep, "/")), "list it in GUARD_FILES"
                )

    def test_every_guard_file_named_by_hand_exists(self):
        root = os.path.dirname(CHECKS)
        for path in guards.GUARD_FILES:
            with self.subTest(path=path):
                self.assertTrue(os.path.exists(os.path.join(root, path)))


class TableSourceTest(unittest.TestCase):
    NAMES = 'NAMES = [{"label": "a", "name": "x" * 3, "path": False, "holdable": True}]\n'
    SUPPRESSIONS = 'S = ("l", "src", True, False)\nSUPPRESSIONS = (("l", "s", True, False),)\n'

    def test_a_table_is_read_as_data_with_constants_products_and_sums(self):
        source = 'N = "n" * 2\nNAMES = [{"label": N + "!", "gaps": {"m.f": "why"}}]\n'
        (row,) = guards.load_table("names", source)
        self.assertEqual((row["label"], row["gaps"]), ("nn!", {"m.f": "why"}))

    def test_tuples_become_rows_with_named_fields_and_a_known_gap_note_becomes_a_mark(self):
        source = 'IMPORTS = (("l", "s", "core", None, "known gap: why", ""),)\n'
        (row,) = guards.load_table("imports", source)
        self.assertEqual(row["folder"], "core")
        self.assertEqual(row["gaps"], {"import form": "known gap: why"})

    def test_a_table_that_is_not_plain_data_is_refused_and_not_run(self):
        for source in (
            "import os\nNAMES = []\n",
            "NAMES = [__import__('os').getcwd()]\n",
            "NAMES = [x]\n",
            "def f(): pass\nNAMES = []\n",
            "NAMES = [",
            "OTHER = []\n",
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                guards.load_table("names", source)

    def test_a_name_that_is_not_valid_text_in_a_table_still_reads(self):
        (row,) = guards.load_table("names", 'NAMES = [{"label": "\\udcff"}]\n')
        self.assertEqual(row["label"], "\udcff")


def rows(*labels, **changes):
    return [{"label": label, "gaps": changes.get(label, {})} for label in labels]


class TableReportTest(unittest.TestCase):
    def both(self, base, head):
        """(changes, standing) for the names table alone."""
        return guards.table_report(
            {"names": base, "imports": None, "suppressions": None},
            {"names": head, "imports": None, "suppressions": None},
        )

    def report(self, base, head):
        return self.both(base, head)[0]

    def test_a_row_at_the_base_and_not_at_the_head_is_named_with_its_table(self):
        lines = self.report(rows("a", "b", "c"), rows("a", "c"))
        self.assertEqual(lines, ["names: row removed: b"])

    def test_added_rows_are_counted_not_listed(self):
        self.assertEqual(self.report(rows("a"), rows("a", "b", "c")), ["names: 2 rows added"])

    def test_a_base_without_the_table_makes_every_row_new_and_removes_none(self):
        self.assertEqual(
            self.report(None, rows("a", "b")), ["names: no table at the base; all 2 rows are new"]
        )

    def test_a_table_gone_from_the_head_names_each_row_removed(self):
        lines = self.report(rows("a", "b"), None)
        self.assertEqual(
            lines,
            [
                "names: the table is gone from the head",
                "names: row removed: a",
                "names: row removed: b",
            ],
        )

    def test_a_row_whose_content_changed_is_named_with_the_fields(self):
        base = [{"label": "a", "name": "x", "holdable": True, "gaps": {}}]
        head = [{"label": "a", "name": "y", "holdable": False, "gaps": {}}]
        self.assertEqual(self.report(base, head), ["names: row changed: a (holdable, name)"])

    def test_two_fields_that_swapped_values_are_a_changed_row_naming_both(self):
        base = [{"label": "a", "name": "x", "source": "y", "gaps": {}}]
        head = [{"label": "a", "name": "y", "source": "x", "gaps": {}}]
        self.assertEqual(self.report(base, head), ["names: row changed: a (name, source)"])

    def test_a_row_with_the_same_values_under_swapped_field_names_is_a_changed_row(self):
        base = [{"label": "a", "first": 1, "second": 2, "gaps": {}}]
        head = [{"label": "a", "first": 2, "second": 1, "gaps": {}}]
        self.assertEqual(self.report(base, head), ["names: row changed: a (first, second)"])

    def test_a_row_that_only_got_a_new_label_is_relabelled_not_removed_and_added(self):
        base = [{"label": "old", "name": "x", "holdable": True, "gaps": {}}]
        head = [{"label": "new", "name": "x", "holdable": True, "gaps": {}}]
        self.assertEqual(self.report(base, head), ["names: row relabelled: old \u2192 new"])

    def test_a_new_label_and_another_field_changed_is_removed_plus_added(self):
        base = [{"label": "old", "name": "x", "gaps": {}}]
        head = [{"label": "new", "name": "y", "gaps": {}}]
        self.assertEqual(
            self.report(base, head), ["names: row removed: old", "names: 1 rows added"]
        )

    def test_two_equal_rows_relabelled_are_matched_once_each(self):
        base = [{"label": "a", "name": "x", "gaps": {}}, {"label": "b", "name": "x", "gaps": {}}]
        head = [{"label": "c", "name": "x", "gaps": {}}]
        self.assertEqual(
            self.report(base, head), ["names: row relabelled: a \u2192 c", "names: row removed: b"]
        )

    def test_a_relabelled_row_keeps_its_mark_without_calling_it_new(self):
        base = rows("old", old={"m.f": "why"})
        head = rows("new", new={"m.f": "why"})
        self.assertEqual(
            self.both(base, head),
            (
                ["names: row relabelled: old \u2192 new"],
                ["names: known gap: new: m.f: why"],
            ),
        )

    def test_a_mark_added_is_a_change_and_every_mark_in_force_stands(self):
        base = rows("a", "b", b={"m.f": "old reason"})
        head = rows("a", "b", a={"m.g": "a new reason"}, b={"m.f": "old reason"})
        self.assertEqual(
            self.both(base, head),
            (
                ["names: new known gap: a: m.g: a new reason"],
                [
                    "names: known gap: a: m.g: a new reason",
                    "names: known gap: b: m.f: old reason",
                ],
            ),
        )

    def test_a_reason_that_changed_counts_as_new(self):
        base = rows("a", a={"m.f": "short"})
        head = rows("a", a={"m.f": "a longer reason"})
        self.assertEqual(self.report(base, head), ["names: new known gap: a: m.f: a longer reason"])

    def test_a_standing_mark_alone_is_no_change(self):
        both = rows("a", a={"m.f": "why"})
        self.assertEqual(self.both(both, both), ([], ["names: known gap: a: m.f: why"]))

    def test_nothing_to_say_is_no_lines(self):
        self.assertEqual(self.both(rows("a"), rows("a")), ([], []))
        self.assertEqual(guards.table_report({}, {}), ([], []))

    def test_a_table_that_could_not_be_read_is_said_so_and_does_not_hide_the_others(self):
        lines = guards.table_report(
            {"names": "SyntaxError: line 1", "imports": rows("x"), "suppressions": None},
            {"names": rows("a"), "imports": rows(), "suppressions": None},
        )[0]
        self.assertEqual(
            lines,
            [
                "names: the table at the base could not be read: SyntaxError: line 1",
                "imports: row removed: x",
            ],
        )

    def test_each_section_is_one_escaped_block_and_empty_for_no_lines(self):
        self.assertEqual(guards.render_tables([], []), "")
        text = guards.render_tables(["names: row removed: x\n```\n# injected"], [])
        fences = [line for line in text.splitlines() if line.startswith("`")]
        self.assertEqual(len(fences), 2)
        self.assertIn("x\\n", text)


class RenderTablesTest(unittest.TestCase):
    CHANGES = "## What this pull request does to the hostile-case tables"
    STANDING = "## Known gaps in the tables, as they stand"

    def rendered(self, base, head):
        return guards.render_tables(
            *guards.table_report(
                {"names": base, "imports": None, "suppressions": None},
                {"names": head, "imports": None, "suppressions": None},
            )
        )

    def test_a_pull_request_that_touches_no_table_prints_only_the_standing_marks(self):
        both = rows("a", a={"m.f": "why"})
        text = self.rendered(both, both)
        self.assertNotIn(self.CHANGES, text)
        self.assertIn(self.STANDING, text)
        self.assertIn("names: known gap: a: m.f: why", text)

    def test_a_pull_request_that_touches_no_table_and_no_mark_prints_nothing(self):
        self.assertEqual(self.rendered(rows("a"), rows("a")), "")

    def test_a_pull_request_that_adds_rows_prints_the_changes_heading(self):
        text = self.rendered(rows("a"), rows("a", "b"))
        self.assertIn(self.CHANGES, text)
        self.assertIn("names: 1 rows added", text)
        self.assertNotIn(self.STANDING, text)

    def test_a_pull_request_that_removes_a_row_prints_the_changes_heading(self):
        text = self.rendered(rows("a", "b"), rows("a"))
        self.assertIn(self.CHANGES, text)
        self.assertIn("names: row removed: b", text)

    def test_a_pull_request_that_adds_a_mark_prints_both_headings_changes_first(self):
        text = self.rendered(rows("a"), rows("a", a={"m.f": "why"}))
        self.assertIn("names: new known gap: a: m.f: why", text)
        self.assertIn("names: known gap: a: m.f: why", text)
        self.assertLess(text.index(self.CHANGES), text.index(self.STANDING))

    def test_a_standing_mark_is_not_listed_under_the_changes_heading(self):
        text = self.rendered(
            rows("a", "b", b={"m.f": "why"}), rows("a", "b", "c", b={"m.f": "why"})
        )
        changes, _, standing = text.partition(self.STANDING)
        self.assertNotIn("known gap", changes)
        self.assertIn("names: known gap: b: m.f: why", standing)


class RenderSummaryTest(unittest.TestCase):
    def body(self, text):
        """The lines between the opening and closing fence."""
        lines = text.splitlines()
        fence = next(line for line in lines if line.startswith("`"))
        self.assertEqual(lines.count(fence), 2, text)
        first = lines.index(fence)
        return fence, lines[first + 1 : lines.index(fence, first + 1)]

    def test_nothing_changed_is_one_line(self):
        self.assertEqual(guards.render_summary([]), guards.NONE_CHANGED + "\n")

    def test_one_line_per_file_under_a_heading_about_the_guardrails(self):
        text = guards.render_summary([("changed", "pyproject.toml"), ("deleted", "checks/a.sh")])
        self.assertTrue(text.startswith("## This pull request changes the guardrails\n"))
        self.assertIn("reviewer should read these files", text)
        _, lines = self.body(text)
        self.assertEqual([line.split()[0] for line in lines], ["changed", "deleted"])
        self.assertTrue(lines[0].endswith("pyproject.toml") and lines[1].endswith("checks/a.sh"))

    def test_awkward_names_each_take_one_line_inside_the_block_unaltered(self):
        text = guards.render_summary([("changed", "checks/" + n) for n in AWKWARD])
        _, lines = self.body(text)
        self.assertEqual(len(lines), len(AWKWARD))
        for line, name in zip(lines, AWKWARD, strict=True):
            self.assertTrue(line.endswith(names.escape_name("checks/" + name)), line)

    def test_no_name_can_close_the_block_or_start_markup(self):
        hostile = ["x\n```\n# heading\n<script>", "```", "``````````", "a\n~~~\n"]
        text = guards.render_summary([("changed", "checks/" + n) for n in hostile])
        fence, lines = self.body(text)
        self.assertGreater(len(fence), 10)
        self.assertEqual(len(lines), len(hostile))
        self.assertFalse([line for line in lines if line.startswith(fence)])
        self.assertTrue(all(line.split(" ")[0] in ("changed",) for line in lines))


class FixModeDecisionsTest(unittest.TestCase):
    def test_changed_files_are_those_whose_content_hash_differs_by_exact_path(self):
        before = {"my file.py": "1", "a.py": "2", "gone.py": "3", "same.py": "4"}
        after = {"my file.py": "9", "a.py": "2", "new.py": "5", "same.py": "4"}
        self.assertEqual(fixmode.changed_files(before, after), ["gone.py", "my file.py", "new.py"])

    def test_failed_files_are_io_errors_and_syntax_errors_not_lint_findings(self):
        diagnostics = [
            {"code": "E902", "filename": "/r/ro.py"},
            {"code": "invalid-syntax", "filename": "/r/bad.py"},
            {"code": None, "filename": "/r/other.py"},
            {"code": "F841", "filename": "/r/lint.py"},
        ]
        self.assertEqual(
            fixmode.failed_from_diagnostics(diagnostics, "/r"), ["bad.py", "other.py", "ro.py"]
        )

    def test_the_formatters_failed_files_are_matched_whole_against_known_paths(self):
        output = "error: Failed to write my file.py: Permission denied (os error 13)\n"
        output += "error: Failed to parse bad.py:1:7: Expected\n"
        known = ["my file.py", "my", "bad.py", "fine.py"]
        self.assertEqual(fixmode.failed_from_format_output(output, known), ["bad.py", "my file.py"])

    def test_remaining_lint_findings_are_one_line_each(self):
        d = {
            "code": "F841",
            "filename": "/r/a b.py",
            "location": {"row": 3},
            "message": "Unused\n  more",
        }
        self.assertEqual(fixmode.remaining_findings([d], "/r"), ["a b.py:3: F841 Unused"])

    def test_odd_ruff_json_is_refused_not_misread(self):
        for text in (
            '{"a": 1}',
            "null",
            "[null]",
            '[{"code": "F401"}]',
            '[{"filename": 3}]',
            '[{"filename": "a.py", "code": 5}]',
            "not json",
            "",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                fixmode.parse_diagnostics(text)

    def test_a_sparse_but_valid_diagnostic_is_accepted_and_described(self):
        found = fixmode.parse_diagnostics('[{"filename": "/r/a.py", "code": "F401"}]')
        self.assertEqual(fixmode.remaining_findings(found, "/r"), ["a.py:?: F401 "])
        self.assertEqual(fixmode.parse_diagnostics("[]"), [])

    def test_a_link_is_hashed_under_its_own_path_unless_its_target_is_already_hashed(self):
        links = {
            "/r/in.py": "/r/real.py",
            "/r/out.py": "/elsewhere/o.py",
            "/r/b.py": "/r/.git/x.py",
        }
        self.assertEqual(fixmode.links_to_hash({"/r/real.py"}, links), ["/r/b.py", "/r/out.py"])
        self.assertEqual(fixmode.links_to_hash({"/r/real.py"}, {}), [])

    def test_links_that_end_at_one_file_count_once(self):
        links = {"/r/l2.py": "/o/x.py", "/r/l1.py": "/o/x.py", "/r/other.py": "/o/y.py"}
        self.assertEqual(fixmode.links_to_hash(set(), links), ["/r/l1.py", "/r/other.py"])

    def test_pycache_is_not_skipped_because_ruff_does_not_skip_it(self):
        self.assertNotIn("__pycache__", fixmode.SKIPPED_FOLDERS)
        self.assertEqual(set(fixmode.SKIPPED_FOLDERS), {".git", ".ruff_cache", ".mypy_cache"})

    def test_nothing_changed_says_so(self):
        self.assertEqual(fixmode.render_lines([], [], False), ["fix: nothing to change"])

    def test_the_count_is_the_number_of_files_and_names_stay_whole(self):
        self.assertEqual(
            fixmode.render_lines(["my file.py", "b.py"], [], False),
            [
                "changed: my file.py",
                "changed: b.py",
                "fix: changed 2 files; now run ./checks/all.sh",
            ],
        )
        self.assertEqual(
            fixmode.render_lines(["a\nb.py"], [], False),
            ["changed: a\\nb.py", "fix: changed 1 file; now run ./checks/all.sh"],
        )

    def test_a_failure_still_lists_what_changed_then_names_the_failed_files(self):
        self.assertEqual(
            fixmode.render_lines(["ok.py"], ["ro.py"], False),
            [
                "changed: ok.py",
                "failed: ro.py",
                "fix: failed; ruff could not finish (its output is on standard error)",
            ],
        )

    def test_a_failure_with_no_file_named_never_says_nothing_to_change(self):
        lines = fixmode.render_lines([], [], True)
        self.assertEqual(
            lines, ["fix: failed; ruff could not finish (its output is on standard error)"]
        )


if __name__ == "__main__":
    unittest.main()
