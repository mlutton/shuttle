"""The decisions inside the check's helper scripts (checks/*.py), as functions over plain data."""

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
        ]
        self.assertEqual(self.guards_in(*paths), sorted(paths))

    def test_lookalikes_are_not_guard_files(self):
        self.assertEqual(
            self.guards_in(
                ".githubx/w.yml", "checks2/a.sh", "docs/pyproject.toml", "checks.md", "old.toml"
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
