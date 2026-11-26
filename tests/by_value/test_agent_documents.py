"""The documents that steer agents point only at paths that exist.

`pointed_paths` is the decision: a document's text in, the repository paths it names out.
The walk over the real documents is a thin layer over it.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCUMENTS = [
    "AGENTS.md",
    "CODING_STANDARDS.md",
    "docs/process.md",
    ".github/pull_request_template.md",
    ".claude/agents/shuttle-builder.md",
    ".claude/agents/shuttle-reviewer.md",
]
EXTENSIONS = (".md", ".sh", ".py", ".toml", ".yml", ".txt")


def pointed_paths(text: str) -> list[str]:
    """Each backquoted span whose first word looks like a repository path, as a path."""
    found = []
    for span in re.findall(r"`([^`\n]+)`", text):
        word = span.split()[0].removeprefix("./")
        if "<" in word or "@" in word or not ("/" in word or word.endswith(EXTENSIONS)):
            continue
        found.append(word.split("*")[0].rstrip("/") if "*" in word else word.rstrip("/"))
    return found


def missing_paths(text: str, exists) -> list[str]:
    return [path for path in pointed_paths(text) if path and not exists(path)]


class PointedPathsTest(unittest.TestCase):
    def test_paths_and_folders_are_found_and_commands_reduce_to_their_script(self):
        text = "See `docs/process.md`, `tests/hostile/` and `./checks/all.sh --fix`."
        self.assertEqual(pointed_paths(text), ["docs/process.md", "tests/hostile", "checks/all.sh"])

    def test_a_glob_points_at_its_folder(self):
        self.assertEqual(pointed_paths("`.claude/agents/**`"), [".claude/agents"])

    def test_words_that_are_not_paths_are_left_alone(self):
        text = "`check: passed`, `<path>`, `users.noreply.github.com`, `gh pr view`"
        self.assertEqual(pointed_paths(text), [])

    def test_a_pointer_to_a_missing_file_is_reported(self):
        self.assertEqual(
            missing_paths("`docs/gone.md` and `README.md`", lambda p: p == "README.md"),
            ["docs/gone.md"],
        )


class DocumentsPointAtTheTreeTest(unittest.TestCase):
    def test_every_document_exists_and_every_path_it_names_exists(self):
        for name in DOCUMENTS:
            with self.subTest(document=name):
                with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
                    text = handle.read()
                missing = missing_paths(text, lambda p: os.path.exists(os.path.join(ROOT, p)))
                self.assertEqual(missing, [])
