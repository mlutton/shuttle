"""Every function in checks/ that takes a file name, run against every row of the names table.

The table (tests/hostile/names_table.py) holds the file names that broke careless code in
review: a space, a newline, a backtick, bytes that are not UTF-8, look-alikes of the guard
folders. Each test here loops the whole table through one function and asserts that
function's invariant, stated in the test's name. A function that fails a row has a finding;
a row the function is known to fail carries a mark in the table (`gaps`) and the test then
asserts that the invariant still fails there, so a mark cannot go stale.

A new function that takes a name has to appear here: tests/by_value/test_name_functions.py
fails until it is registered in tests/hostile/registry.py. Tests that touch the filesystem use
temporary folders they make, create what the filesystem will hold, and say on standard error
how many rows it refused and why.
"""

import hashlib
import importlib
import io
import itertools
import os
import re
import sys
import tempfile
import tomllib
import unittest
import unittest.mock

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TESTS)
sys.path.insert(0, os.path.join(ROOT, "checks"))
sys.path.insert(0, TESTS)

names = importlib.import_module("names")
guards = importlib.import_module("guards")
fixmode = importlib.import_module("fixmode")
report = importlib.import_module("report")
table = importlib.import_module("hostile.names_table")
registry = importlib.import_module("hostile.registry")
support = importlib.import_module("hostile.support")
unsafe, one_line = support.unsafe, support.one_line

ROWS = table.NAMES
NO_NUL = [row for row in ROWS if "\0" not in row["name"]]
HOLDABLE = [row for row in ROWS if row["holdable"]]
GUARD_FOLDERS = ("checks", ".githooks", ".github")
CLOSING_FENCE = r" {0,3}`{%d,}[ \t]*"


def beneath(folder, row):
    """A row as a path under a folder: rows that are paths already stay as they are."""
    return row["name"] if row["path"] else f"{folder}/{row['name']}"


class RowsTest(unittest.TestCase):
    def each(self, key, rows, check):
        """Run check(row) over rows; it returns None or what went wrong. A row marked as a
        known gap for key must go wrong, and any other must not."""
        for row in rows:
            with self.subTest(label=row["label"]):
                problem = check(row)
                gap = row.get("gaps", {}).get(key)
                if gap:
                    self.assertTrue(problem, f"{key} no longer fails this row: remove the mark")
                else:
                    self.assertIsNone(problem)


class TheTablesTest(unittest.TestCase):
    def test_every_row_has_a_label_a_distinct_name_and_says_whether_a_filesystem_holds_it(self):
        labels = [row["label"] for row in ROWS]
        self.assertEqual(len(labels), len(set(labels)), "two rows share a label")
        found = [row["name"] for row in ROWS]
        self.assertEqual(len(found), len(set(found)), "two rows share a name")
        for row in ROWS:
            with self.subTest(label=row["label"]):
                self.assertIsInstance(row["name"], str)
                self.assertIsInstance(row["holdable"], bool)
                self.assertIsInstance(row["path"], bool)
                self.assertEqual(row["path"], "/" in row["name"])
                if not row["holdable"]:
                    self.assertTrue(row.get("why_not"), "a name no filesystem holds says why")
                for key in row.get("gaps", {}):
                    self.assertRegex(key, r"^\w+\.\w+$")

    def test_a_known_gap_names_a_registered_function_and_says_why_in_words(self):
        # without this a one-character reason could excuse a failing row
        for row in ROWS:
            for key, reason in row.get("gaps", {}).items():
                with self.subTest(label=row["label"], key=key):
                    self.assertIn(key, registry.TABLE_TESTED, "a mark on a function nobody tests")
                    self.assertIn(key.split(".")[1], reason, "the reason names the function")
                    self.assertGreaterEqual(len(reason.split()), 12, "say why, in a sentence")

    def test_a_row_this_filesystem_refuses_is_reported_short_and_the_others_are_made(self):
        rows = [
            {"label": "fine", "name": "ok.py", "path": False, "holdable": True},
            {"label": "refused", "name": "x\0y.py", "path": False, "holdable": True},
            {"label": "known", "name": "k.py", "path": False, "holdable": True},
            {"label": "never", "name": "n.py", "path": False, "holdable": False, "why_not": "w"},
        ]
        with tempfile.TemporaryDirectory() as root:
            made, unexpected = support.create_all(root, rows, skip={"known": "a tool refuses it"})
        self.assertEqual(list(made), ["ok.py"])
        self.assertEqual(unexpected, [("refused", "ValueError")])
        note = support.unmade_note(unexpected)
        self.assertLess(len(note), 120)
        self.assertIn("refused", note)

    def test_the_table_has_the_names_the_reviews_found(self):
        wanted = [" ", "\t", "\n", "\r", "`" * 6, "-", "#", "    ", "|", "<", ">", "\\n", "'", '"']
        wanted += ["$(", ";", "*", "é", "‮", " ", "\x0c", "\x85", "\udcff"]
        wanted += ["checks2/x", ".githubx/y", "Checks/x"]
        every = "".join(row["name"] for row in ROWS)
        for piece in wanted:
            with self.subTest(piece=piece):
                self.assertIn(piece, every)
        self.assertTrue(any(len(row["name"]) > 255 for row in ROWS))
        self.assertTrue(any(not row["holdable"] for row in ROWS))


class EscapeNameTest(RowsTest):
    def test_escape_name_renders_every_name_as_one_line_with_no_control_or_direction_character(
        self,
    ):
        def check(row):
            shown = names.escape_name(row["name"])
            if not one_line(shown):
                return f"not one safe line: {shown!r}"
            shown.encode("utf-8")  # no surrogate is left to crash a print
            if row["name"].isascii() and row["name"].isprintable() and "\\" not in row["name"]:
                return None if shown == row["name"] else f"changed a plain name: {shown!r}"
            return None

        self.each("names.escape_name", NO_NUL, check)

    def test_escape_name_never_renders_two_different_names_the_same(self):
        shown = {}
        for row in NO_NUL:
            shown.setdefault(names.escape_name(row["name"]), []).append(row["label"])
        clashes = {text: labels for text, labels in shown.items() if len(labels) > 1}
        self.assertEqual(clashes, {})

    def test_escape_name_tells_a_byte_that_is_not_utf8_from_the_character_with_the_same_value(self):
        invalid = os.fsdecode(b"x\x85y")
        valid = "x\x85y"
        self.assertNotEqual(invalid, valid)
        self.assertNotEqual(names.escape_name(invalid), names.escape_name(valid))


class FencedTest(unittest.TestCase):
    def check_block(self, lines):
        block = names.fenced(lines)
        parts = block.split("\n")
        self.assertEqual(parts[-1], "", "the block ends with a newline")
        fence, body = parts[0], parts[1:-2]
        self.assertRegex(fence, r"^`{3,}$")
        self.assertEqual(parts[-2], fence)
        self.assertEqual(body, lines)
        longest = max((len(run) for line in lines for run in re.findall("`+", line)), default=0)
        self.assertGreater(len(fence), longest)
        closers = [p for p in parts[:-1] if re.fullmatch(CLOSING_FENCE % len(fence), p)]
        self.assertEqual(len(closers), 2, "exactly the opening and the closing fence")

    def test_fenced_gives_exactly_two_fence_lines_for_any_subset_of_the_names(self):
        shown = [names.escape_name(row["name"]) for row in NO_NUL]
        self.check_block(shown)
        self.check_block(list(reversed(shown)))
        for line in shown:
            self.check_block([line])
        for pair in itertools.combinations_with_replacement(shown, 2):
            self.check_block(list(pair))

    def test_fenced_keeps_a_name_that_is_a_fence_or_starts_markup_inside_the_block(self):
        for row in NO_NUL:
            with self.subTest(label=row["label"]):
                self.check_block(["added   " + names.escape_name(row["name"])])
                self.check_block([names.escape_name(row["name"])])


class GitOutputTest(RowsTest):
    def test_parse_name_status_returns_every_name_whole_in_order_for_any_name_git_can_carry(self):
        statuses = itertools.cycle("AMDT")
        pairs = [(next(statuses), row["name"]) for row in HOLDABLE]
        raw = b"".join(s.encode() + b"\0" + os.fsencode(n) + b"\0" for s, n in pairs)
        self.assertEqual(guards.parse_name_status(raw), pairs)

        def check(row):
            one = f"M\0{row['name']}\0".encode("utf-8", "surrogateescape")
            got = guards.parse_name_status(one)
            return None if got == [("M", row["name"])] else f"got {got!r}"

        self.each("guards.parse_name_status", HOLDABLE, check)


class GuardDecisionTest(RowsTest):
    """Over the rows a git repository can hold: git never reports an empty path component."""

    def test_is_guard_is_true_for_any_name_in_a_guard_folder_and_false_for_a_look_alike(self):
        def check(row):
            if not row["path"]:
                for folder in GUARD_FOLDERS:
                    if not guards.is_guard(f"{folder}/{row['name']}"):
                        return f"{folder}/ + the name is not a guard"
            elif guards.is_guard(row["name"]):
                return "a look-alike is a guard"
            if guards.is_guard(row["name"]):
                return "the name on its own is a guard"
            return None

        self.each("guards.is_guard", HOLDABLE, check)

    def test_is_guard_is_true_for_each_guard_file_and_false_for_a_name_joined_to_one(self):
        for guard in guards.GUARD_FILES:
            self.assertTrue(guards.is_guard(guard))
            for row in HOLDABLE:
                with self.subTest(guard=guard, label=row["label"]):
                    self.assertFalse(guards.is_guard(guard + row["name"]))
                    self.assertFalse(guards.is_guard(f"sub/{guard}"))

    def test_guard_changes_lists_each_guard_name_once_and_whole_and_no_look_alike(self):
        inputs = [("M", beneath("checks", row)) for row in HOLDABLE]
        expected = sorted(beneath("checks", row) for row in HOLDABLE if not row["path"])
        got = guards.guard_changes(inputs)
        self.assertEqual([path for _, path in got], expected)
        self.assertEqual({what for what, _ in got}, {"changed"})
        self.assertEqual(guards.guard_changes(list(reversed(inputs))), got)

        def check(row):
            one = guards.guard_changes([("A", beneath("checks", row))])
            want = [] if row["path"] else [("added", beneath("checks", row))]
            return None if one == want else f"got {one!r}"

        self.each("guards.guard_changes", HOLDABLE, check)

    def test_render_summary_lists_each_name_on_one_line_inside_one_block_of_two_fences(self):
        changes = [("D", beneath("checks", row)) for row in HOLDABLE if not row["path"]]
        text = guards.render_summary(guards.guard_changes(changes))
        lines = text.split("\n")
        fences = [i for i, line in enumerate(lines) if re.fullmatch(r"`{3,}", line)]
        # a name that is only backticks is a line of the block; the fence is the longer one
        fence = lines[fences[0]]
        closers = [i for i, line in enumerate(lines) if line == fence]
        self.assertEqual(len(closers), 2, text)
        body = lines[closers[0] + 1 : closers[1]]
        sorted_paths = sorted(path for _, path in changes)
        self.assertEqual(body, [f"{'deleted':<8}{names.escape_name(p)}" for p in sorted_paths])
        for line in body:
            self.assertTrue(one_line(line), line)
        self.assertFalse([line for line in lines if unsafe(line)])
        self.assertEqual(len(set(body)), len(body), "two names rendered the same")

        def check(row):
            one = guards.render_summary([("changed", beneath("checks", row))])
            parts = one.split("\n")
            fence = parts[parts.index(next(p for p in parts if p.startswith("`")))]
            if parts.count(fence) != 2 or any(unsafe(p) for p in parts):
                return f"fences or controls: {one!r}"
            return None

        self.each("guards.render_summary", HOLDABLE, check)


class FixModeTest(RowsTest):
    def test_changed_files_lists_each_changed_name_once_whole_and_in_order(self):
        every = [row["name"] for row in NO_NUL]
        before = dict.fromkeys(every, "1")
        after = {name: "2" if i % 2 else "1" for i, name in enumerate(every)}
        self.assertEqual(
            fixmode.changed_files(before, after),
            sorted(name for i, name in enumerate(every) if i % 2),
        )

        def check(row):
            name = row["name"]
            got = (
                fixmode.changed_files({name: "1"}, {name: "2"}),
                fixmode.changed_files({name: "1"}, {name: "1"}),
                fixmode.changed_files({name: "1"}, {}),
                fixmode.changed_files({}, {name: "1"}),
            )
            return None if got == ([name], [], [name], [name]) else f"got {got!r}"

        self.each("fixmode.changed_files", NO_NUL, check)

    def test_render_lines_gives_each_name_one_line_and_counts_the_files(self):
        every = [row["name"] for row in NO_NUL]
        lines = fixmode.render_lines(every, [], False)
        self.assertEqual(len(lines), len(every) + 1)
        self.assertEqual(lines[:-1], [f"changed: {names.escape_name(n)}" for n in every])
        self.assertEqual(lines[-1], f"fix: changed {len(every)} files; now run ./checks/all.sh")
        failing = fixmode.render_lines(every[:3], every[3:], False)
        self.assertEqual(failing[3:-1], [f"failed: {names.escape_name(n)}" for n in every[3:]])
        self.assertEqual(len(set(lines)), len(lines), "two names rendered the same")
        self.assertFalse([line for line in lines + failing if not one_line(line)])

        def check(row):
            one = fixmode.render_lines([row["name"]], [], False)
            want = [
                f"changed: {names.escape_name(row['name'])}",
                "fix: changed 1 file; now run ./checks/all.sh",
            ]
            return None if one == want and all(one_line(x) for x in one) else f"got {one!r}"

        self.each("fixmode.render_lines", NO_NUL, check)

    def test_failed_from_diagnostics_gives_each_name_relative_to_the_root_once_and_whole(self):
        rows = [row for row in HOLDABLE]

        def diag(row):
            return {"code": "E902", "filename": "/r/" + row["name"]}

        got = fixmode.failed_from_diagnostics([diag(row) for row in rows], "/r")
        self.assertEqual(got, sorted(row["name"] for row in rows))

        def check(row):
            one = fixmode.failed_from_diagnostics([diag(row), diag(row)], "/r")
            return None if one == [row["name"]] else f"got {one!r}"

        self.each("fixmode.failed_from_diagnostics", rows, check)

    def test_failed_from_format_output_names_only_the_files_the_formatter_named(self):
        known = [row["name"] for row in HOLDABLE]

        def check(row):
            output = f"error: Failed to write {row['name']}: Permission denied (os error 13)\n"
            got = fixmode.failed_from_format_output(output, known)
            return None if got == [row["name"]] else f"got {got!r}"

        self.each("fixmode.failed_from_format_output", HOLDABLE, check)

    def test_remaining_findings_gives_each_name_on_one_line_and_no_two_alike(self):
        def diag(row):
            return {
                "code": "F841",
                "filename": "/r/" + row["name"],
                "location": {"row": 3},
                "message": "m",
            }

        rows = HOLDABLE
        lines = fixmode.remaining_findings([diag(row) for row in rows], "/r")
        self.assertEqual(lines, [f"{names.escape_name(row['name'])}:3: F841 m" for row in rows])
        self.assertEqual(len(set(lines)), len(lines), "two names rendered the same")

        def check(row):
            (one,) = fixmode.remaining_findings([diag(row)], "/r")
            return None if one_line(one) else f"not one line: {one!r}"

        self.each("fixmode.remaining_findings", rows, check)

    def test_a_message_carrying_a_name_is_shown_as_one_line_too(self):
        for row in HOLDABLE:
            with self.subTest(label=row["label"]):
                found = {"code": "F841", "filename": "/r/a.py", "message": row["name"]}
                (line,) = fixmode.remaining_findings([found], "/r")
                self.assertTrue(one_line(line), line)

    def test_links_to_hash_returns_each_link_once_whole_and_counts_links_to_one_file_once(self):
        rows = HOLDABLE
        links = {"/r/" + row["name"]: "/out/" + row["name"] for row in rows}
        self.assertEqual(fixmode.links_to_hash(set(), links), sorted(links))
        half = {t for i, t in enumerate(sorted(links.values())) if i % 2}
        got = fixmode.links_to_hash(half, links)
        self.assertEqual(got, sorted(k for k, t in links.items() if t not in half))
        same = dict.fromkeys(links, "/out/one")
        self.assertEqual(fixmode.links_to_hash(set(), same), [min(links)])

        def check(row):
            one = {"/r/" + row["name"]: "/out/x"}
            ok = fixmode.links_to_hash(set(), one) == list(one)
            return None if ok and fixmode.links_to_hash({"/out/x"}, one) == [] else "wrong"

        self.each("fixmode.links_to_hash", rows, check)

    def test_is_bytecode_is_true_only_for_a_pyc_file_in_a_folder_named_exactly_pycache(self):
        def check(row):
            name = row["name"]
            if not fixmode.is_bytecode(f"/r/{name}/__pycache__", "m.pyc"):
                return "a real __pycache__ under this name is not one"
            if fixmode.is_bytecode(f"/r/__pycache__/{name}", "m.pyc") and not name.endswith(
                "__pycache__"
            ):
                return "a folder under __pycache__ is one"
            if fixmode.is_bytecode(f"/r/{name}", "m.pyc") and not name.endswith("/__pycache__"):
                return "a folder with this name is __pycache__"
            if fixmode.is_bytecode("/r/__pycache__", name) != name.endswith(".pyc"):
                return "the file name's suffix decides, and only it"
            return None

        self.each("fixmode.is_bytecode", NO_NUL, check)
        self.assertFalse(fixmode.is_bytecode("/r/p__pycache__q", "m.pyc"))
        self.assertFalse(fixmode.is_bytecode("/r/__pycache__x", "m.pyc"))


class TheFilesystemTest(unittest.TestCase):
    """Functions that read a folder: a temporary one holds every name this filesystem will."""

    def make(self, root, rows=None, **kwargs):
        """The files made for the rows. A row this filesystem refuses although the table says
        it can hold it is reported as a skipped sub-test, with one short reason."""
        made, unexpected = support.create_all(root, rows or HOLDABLE, **kwargs)
        if unexpected:
            with self.subTest("some names are refused here"):
                self.skipTest(support.unmade_note(unexpected))
        self.assertTrue(made)
        return made

    def test_snapshot_hashes_each_file_under_its_own_whole_path_once(self):
        with tempfile.TemporaryDirectory() as root:
            made = self.make(root, make=lambda n: n)
            shot = fixmode.snapshot(root)
            self.assertEqual(sorted(shot), sorted(made.values()))
            for rel in made.values():
                with open(os.path.join(root, rel), "rb") as f:
                    self.assertEqual(shot[rel], hashlib.sha256(f.read()).hexdigest())
            entries = fixmode.tree_entries(root)
            relative = [os.path.relpath(p, root) for p in entries]
            self.assertEqual(sorted(relative), sorted(made.values()))
            self.assertEqual(len(set(entries)), len(entries))
            for rel in made.values():
                self.assertIsNotNone(fixmode.file_hash(os.path.join(root, rel)))

    def test_file_hash_of_a_name_that_is_not_there_is_none_not_an_error(self):
        with tempfile.TemporaryDirectory() as root:
            for row in HOLDABLE:
                with self.subTest(label=row["label"]):
                    path = os.path.join(root, "absent", row["name"])
                    self.assertIsNone(fixmode.file_hash(path))

    def test_walked_files_lists_each_python_file_once_whole_with_slashes_in_order(self):
        with tempfile.TemporaryDirectory() as root:
            made = self.make(root)
            walked = report.walked_files(root, ["names"])
            self.assertEqual(walked, sorted(made.values()))
            self.assertEqual(len(set(walked)), len(walked))

    def test_source_markers_gives_each_marker_and_problem_with_the_file_s_whole_name(self):
        with tempfile.TemporaryDirectory() as root:
            made = self.make(root)
            paths = sorted(made.values())
            markers, problems = report.source_markers(root, paths)
            self.assertEqual(problems, [])
            self.assertEqual([m.path for m in markers], paths)
            self.assertEqual({m.line for m in markers}, {1})
            self.assertEqual({m.reason for m in markers}, {"why"})

    def test_source_markers_names_a_file_it_cannot_read_whole(self):
        with tempfile.TemporaryDirectory() as root:
            made = self.make(root, content="")
            for rel in made.values():
                with open(os.path.join(root, rel), "wb") as f:
                    f.write(b"\xff\xfe\x00 not utf-8\n")
            paths = sorted(made.values())
            _, problems = report.source_markers(root, paths)
            self.assertEqual(len(problems), len(paths))
            for path, problem in zip(paths, problems, strict=True):
                self.assertTrue(problem.startswith(path + ": "), problem)

    def test_analyse_unmeasured_gives_each_file_under_its_whole_path(self):
        with tempfile.TemporaryDirectory() as root:
            made = self.make(root, content="x = 1\n")
            rc = os.path.join(root, "coverage.toml")
            with open(rc, "w", encoding="utf-8") as f:
                f.write(f"[tool.coverage.run]\ndata_file = {str(os.path.join(root, 'd'))!r}\n")
            paths = sorted(made.values())
            got = report.analyse_unmeasured(rc, root, paths)
            self.assertEqual(sorted(got), paths)
            for path in paths:
                self.assertEqual(got[path].path, path)
                self.assertEqual(got[path].statements, 1)
                self.assertEqual(got[path].missing, (1,))


class ReportTest(RowsTest):
    def test_find_markers_names_the_file_whole_in_each_marker_and_problem(self):
        def check(row):
            path = row["name"]
            found, problems = report.find_markers(path, "x = 1  # not tested: why\n")
            if (found, problems) != ([report.Marker(path, 1, "why")], []):
                return f"marker: {found!r} {problems!r}"
            found, problems = report.find_markers(path, "x = 1  # not tested:\n")
            if found or len(problems) != 1 or not problems[0].startswith(f"{path} line 1"):
                return f"problem: {problems!r}"
            return None

        self.each("report.find_markers", NO_NUL, check)

    def test_normalize_coverage_gives_each_file_under_its_whole_path_relative_to_the_root(self):
        def entry():
            return {"summary": {"num_statements": 2}, "missing_lines": [], "excluded_lines": []}

        rows = HOLDABLE
        data = {"files": {"/r/" + row["name"]: entry() for row in rows}}
        got = report.normalize_coverage(data, "/r")
        self.assertEqual([f.path for f in got], sorted(row["name"] for row in rows))

        def check(row):
            one = report.normalize_coverage({"files": {"/r/" + row["name"]: entry()}}, "/r")
            return None if [f.path for f in one] == [row["name"]] else f"got {one!r}"

        self.each("report.normalize_coverage", rows, check)

    def test_merge_rows_gives_one_row_for_each_walked_name_whole_and_in_order(self):
        every = [row["name"] for row in NO_NUL]
        rows = report.merge_rows(every + every[:5], [], {})
        self.assertEqual([r.path for r in rows], sorted(every))
        have = [report.FileCoverage(n, 3, (), ()) for n in every[::2]]
        rows = report.merge_rows(every, have, {})
        self.assertEqual([r.path for r in rows], sorted(every))
        self.assertEqual(sum(r.statements == 3 for r in rows), len(have))

    def test_render_coverage_gives_each_file_one_line_and_no_two_alike(self):
        files = tuple(report.FileCoverage(row["name"], 4, (1,), ()) for row in NO_NUL)
        lines = report.render_coverage(files)
        self.assertEqual(len(lines), len(files) + 2)  # the header and the total
        for line in lines:
            self.assertTrue(one_line(line), line)
        for line, file in zip(lines[1:-1], files, strict=True):
            self.assertTrue(line.startswith(names.escape_name(file.path)), line)
        self.assertEqual(len(set(lines)), len(lines))

    def test_failure_line_is_one_line_with_no_control_character_whatever_the_reason(self):
        def check(row):
            line = report.failure_line(row["name"])
            ok = one_line(line) and line.startswith(report.COULD_NOT)
            return None if ok else f"got {line!r}"

        self.each("report.failure_line", NO_NUL, check)

    def facts(self, labels):
        files = tuple(report.FileCoverage(n, 1, (1,), ()) for n in labels)
        markers = tuple(report.Marker(n, 7, n) for n in labels)
        # a test id's first dotted part is a folder, which the report prints
        tests = tuple(report.TestRecord(f"{n}.test_x", 0.5, "skipped", n) for n in labels)
        return report.Facts(
            commit="abc123",
            command=report.COMMAND,
            python="3.12.1",
            coverage="7.13.0",
            tests=tests,
            total_seconds=1.0,
            was_successful=False,
            peak_self_kib=1,
            peak_children_kib=1,
            files=files,
            markers=markers,
            failures=tuple(f"{n} (failed)" for n in labels),
            marker_problems=tuple(f"{n}: a problem" for n in labels),
        )

    @staticmethod
    def outside(markdown):
        """The lines outside fenced blocks, and the number of fences."""
        outside, fence, fences = [], None, 0
        for line in markdown.split("\n"):
            if fence is None and re.fullmatch(r"`{3,}", line):
                fence, fences = line, fences + 1
            elif fence is not None and line == fence:
                fence = None
            elif fence is None:
                outside.append(line)
        assert fence is None, "a fence was never closed"
        return outside, fences

    def test_render_report_keeps_every_name_inside_a_fenced_block_and_escaped(self):
        every = [row["name"] for row in NO_NUL]
        hostile = report.render_report(self.facts(every))
        benign = report.render_report(self.facts([f"f{i}" for i in range(len(every))]))
        self.assertEqual(self.outside(hostile), self.outside(benign))
        self.assertFalse([line for line in hostile.split("\n") if unsafe(line)])

        def check(row):
            text = report.render_report(self.facts([row["name"]]))
            same = self.outside(text) == self.outside(report.render_report(self.facts(["f"])))
            return None if same and not any(unsafe(x) for x in text.split("\n")) else "outside"

        self.each("report.render_report", NO_NUL, check)

    def test_coverage_config_keeps_a_root_and_a_data_file_whole_in_the_toml_file(self):
        pyproject = {"tool": {"coverage": {"run": {"source": ["shuttle"], "branch": True}}}}
        with tempfile.TemporaryDirectory() as folder:
            config = os.path.join(folder, "coverage.toml")

            def check(row):
                name = row["name"]
                text = report.coverage_config(pyproject, "/r/" + name, "/d/" + name)
                try:  # the file the report writes, as it writes it
                    with open(config, "w", encoding="utf-8") as f:
                        f.write(text)
                    with open(config, "rb") as f:
                        run = tomllib.load(f)["tool"]["coverage"]["run"]
                except (UnicodeEncodeError, tomllib.TOMLDecodeError) as error:
                    return f"not a TOML file: {error}"
                same = run["source"] == [os.path.join("/r/" + name, "shuttle")]
                return None if same and run["data_file"] == "/d/" + name else f"changed: {run!r}"

            self.each("report.coverage_config", NO_NUL, check)

    def test_a_report_that_cannot_write_its_settings_ends_in_one_failure_line_and_exit_1(self):
        # the truth the coverage_config gap rests on: the write raises, main says so once
        error = UnicodeEncodeError("utf-8", "\udcff", 0, 1, "surrogates not allowed")
        out = io.StringIO()
        with (
            unittest.mock.patch.object(report, "run", side_effect=error),
            unittest.mock.patch.object(sys, "stdout", out),
            unittest.mock.patch.object(sys, "stderr", io.StringIO()),
        ):
            code = report.main()
        self.assertEqual(code, 1)
        (line,) = out.getvalue().splitlines()
        self.assertTrue(line.startswith(report.COULD_NOT))
        with self.assertRaises(UnicodeEncodeError):
            "/r/\udcff".encode()


if __name__ == "__main__":
    unittest.main()
