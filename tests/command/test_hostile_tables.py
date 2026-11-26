"""The hostile-case tables against the real tools: three runs, no more.

- One ruff run over a tree with one core file per row of the imports table: the "which guard"
  column is checked against the real banned-import rule, so a row can neither be refused by
  nothing nor be listed as lint's when it is not.
- One ruff run over a tree with one core file per lint-ignore spelling: the "honoured" column is
  checked against the pinned ruff, and every spelling ruff honours must be refused by the rule
  test. An upgrade of ruff that starts honouring a new spelling fails here, not in review.
- One run of checks/guard-files.sh in a temporary git repository holding every file name the
  filesystem will hold as a changed guard file (real git, no ruff).

The names table against fix mode (the real ruff) is part of test_fix_mode.py's one-tree test.
The by-value tests (tests/by_value/) loop the same tables through the functions themselves.
"""

import collections
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(TESTS)
sys.path.insert(0, TESTS)
sys.path.insert(0, os.path.join(REPO, "checks"))

imports_table = importlib.import_module("hostile.imports_table")
suppressions_table = importlib.import_module("hostile.suppressions_table")
names_table = importlib.import_module("hostile.names_table")
support = importlib.import_module("hostile.support")
names = importlib.import_module("names")
check_module = importlib.import_module("by_value.test_rules").check_module

BANNED_IMPORT_RULE = "TID251"
GIT_ENV = {
    "PATH": os.environ["PATH"],
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "HOME": os.devnull,
}


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def read_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def banned_import_findings(tree):
    """Run the pinned ruff once over shuttle/ in the tree: the set of files (relative to
    shuttle/) with a banned-import finding. Anything but a finding-or-none result is an error."""
    done = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", "--output-format", "json", "shuttle"],
        cwd=tree,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if done.returncode not in (0, 1):
        raise AssertionError(f"ruff could not run (exit {done.returncode}): {done.stderr}")
    found = json.loads(done.stdout)
    return {
        os.path.relpath(d["filename"], os.path.join(tree, "shuttle"))
        for d in found
        if d["code"] == BANNED_IMPORT_RULE
    }


class TreeTest(unittest.TestCase):
    def tree(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        shutil.copy(os.path.join(REPO, "pyproject.toml"), folder.name)
        return folder.name


class ImportsLintColumnTest(TreeTest):
    def test_the_which_guard_column_agrees_with_the_real_linter_and_every_refusal_is_caught(self):
        tree = self.tree()
        places = []
        for index, (_, source, folder, *_) in enumerate(imports_table.IMPORTS):
            place = folder if folder.endswith(".py") else f"{folder}/row_{index:03d}.py"
            places.append(place)
            write(tree, f"shuttle/{place}", source + "\n")
        for where, _, files in list(os.walk(os.path.join(tree, "shuttle"))):
            if not os.path.basename(where).startswith("noinit") and "__init__.py" not in files:
                write(where, "__init__.py", "")
        write(tree, "shuttle/__main__.py", "")
        flagged = banned_import_findings(tree)

        wrong = []
        for place, (label, source, _, caught_by, note, _) in zip(
            places, imports_table.IMPORTS, strict=True
        ):
            lint = place in flagged
            rule = bool(check_module(source, place))
            if lint != (caught_by in ("both", "lint")) or rule != (
                caught_by in ("both", "rule test")
            ):
                wrong.append(f"{label}: table says {caught_by}; lint {lint}, rule test {rule}")
            if caught_by is not None and not (lint or rule):
                wrong.append(f"{label}: refused in the table and caught by neither guard")
            if caught_by is None and "known gap" in note and (lint or rule):
                wrong.append(f"{label}: marked a known gap but a guard now catches it")
        self.assertEqual(wrong, [])
        self.assertTrue(flagged, "ruff reported nothing: it did not read the files")


class SuppressionsRealRuffTest(TreeTest):
    def test_the_honoured_column_agrees_with_ruff_and_the_rule_test_refuses_every_honoured_one(
        self,
    ):
        tree = self.tree()
        write(tree, "shuttle/__init__.py", "")
        write(tree, "shuttle/core/__init__.py", "")
        rows = suppressions_table.SUPPRESSIONS
        for index, (_, source, _, _) in enumerate(rows):
            end = "" if source.endswith("\n") else "\n"
            write(tree, f"shuttle/core/row_{index:03d}.py", source + end)
        flagged = banned_import_findings(tree)

        disagree, let_through = [], []
        for index, (label, source, honoured, _) in enumerate(rows):
            silenced = f"core/row_{index:03d}.py" not in flagged
            if silenced != honoured:
                disagree.append(f"{label}: table says honoured={honoured}, ruff says {silenced}")
            refused = any("lint ignore" in p for p in check_module(source, "core/x.py"))
            if silenced and not refused:
                let_through.append(f"{label}: ruff honours it and the rule test does not refuse it")
        self.assertEqual(disagree, [], "update the honoured column to what ruff does now")
        self.assertEqual(let_through, [], "a spelling that silences the linter gets through")
        self.assertTrue(flagged, "ruff reported nothing: it did not read the files")


class GuardListingOfEveryNameTest(unittest.TestCase):
    def git(self, tree, *args):
        done = subprocess.run(
            ["git", *args], cwd=tree, env=GIT_ENV, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_every_name_the_filesystem_holds_is_listed_once_and_whole_in_one_block(self):
        with tempfile.TemporaryDirectory() as tree:
            self.git(tree, "init", "-q", "-b", "main")
            os.mkdir(os.path.join(tree, "checks"))
            for name in ("guard-files.sh", "guards.py", "names.py"):
                shutil.copy(os.path.join(REPO, "checks", name), os.path.join(tree, "checks"))
            write(tree, "README.md", "x\n")
            # the base has an older names table with one more row, a suppression table that
            # does not parse, and no import table
            real_names = read_file(os.path.join(TESTS, "hostile", "names_table.py"))
            extra = '    {"label": "a row only the base had", "name": "gone", "path": False},\n)\n'
            write(tree, "tests/hostile/names_table.py", real_names.rstrip()[:-1] + extra)
            write(tree, "tests/hostile/suppressions_table.py", "SUPPRESSIONS = (\n")
            self.git(tree, "add", "-A")
            self.git(tree, "commit", "-q", "-m", "base")
            base = self.git(tree, "rev-parse", "HEAD")

            made, unexpected = [], []
            for row in names_table.NAMES:
                rel = row["name"] if row["path"] else f"checks/{row['name']}"
                if not row["holdable"]:
                    continue
                try:
                    write(tree, os.fsdecode(rel), "x\n")
                except (OSError, ValueError) as error:
                    unexpected.append((row["label"], type(error).__name__))
                    continue
                made.append((row, rel))
            if unexpected:
                with self.subTest("some names are refused here"):
                    self.skipTest(support.unmade_note(unexpected))
            self.assertTrue(made)
            for table in ("names", "imports", "suppressions"):
                shutil.copy(
                    os.path.join(TESTS, "hostile", f"{table}_table.py"),
                    os.path.join(tree, "tests", "hostile"),
                )
            self.git(tree, "add", "-A")
            self.git(tree, "commit", "-q", "-m", "every name")

            done = subprocess.run(
                [os.path.join(tree, "checks", "guard-files.sh"), base],
                cwd=tree,
                env=GIT_ENV,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            whole = done.stdout.decode("utf-8")
            text, _, tables = whole.partition("## What this pull request does to the hostile")
            lines = text.split("\n")
            fence = next(line for line in lines if line.startswith("`"))
            self.assertEqual(lines.count(fence), 2, "exactly two fence lines")
            start = lines.index(fence)
            body = lines[start + 1 : lines.index(fence, start + 1)]
            expected = [
                "added   " + names.escape_name(os.fsdecode(rel))
                for row, rel in made
                if not row["path"]
            ]
            expected += [
                "changed tests/hostile/names_table.py",
                "changed tests/hostile/suppressions_table.py",
                "added   tests/hostile/imports_table.py",
            ]
            self.assertEqual(sorted(body), sorted(expected))
            self.assertEqual(
                collections.Counter(body).most_common(1)[0][1], 1, "a name is listed twice"
            )
            self.assertFalse([line for line in body if support.unsafe(line)])
            self.assertFalse(
                [line for line in body if line.lstrip(" ").startswith(fence)],
                "a name closed the block",
            )
            self.check_tables_section(tables)
            looks_alike = [rel for row, rel in made if row["path"]]
            self.assertTrue(looks_alike)
            for rel in looks_alike:
                self.assertNotIn(names.escape_name(os.fsdecode(rel)), text)

    @staticmethod
    def block_lines(section):
        """The lines inside the one fenced block of a section."""
        block = section.split("\n")
        fence = next(line for line in block if line.startswith("`"))
        return block[block.index(fence) + 1 : block.index(fence, block.index(fence) + 1)]

    def check_tables_section(self, section):
        """What the listing says about the tables: under the changes heading a row the base had,
        a table that did not parse at the base, a table the base lacked and each mark added;
        under its own heading, every known-gap mark."""
        changes, heading, standing = section.partition("## Known gaps in the tables, as they stand")
        self.assertTrue(heading, "the standing marks have their own heading")
        shown = self.block_lines(changes)
        held = self.block_lines(standing)
        self.assertIn("names: row removed: a row only the base had", shown)
        self.assertTrue(
            any(
                x.startswith("suppressions: the table at the base could not be read") for x in shown
            )
        )
        imports = len(imports_table.IMPORTS)
        self.assertIn(f"imports: no table at the base; all {imports} rows are new", shown)
        for row in names_table.NAMES:
            for key, reason in row.get("gaps", {}).items():
                self.assertIn(f"names: known gap: {row['label']}: {key}: {reason}", held)
                self.assertNotIn(f"names: known gap: {row['label']}: {key}: {reason}", shown)
        for label, _, _, _, note, _ in imports_table.IMPORTS:
            if "known gap" in note:
                self.assertIn(f"imports: new known gap: {label}: import form: {note}", shown)
                self.assertIn(f"imports: known gap: {label}: import form: {note}", held)
        self.assertFalse([line for line in shown + held if support.unsafe(line)])


if __name__ == "__main__":
    unittest.main()
