"""The documents that steer agents point only at paths that exist.

`pointed_paths` is the decision: a document's text and the repository's top-level entries in,
the paths the text names out. The walk over the real documents is a thin layer over it.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCUMENTS = [
    "AGENTS.md",
    "CLAUDE.md",
    "CODING_STANDARDS.md",
    "README.md",
    "docs/process.md",
    ".github/pull_request_template.md",
    ".claude/agents/shuttle-builder.md",
    ".claude/agents/shuttle-reviewer.md",
]


def pointed_paths(text: str, top_level: set[str]) -> list[tuple[str, bool]]:
    """Each backquoted span whose first word begins with a top-level entry, as (path, folder).
    A trailing `:line`, `::member` or `#anchor` is cut; a glob points at the folder before it;
    a trailing slash says the path must be a folder."""
    found = []
    for span in re.findall(r"`([^`\n]+)`", text):
        word = re.split(r"[:#]", span.split()[0].removeprefix("./"))[0]
        if "*" in word:
            word = word[: word.index("*")]
        if word.split("/")[0] in top_level:
            found.append((word.rstrip("/"), word.endswith("/")))
    return found


def problems(text: str, top_level: set[str], kind) -> list[str]:
    """What is wrong with each pointer; `kind` says "folder", "file" or "" (absent) for a path."""
    result = []
    for path, folder in pointed_paths(text, top_level):
        found = kind(path)
        if not found:
            result.append(f"{path} does not exist")
        elif folder and found != "folder":
            result.append(f"{path} is pointed at as a folder but is a file")
    return result


def top_level_entries(listing: list[str], ignored: list[str]) -> set[str]:
    """The names at the root of the tree, less what the repository's own ignore file lists."""
    skipped = {line.strip().rstrip("/") for line in ignored}
    return {name for name in listing if name not in skipped and name != ".git"}


TOP = {"README.md", "AGENTS.md", "checks", "docs", "tests", ".claude"}


class PointedPathsTest(unittest.TestCase):
    def test_paths_folders_and_commands_reduce_to_the_path(self):
        text = "See `docs/process.md`, `tests/hostile/` and `./checks/all.sh --fix`."
        self.assertEqual(
            pointed_paths(text, TOP),
            [("docs/process.md", False), ("tests/hostile", True), ("checks/all.sh", False)],
        )

    def test_a_root_file_counts_by_its_exact_name(self):
        self.assertEqual(
            pointed_paths("`README.md` `README.mdx` `AGENTS`", TOP), [("README.md", False)]
        )

    def test_a_glob_points_at_the_folder_before_it(self):
        self.assertEqual(pointed_paths("`.claude/agents/**`", TOP), [(".claude/agents", True)])

    def test_a_line_number_member_or_anchor_is_cut(self):
        text = "`docs/process.md:14` `docs/process.md#steps` `tests/x.py::Class.method`"
        self.assertEqual(
            pointed_paths(text, TOP),
            [("docs/process.md", False), ("docs/process.md", False), ("tests/x.py", False)],
        )

    def test_spans_that_only_look_like_paths_are_not_paths(self):
        text = "`and/or` `origin/main` `.venv/bin/python` `/etc/passwd` `check: passed` `<path>`"
        self.assertEqual(pointed_paths(text, TOP), [])

    def test_a_pointer_to_something_missing_is_reported(self):
        kinds = {"README.md": "file"}
        self.assertEqual(
            problems("`docs/gone.md` and `README.md`", TOP, lambda p: kinds.get(p, "")),
            ["docs/gone.md does not exist"],
        )

    def test_a_folder_pointer_passes_only_for_a_folder(self):
        kinds = {"docs": "file"}
        self.assertEqual(
            problems("`docs/`", TOP, lambda p: kinds.get(p, "")),
            ["docs is pointed at as a folder but is a file"],
        )
        self.assertEqual(problems("`docs/`", TOP, lambda p: "folder"), [])

    def test_the_top_level_entries_leave_out_what_the_repository_ignores(self):
        listing = [".git", ".venv", "docs", "README.md"]
        self.assertEqual(
            top_level_entries(listing, [".venv/", "__pycache__/"]), {"docs", "README.md"}
        )


def kind_in(root: str):
    def kind(path: str) -> str:
        full = os.path.join(root, path)
        return "folder" if os.path.isdir(full) else "file" if os.path.exists(full) else ""

    return kind


class DocumentsPointAtTheTreeTest(unittest.TestCase):
    def test_every_document_exists_and_every_path_it_names_exists(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as handle:
            ignored = handle.read().splitlines()
        top = top_level_entries(os.listdir(ROOT), ignored)
        for name in DOCUMENTS:
            with self.subTest(document=name):
                with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
                    text = handle.read()
                self.assertEqual(problems(text, top, kind_in(ROOT)), [])
