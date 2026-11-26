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


def pointed_paths(text: str, top_level: set[str], ignored: set[str]) -> list[tuple[str, bool]]:
    """Each backquoted span that names a path, as (path, must be a folder). Only the first word
    counts; a leading `./`, a trailing `:line`, `::member` or `#anchor` are cut, and a glob
    points at the folder before it. A path (a) holds a slash and ends in a file extension or a
    slash, whatever its first component; or (b) is a bare word ending in `.md`; or (c) starts
    with a top-level entry of the tree. Absolute paths and anything under an ignored entry are
    not paths. A span is not a path either when it starts with `~`, `$` or `../` (a home folder, a
    variable, the folder above), or when its first component holds a dot after its first
    character and is not an entry of the tree (`example.com/x.html`; a dot folder such as
    `.github` starts with its dot, so a mistyped one is still reported)."""
    found = []
    for span in re.findall(r"`([^`\n]+)`", text):
        word = re.split(r":|#", span.split()[0].removeprefix("./"))[0]
        word = word[: word.index("*")] if "*" in word else word
        first = word.split("/")[0]
        if not word or word.startswith(("/", "~", "$", "../")) or "<" in word or ">" in word:
            continue
        host_like = "." in first[1:] and first not in top_level
        if first in ignored or ("/" in word and host_like):
            continue
        last = word.rstrip("/").split("/")[-1]
        slash = "/" in word
        has_extension = re.search(r"\.[A-Za-z][A-Za-z0-9]*$", last) is not None
        by_form = (slash and (word.endswith("/") or has_extension)) or (
            not slash and word.endswith(".md")
        )
        if by_form or first in top_level:
            found.append((word.rstrip("/"), word.endswith("/")))
    return found


def problems(text: str, top_level: set[str], ignored: set[str], kind) -> list[str]:
    """What is wrong with each pointer; `kind` says "folder", "file" or "" (absent) for a path."""
    result = []
    for path, folder in pointed_paths(text, top_level, ignored):
        found = kind(path)
        if not found:
            result.append(f"{path} does not exist")
        elif folder and found != "folder":
            result.append(f"{path} is pointed at as a folder but is a file")
    return result


def ignored_entries(ignore_lines: list[str]) -> set[str]:
    """The names the repository's own ignore file lists, plus its git folder."""
    return {line.strip().rstrip("/") for line in ignore_lines if line.strip()} | {".git"}


TOP = {"README.md", "AGENTS.md", "checks", "docs", "tests", ".claude", ".githooks"}
IGNORED = {".venv", "__pycache__", ".git"}


class PointedPathsTest(unittest.TestCase):
    def paths(self, text, top=TOP):
        return pointed_paths(text, top, IGNORED)

    def test_paths_folders_and_commands_reduce_to_the_path(self):
        text = "See `docs/process.md`, `tests/hostile/` and `./checks/all.sh --fix`."
        self.assertEqual(
            self.paths(text),
            [("docs/process.md", False), ("tests/hostile", True), ("checks/all.sh", False)],
        )

    def test_a_slash_and_an_extension_make_a_path_whatever_the_first_component(self):
        self.assertEqual(
            self.paths("`scripts/all.sh` `doc/process.md` `x/y.toml`"),
            [("scripts/all.sh", False), ("doc/process.md", False), ("x/y.toml", False)],
        )

    def test_a_trailing_slash_makes_a_folder_whatever_the_first_component(self):
        self.assertEqual(
            self.paths("`test/hostile/` `anything/`"), [("test/hostile", True), ("anything", True)]
        )

    def test_a_bare_word_ending_in_md_is_a_path(self):
        self.assertEqual(
            self.paths("`README.md` `NOTES.md`"), [("README.md", False), ("NOTES.md", False)]
        )

    def test_a_first_component_in_the_tree_makes_a_path_without_an_extension(self):
        self.assertEqual(
            self.paths("`.githooks/pre-push` `checks` `check` `.githooksx/y`"),
            [(".githooks/pre-push", False), ("checks", False)],
        )

    def test_a_glob_points_at_the_folder_before_it(self):
        self.assertEqual(self.paths("`.claude/agents/**`"), [(".claude/agents", True)])

    def test_a_line_number_member_or_anchor_is_cut(self):
        text = "`docs/process.md:14` `docs/process.md#steps` `tests/x.py::Class.method`"
        self.assertEqual(
            self.paths(text),
            [("docs/process.md", False), ("docs/process.md", False), ("tests/x.py", False)],
        )

    def test_spans_that_only_look_like_paths_are_not_paths(self):
        for span in (
            "and/or",
            "origin/main",
            ".venv/bin/python",
            ".venv/bin/tool.py",
            "/etc/passwd",
            "/etc/hosts.md",
            "check: passed",
            "<path>",
            "<dir>/x.md",
            "users.noreply.github.com",
            "gh pr view",
            "example.com/x.html",
            "~/x.md",
            "../x.md",
            "../checks/all.sh",
            "~/checks/",
            "$HOME/x.md",
            "${HOME}/x.md",
            "~user/x.md",
        ):
            with self.subTest(span=span):
                self.assertEqual(self.paths(f"`{span}`"), [])

    def test_a_renamed_top_level_folder_is_reported_not_forgotten(self):
        # the tree no longer has `checks`; the documents still point at it
        found = problems("`checks/all.sh` and `checks/`", {"docs"}, IGNORED, lambda p: "")
        self.assertEqual(found, ["checks/all.sh does not exist", "checks does not exist"])

    def test_a_mistyped_or_removed_dot_folder_is_reported_and_a_host_name_is_not(self):
        text = "`.claud/agents/x.md` `.github/workflows/gone.yml` `example.com/x.html`"
        found = problems(text, {".claude"}, IGNORED, lambda p: "")
        self.assertEqual(
            found,
            [".claud/agents/x.md does not exist", ".github/workflows/gone.yml does not exist"],
        )

    def test_a_mistyped_first_component_is_reported(self):
        found = problems("`doc/process.md` and `test/hostile/`", TOP, IGNORED, lambda p: "")
        self.assertEqual(found, ["doc/process.md does not exist", "test/hostile does not exist"])

    def test_a_pointer_to_something_missing_is_reported(self):
        kinds = {"README.md": "file"}
        self.assertEqual(
            problems("`docs/gone.md` and `README.md`", TOP, IGNORED, lambda p: kinds.get(p, "")),
            ["docs/gone.md does not exist"],
        )

    def test_a_folder_pointer_passes_only_for_a_folder(self):
        kinds = {"docs": "file"}
        self.assertEqual(
            problems("`docs/`", TOP, IGNORED, lambda p: kinds.get(p, "")),
            ["docs is pointed at as a folder but is a file"],
        )
        self.assertEqual(problems("`docs/`", TOP, IGNORED, lambda p: "folder"), [])

    def test_the_ignored_names_come_from_the_ignore_file_and_the_git_folder(self):
        self.assertEqual(
            ignored_entries([".venv/", "", "__pycache__/"]), {".venv", "__pycache__", ".git"}
        )


def kind_in(root: str):
    def kind(path: str) -> str:
        full = os.path.join(root, path)
        return "folder" if os.path.isdir(full) else "file" if os.path.exists(full) else ""

    return kind


class DocumentsPointAtTheTreeTest(unittest.TestCase):
    def test_every_document_exists_and_every_path_it_names_exists(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        ignored = ignored_entries(lines)
        top = set(os.listdir(ROOT)) - ignored
        for name in DOCUMENTS:
            with self.subTest(document=name):
                with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
                    text = handle.read()
                self.assertEqual(problems(text, top, ignored, kind_in(ROOT)), [])
