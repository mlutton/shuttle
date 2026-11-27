"""The cases every set of operations is held to: the real one and the simulated one.

`ContractCases` is a mixin. A test class that mixes it in with unittest.TestCase sets
`self.world` (an Operations) and `self.harness` (what a case needs that is not an operation:
a fresh folder, a listing of it, a program to start, a signal to send). The real half is
tests/command/test_world_contract.py (a temporary folder, real short-lived child processes);
the simulated half is tests/by_value/test_world_contract.py. Both must pass every case: a
case the simulated world cannot honestly model is a finding to report, not a case to drop.
Where a case is not here for that reason, UNMODELLED says so.

Each case's name says the invariant. The waits are the processes' own, bounded by a count of
tries, and end as soon as what is waited for has happened; no test reads a clock or sleeps.
"""

import hashlib
import importlib
import os
import re
import sys

from shuttle.core import boundary, place
from shuttle.core.shapes import NotARegularFile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAMES = importlib.import_module("hostile.names_table").NAMES

# What the simulated world cannot honestly do, so no case exists for it (reported in the
# pull request): it runs no program, so it cannot show which environment a child sees, what
# a real child prints or writes, or that a real child's exit status is the program's own.
UNMODELLED = (
    "the environment a started child really sees",
    "what a started child really does beyond the behaviour declared for it",
    "the git configuration, ignore rules, hooks and identity a real git would read or use "
    "(the simulated freeze only counts files; the real half's own cases show the commit's "
    "identity, that nothing of the caller's is read, and a file that cannot be read)",
)

HOLDABLE_NAMES = [row for row in NAMES if row["holdable"] and not row["path"]]
HANDLED_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGALRM")
TEXT = "line one\nline two \u00e9 \u2713\n"


# A folder name with what a command line or a unit file treats specially: a dash, spaces, a
# dollar, a braced name, a percent, a backslash and a newline.
AWKWARD_FOLDER = "-p a$$b ${X} $HOME %h %n\\\nz"

TRIES = 200
TRY_SECONDS = 0.05


def ended(world, process):
    """Wait on the process until it has ended; False if it had not after TRIES tries."""
    return any(world.processes.wait(process, TRY_SECONDS) is not None for _ in range(TRIES))


class ContractCases:
    def assertRaisesExactly(self, expected, function, *arguments):
        """The call raises `expected` itself, not a parent or a sibling class: the run prints the
        class's name in lines a caller reads, so the two halves must agree on it."""
        try:
            function(*arguments)
        except BaseException as error:
            self.assertIs(type(error), expected, f"{type(error).__name__}: {error}")
            return
        self.fail(f"nothing was raised; expected {expected.__name__}")

    # ------------------------------------------------------------------ files

    def fresh(self, name="a-file"):
        return f"{self.harness.folder()}/{name}"

    def test_a_text_put_in_place_reads_back_whole_as_utf_8(self):
        path = self.fresh()
        self.world.files.write_new(path, TEXT)
        self.assertEqual(self.world.files.read(path), TEXT.encode("utf-8"))

    def test_a_file_read_by_lines_gives_each_line_without_its_end_and_never_a_cut_one_whole(self):
        path = self.fresh()
        self.world.files.write_new(path, "one\ntwo\r\n\nlast without an end")
        lines = list(self.world.files.read_lines(path, 100))
        self.assertEqual(
            lines,
            [(b"one", False), (b"two\r", False), (b"", False), (b"last without an end", False)],
        )

    def test_a_line_over_the_limit_gives_its_first_bytes_cut_and_the_lines_after_it_whole(self):
        path = self.fresh()
        self.world.files.write_new(path, "abcdef\n12345\nxyzzy\nabcdefghij")
        got = list(self.world.files.read_lines(path, 5))
        self.assertEqual(
            got, [(b"abcde", True), (b"12345", False), (b"xyzzy", False), (b"abcde", True)]
        )

    def test_a_file_of_one_endless_line_is_read_in_bounded_pieces(self):
        path = self.fresh()
        self.world.files.write_new(path, "x" * 3_000_000 + "\nnext\n")
        got = list(self.world.files.read_lines(path, 10))
        self.assertEqual(got, [(b"x" * 10, True), (b"next", False)])

    def test_reading_an_empty_file_by_lines_gives_none_and_an_end_with_a_line_end_gives_no_extra(
        self,
    ):
        empty, ended = self.fresh("empty"), self.fresh("ended")
        self.world.files.write_new(empty, "")
        self.world.files.write_new(ended, "a\n")
        self.assertEqual(list(self.world.files.read_lines(empty, 5)), [])
        self.assertEqual(list(self.world.files.read_lines(ended, 5)), [(b"a", False)])

    def test_reading_by_lines_raises_as_reading_does_when_the_call_is_made(self):
        things = dict(self.not_regular_things())
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.read_lines, self.fresh("absent"), 5
        )
        self.assertRaisesExactly(
            IsADirectoryError, self.world.files.read_lines, self.harness.folder(), 5
        )
        for label in ("a named pipe", "a device", "a link to a device", "a link to a named pipe"):
            with self.subTest(label):
                self.assertRaisesExactly(
                    NotARegularFile, self.world.files.read_lines, things[label], 5
                )

    def test_a_new_file_that_is_not_there_yet_is_not_there_and_then_is(self):
        path = self.fresh()
        self.assertFalse(self.world.files.exists(path))
        self.world.files.write_new(path, "x")
        self.assertTrue(self.world.files.exists(path))
        self.world.files.remove(path)
        self.assertFalse(self.world.files.exists(path))

    def test_writing_a_new_file_over_a_name_that_is_there_raises_file_exists_and_changes_nothing(
        self,
    ):
        path = self.fresh()
        self.world.files.write_new(path, "first")
        self.assertRaisesExactly(FileExistsError, self.world.files.write_new, path, "second")
        self.assertEqual(self.world.files.read(path), b"first")

    def test_writing_a_new_file_in_a_folder_that_is_not_there_raises_and_makes_nothing(self):
        folder = self.harness.folder()
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.write_new, f"{folder}/absent/file", "x"
        )
        self.assertEqual(self.harness.names_in(folder), [])

    def test_a_text_that_cannot_be_encoded_raises_a_value_error(self):
        path = self.fresh()
        self.assertRaisesExactly(
            UnicodeEncodeError, self.world.files.write_new, path, "lone surrogate \ud800"
        )
        # the name was made before the text was encoded, and is left there, empty
        self.assertEqual(self.world.files.read(path), b"")

    def test_a_linked_name_reads_the_same_and_outlives_the_removal_of_the_first(self):
        first, second = self.fresh("first"), self.fresh("second")
        self.world.files.write_new(first, TEXT)
        self.world.files.link(first, second)
        self.assertEqual(self.world.files.read(second), TEXT.encode("utf-8"))
        self.world.files.remove(first)
        self.assertFalse(self.world.files.exists(first))
        self.assertEqual(self.world.files.read(second), TEXT.encode("utf-8"))

    def test_linking_onto_a_name_that_is_there_raises_file_exists_and_changes_neither(self):
        first, second = self.fresh("first"), self.fresh("second")
        self.world.files.write_new(first, "one")
        self.world.files.write_new(second, "two")
        self.assertRaisesExactly(FileExistsError, self.world.files.link, first, second)
        self.assertEqual(self.world.files.read(first), b"one")
        self.assertEqual(self.world.files.read(second), b"two")

    def test_linking_from_a_name_that_is_not_there_raises_and_makes_nothing(self):
        folder = self.harness.folder()
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.link, f"{folder}/absent", f"{folder}/new"
        )
        self.assertEqual(self.harness.names_in(folder), [])

    def test_a_copy_reads_the_same_and_outlives_the_removal_of_the_first(self):
        first, second = self.fresh("first"), self.fresh("second")
        text = "no final newline, crlf\r\n, trailing spaces   "
        self.world.files.write_new(first, text)
        self.world.files.copy(first, second)
        self.assertEqual(self.world.files.read(second), text.encode("utf-8"))
        self.assertEqual(self.world.files.read(first), text.encode("utf-8"))
        self.world.files.remove(first)
        self.assertEqual(self.world.files.read(second), text.encode("utf-8"))

    def test_a_copy_of_an_empty_file_is_an_empty_file(self):
        first, second = self.fresh("first"), self.fresh("second")
        self.world.files.write_new(first, "")
        self.world.files.copy(first, second)
        self.assertEqual(self.world.files.read(second), b"")

    def test_copying_onto_a_name_that_is_there_raises_file_exists_and_changes_neither(self):
        first, second = self.fresh("first"), self.fresh("second")
        self.world.files.write_new(first, "one")
        self.world.files.write_new(second, "two")
        self.assertRaisesExactly(FileExistsError, self.world.files.copy, first, second)
        self.assertEqual(self.world.files.read(first), b"one")
        self.assertEqual(self.world.files.read(second), b"two")

    def test_copying_from_a_name_that_is_not_there_raises_and_makes_nothing(self):
        folder = self.harness.folder()
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.copy, f"{folder}/absent", f"{folder}/new"
        )
        self.assertEqual(self.harness.names_in(folder), [])

    def test_copying_into_a_folder_that_is_not_there_raises_and_makes_nothing(self):
        first = self.fresh("first")
        self.world.files.write_new(first, "one")
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.copy, first, f"{self.fresh('absent')}/new"
        )

    def test_copying_a_folder_raises_is_a_directory_and_makes_nothing(self):
        folder, other = self.harness.folder(), self.harness.folder()
        self.assertRaisesExactly(IsADirectoryError, self.world.files.copy, folder, f"{other}/new")
        self.assertEqual(self.harness.names_in(other), [])

    def test_a_copy_of_a_name_that_leads_nowhere_raises_not_a_regular_file_and_makes_nothing(self):
        path, other = self.fresh("dangling"), self.fresh("other")
        self.harness.make_a_name_that_leads_nowhere(path)
        self.assertRaisesExactly(NotARegularFile, self.world.files.copy, path, other)
        self.assertFalse(self.world.files.exists(other))

    def not_regular_things(self):
        """One of each thing that is not a regular file, as (label, name). The harness makes
        each so that a call that waits on it or reads it without end fails instead of hanging."""
        target, folder = self.fresh("target"), self.harness.folder()
        self.world.files.write_new(target, TEXT)
        things = {
            "a link to a file": (self.harness.make_a_link, target),
            "a link to a folder": (self.harness.make_a_link, folder),
            "a link to a missing name": (self.harness.make_a_link, self.fresh("missing")),
            "a link to a link to a file": (
                self.harness.make_a_link,
                self.harness.make_a_link(self.fresh("inner"), target),
            ),
            "a link to a device": (self.harness.make_a_link, self.harness.a_device()),
            "a link to a named pipe": (
                self.harness.make_a_link,
                self.harness.make_a_pipe(self.fresh("target-pipe")),
            ),
        }
        made = []
        for label, (make, leads_to) in things.items():
            made.append((label, make(self.fresh("thing"), leads_to)))
        made.append(("a named pipe", self.harness.make_a_pipe(self.fresh("pipe"))))
        made.append(("a device", self.harness.a_device()))
        return made

    def test_copying_a_link_a_pipe_or_a_device_raises_not_a_regular_file_and_makes_nothing(self):
        for label, path in self.not_regular_things():
            with self.subTest(label):
                new = self.fresh("new")
                self.assertRaisesExactly(NotARegularFile, self.world.files.copy, path, new)
                self.assertFalse(self.world.files.exists(new))

    def test_reading_or_hashing_a_pipe_or_a_device_raises_not_a_regular_file(self):
        things = dict(self.not_regular_things())
        for label in ("a named pipe", "a device", "a link to a device", "a link to a named pipe"):
            for operation in (self.world.files.read, self.world.files.hash):
                with self.subTest(label, operation=operation):
                    self.assertRaisesExactly(NotARegularFile, operation, things[label])

    def test_reading_and_hashing_a_link_to_a_file_follow_it(self):
        target, link = self.fresh("target"), self.fresh("link")
        self.world.files.write_new(target, TEXT)
        self.harness.make_a_link(link, target)
        self.assertEqual(self.world.files.read(link), TEXT.encode("utf-8"))
        self.assertEqual(self.world.files.hash(link), self.world.files.hash(target))

    def test_a_file_put_in_place_under_every_name_the_filesystem_will_hold_copies_and_hashes(self):
        folder = self.harness.folder()
        for row in HOLDABLE_NAMES:
            with self.subTest(label=row["label"]):
                path, alias = f"{folder}/{row['name']}", f"{folder}/copy-of-it"
                self.world.files.write_new(path, TEXT)
                self.world.files.copy(path, alias)
                self.assertEqual(self.world.files.read(alias), TEXT.encode("utf-8"))
                self.assertEqual(self.world.files.hash(path), self.world.files.hash(alias))
                self.world.files.remove(alias)
                self.world.files.copy(path, alias)  # into a name that was just freed
                self.world.files.remove(alias)
                self.world.files.remove(path)

    def test_the_hash_is_the_sha256_of_the_bytes_in_lower_case_hex(self):
        empty, text, big = self.fresh("empty"), self.fresh("text"), self.fresh("big")
        self.world.files.write_new(empty, "")
        self.world.files.write_new(text, TEXT)
        self.world.files.write_new(big, "0123456789" * 300000)  # more than one read of any size
        self.assertEqual(self.world.files.hash(empty), hashlib.sha256(b"").hexdigest())
        self.assertEqual(self.world.files.hash(text), hashlib.sha256(TEXT.encode()).hexdigest())
        self.assertEqual(
            self.world.files.hash(big), hashlib.sha256(b"0123456789" * 300000).hexdigest()
        )

    def test_hashing_a_name_that_is_not_there_raises_file_not_found_and_a_folder_is_a_directory(
        self,
    ):
        self.assertRaisesExactly(FileNotFoundError, self.world.files.hash, self.fresh("absent"))
        self.assertRaisesExactly(IsADirectoryError, self.world.files.hash, self.harness.folder())

    def test_removing_a_name_that_is_not_there_raises_file_not_found(self):
        self.assertRaisesExactly(FileNotFoundError, self.world.files.remove, self.fresh("absent"))

    def test_reading_a_name_that_is_not_there_raises_file_not_found(self):
        self.assertRaisesExactly(FileNotFoundError, self.world.files.read, self.fresh("absent"))

    def test_reading_a_folder_raises_is_a_directory(self):
        self.assertRaisesExactly(IsADirectoryError, self.world.files.read, self.harness.folder())

    def test_only_a_folder_is_a_usable_folder(self):
        folder, absent = self.harness.folder(), self.fresh("absent")
        self.assertTrue(self.world.files.usable_folder(folder))
        self.assertFalse(self.world.files.usable_folder(absent))
        self.world.files.write_new(absent, TEXT)
        self.assertFalse(self.world.files.usable_folder(absent))

    def test_a_folder_is_there_and_cannot_be_written_over_linked_from_or_removed(self):
        folder, other = self.harness.folder(), self.fresh("other")
        self.assertTrue(self.world.files.exists(folder))
        self.assertRaisesExactly(FileExistsError, self.world.files.write_new, folder, "x")
        self.assertRaisesExactly(PermissionError, self.world.files.link, folder, other)
        self.assertRaisesExactly(IsADirectoryError, self.world.files.remove, folder)
        self.assertTrue(self.world.files.exists(folder))

    def test_a_name_that_leads_nowhere_is_there_cannot_be_read_or_written_over_and_can_be_removed(
        self,
    ):
        path, other = self.fresh("dangling"), self.fresh("other")
        self.harness.make_a_name_that_leads_nowhere(path)
        self.assertTrue(self.world.files.exists(path))
        self.assertRaisesExactly(FileNotFoundError, self.world.files.read, path)
        self.assertRaisesExactly(FileExistsError, self.world.files.write_new, path, "x")
        self.world.files.write_new(other, "x")
        self.assertRaisesExactly(FileExistsError, self.world.files.link, other, path)
        self.world.files.remove(path)
        self.assertFalse(self.world.files.exists(path))

    def test_a_file_of_a_hundred_thousand_bytes_reads_back_whole(self):
        path, text = self.fresh(), "0123456789" * 10000
        self.world.files.write_new(path, text)
        self.assertEqual(self.world.files.read(path), text.encode("utf-8"))

    def test_a_record_put_in_place_under_every_name_the_filesystem_will_hold_reads_back_whole(self):
        # tests/hostile/names_table.py: the rows that are one name (not a path of several parts)
        folder = self.harness.folder()
        for row in HOLDABLE_NAMES:
            with self.subTest(label=row["label"]):
                path = f"{folder}/{row['name']}"
                alias = f"{folder}/linked-{len(self.harness.names_in(folder))}"
                self.world.files.write_new(path, TEXT)
                self.assertTrue(self.world.files.exists(path))
                self.assertEqual(self.world.files.read(path), TEXT.encode("utf-8"))
                self.assertIn(row["name"], self.harness.names_in(folder))
                self.world.files.link(path, alias)
                self.world.files.remove(path)
                self.assertEqual(self.world.files.read(alias), TEXT.encode("utf-8"))
                self.world.files.remove(alias)
                self.assertNotIn(row["name"], self.harness.names_in(folder))

    # ------------------------------------------------------------ the run area's operations

    def test_a_temporary_folder_is_new_empty_absolute_usable_and_never_the_same_twice(self):
        first = self.world.files.make_temporary_folder("contract-area-")
        second = self.world.files.make_temporary_folder("contract-area-")
        self.addCleanup(self.world.files.remove_tree, first)
        self.addCleanup(self.world.files.remove_tree, second)
        self.assertNotEqual(first, second)
        for path in (first, second):
            self.assertTrue(path.startswith("/"))
            self.assertTrue(path.rpartition("/")[2].startswith("contract-area-"))
            self.assertTrue(self.world.files.usable_folder(path))
            self.assertEqual(self.harness.everything_below(path), [])

    def test_making_folders_makes_each_missing_one_and_is_no_change_where_they_are(self):
        folder = self.harness.folder()
        self.world.files.make_folders(f"{folder}/a/b/c")
        self.world.files.make_folders(f"{folder}/a/b/c")
        self.assertEqual(self.harness.everything_below(folder), ["a/", "a/b/", "a/b/c/"])

    def test_making_folders_over_a_file_raises_file_exists_and_changes_nothing(self):
        path = self.fresh("file")
        self.world.files.write_new(path, "one")
        self.assertRaisesExactly(FileExistsError, self.world.files.make_folders, path)
        self.assertEqual(self.world.files.read(path), b"one")

    def a_tree(self):
        """A folder holding files and folders, one of each thing a copy leaves out or skips."""
        folder = self.harness.folder()
        files = self.world.files
        files.make_folders(f"{folder}/inside/deeper")
        files.make_folders(f"{folder}/history")
        files.write_new(f"{folder}/settings", TEXT)
        files.write_new(f"{folder}/inside/one", "one")
        files.write_new(f"{folder}/inside/deeper/two", "two")
        files.write_new(f"{folder}/history/old", "old")
        files.write_new(f"{folder}/cache", "cached")
        self.harness.make_a_link(f"{folder}/a-link", f"{folder}/settings")
        return folder

    def test_copying_a_folder_copies_every_file_and_folder_below_and_skips_a_link(self):
        tree, other = self.a_tree(), self.harness.folder()
        self.world.files.copy_path(tree, f"{other}/copy", [])
        self.assertEqual(
            self.harness.everything_below(f"{other}/copy"),
            ["cache", "history/", "history/old", "inside/", "inside/deeper/",
             "inside/deeper/two", "inside/one", "settings"],
        )  # fmt: skip
        self.assertEqual(self.world.files.read(f"{other}/copy/inside/deeper/two"), b"two")
        self.world.files.remove(f"{tree}/settings")  # the copy has its own bytes
        self.assertEqual(self.world.files.read(f"{other}/copy/settings"), TEXT.encode("utf-8"))

    def test_copying_a_folder_leaves_out_the_names_given_a_file_or_a_whole_folder(self):
        tree, other = self.a_tree(), self.harness.folder()
        self.world.files.copy_path(tree, f"{other}/copy", ["history", "inside/deeper/two", "cache"])
        self.assertEqual(
            self.harness.everything_below(f"{other}/copy"),
            ["inside/", "inside/deeper/", "inside/one", "settings"],
        )
        self.assertTrue(self.world.files.exists(f"{tree}/history/old"))  # the original is whole

    def test_copying_a_file_by_copy_path_is_a_copy_and_a_left_out_name_changes_nothing(self):
        first, second = self.fresh("first"), self.fresh("second")
        self.world.files.write_new(first, "text")
        self.world.files.copy_path(first, second, ["anything"])
        self.assertEqual(self.world.files.read(second), b"text")

    def test_copying_a_path_onto_a_name_that_is_there_raises_file_exists_and_changes_neither(self):
        tree, other = self.a_tree(), self.harness.folder()
        self.world.files.make_folders(f"{other}/copy")
        self.assertRaisesExactly(
            FileExistsError, self.world.files.copy_path, tree, f"{other}/copy", []
        )
        self.assertEqual(self.harness.everything_below(f"{other}/copy"), [])

    def test_copying_a_path_that_is_not_there_or_into_a_folder_that_is_not_there_raises(self):
        tree, other = self.a_tree(), self.harness.folder()
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.copy_path, f"{other}/absent", f"{other}/new", []
        )
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.copy_path, tree, f"{other}/absent/new", []
        )
        self.assertEqual(self.harness.everything_below(other), [])

    def test_copying_a_path_that_is_a_link_a_pipe_or_a_device_raises_and_makes_nothing(self):
        for label, path in self.not_regular_things():
            with self.subTest(label):
                new = self.fresh("new")
                self.assertRaisesExactly(NotARegularFile, self.world.files.copy_path, path, new, [])
                self.assertFalse(self.world.files.exists(new))

    def test_a_folder_and_a_link_to_one_are_folders_and_nothing_else_is(self):
        where = self.harness.folder()
        folder, file, absent = f"{where}/folder", f"{where}/file", f"{where}/absent"
        self.world.files.make_folders(folder)
        self.world.files.write_new(file, TEXT)
        links = {name: f"{where}/{name}" for name in ("to-folder", "to-file", "to-nothing")}
        self.harness.make_a_link(links["to-folder"], folder)
        self.harness.make_a_link(links["to-file"], file)
        self.harness.make_a_link(links["to-nothing"], absent)
        self.assertTrue(self.world.files.is_folder(folder))
        self.assertTrue(self.world.files.is_folder(links["to-folder"]))
        for label, name in (
            ("absent", absent),
            ("a file", file),
            ("a link to a file", links["to-file"]),
            ("a link to nothing", links["to-nothing"]),
        ):
            with self.subTest(label):
                self.assertFalse(self.world.files.is_folder(name))

    def test_making_a_read_only_tree_writable_changes_what_is_below_and_never_follows_a_link(self):
        tree, outside = self.a_tree(), self.fresh("outside")
        self.world.files.write_new(outside, "x")
        self.harness.make_read_only(outside)
        self.harness.make_a_link(f"{tree}/to-outside", outside)
        for name in ("settings", "inside", "inside/deeper/two"):
            self.harness.make_read_only(f"{tree}/{name}")
        self.world.files.make_writable(tree)
        for name in ("settings", "inside", "inside/deeper/two"):
            self.assertTrue(self.harness.is_writable(f"{tree}/{name}"), name)
        self.assertFalse(self.harness.is_writable(outside))

    def test_making_a_link_writable_raises_not_a_regular_file_and_a_missing_name_raises(self):
        folder, outside = self.harness.folder(), self.fresh("outside")
        self.world.files.write_new(outside, "x")
        self.harness.make_read_only(outside)
        self.harness.make_a_link(f"{folder}/link", outside)
        self.assertRaisesExactly(NotARegularFile, self.world.files.make_writable, f"{folder}/link")
        self.assertFalse(self.harness.is_writable(outside))
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.make_writable, f"{folder}/absent"
        )

    def test_removing_a_tree_removes_all_of_it_read_only_parts_too_and_a_link_not_what_it_leads_to(
        self,
    ):
        tree, elsewhere = self.a_tree(), self.harness.folder()
        self.world.files.write_new(f"{elsewhere}/kept", "kept")
        self.harness.make_a_link(f"{tree}/to-folder", elsewhere)
        for name in ("inside/deeper/two", "inside/deeper", "inside"):
            self.harness.make_read_only(f"{tree}/{name}")
        self.world.files.remove_tree(tree)
        self.assertFalse(self.world.files.exists(tree))
        self.assertEqual(self.world.files.read(f"{elsewhere}/kept"), b"kept")

    def test_removing_a_tree_that_is_not_there_raises_file_not_found_and_a_file_raises_not_a_directory(
        self,
    ):
        folder, path = self.harness.folder(), self.fresh("file")
        self.assertRaisesExactly(
            FileNotFoundError, self.world.files.remove_tree, f"{folder}/absent"
        )
        self.world.files.write_new(path, "x")
        self.assertRaisesExactly(NotADirectoryError, self.world.files.remove_tree, path)
        self.assertEqual(self.world.files.read(path), b"x")

    # -------------------------------------------------------------- processes

    def start(self, kind, **extra):
        argv = self.harness.argv(kind, **extra)
        process = self.world.processes.start(argv, self.harness.environment())
        self.addCleanup(self.harness.end, process)
        return process

    def ended(self, process):
        return ended(self.world, process)

    def test_a_program_that_can_be_found_is_found_and_one_that_cannot_is_not(self):
        found = self.world.processes.find_program(self.harness.argv("exits_at_once")[0])
        self.assertIsInstance(found, str)
        self.assertTrue(found.startswith("/"))  # absolute, the link (if any) not followed
        self.assertIsNone(self.world.processes.find_program(self.harness.argv("not_a_program")[0]))
        for odd in ("a\0b", "a" * 5000, "no/such/dir/" * 500, ""):  # none of these may raise
            self.assertIsNone(self.world.processes.find_program(odd))

    def test_a_program_that_exits_by_itself_ends_with_its_exit_status_and_keeps_it(self):
        for kind, status in (("exits_at_once", 0), ("exits_with_three", 3)):
            with self.subTest(kind):
                process = self.start(kind)
                self.assertTrue(self.ended(process))
                self.assertEqual(self.world.processes.poll(process), status)
                self.assertEqual(self.world.processes.poll(process), status)

    def test_starting_a_program_that_cannot_be_found_raises_file_not_found(self):
        self.assertRaisesExactly(
            FileNotFoundError,
            self.world.processes.start,
            self.harness.argv("not_a_program"),
            self.harness.environment(),
        )

    def test_starting_a_program_with_an_argument_holding_a_null_character_raises_a_value_error(
        self,
    ):
        argv = [*self.harness.argv("exits_at_once"), "a\0b"]
        self.assertRaisesExactly(
            ValueError, self.world.processes.start, argv, self.harness.environment()
        )

    def test_a_running_program_polls_none_and_waiting_for_it_gives_none_until_it_is_ended(self):
        process = self.start("sleeps")
        self.assertIsNone(self.world.processes.poll(process))
        self.assertIsNone(self.world.processes.wait(process, 0.01))
        self.harness.end(process)
        self.assertTrue(self.ended(process))
        self.assertEqual(self.world.processes.poll(process), -9)

    def test_waiting_for_a_program_that_has_ended_gives_its_status_every_time(self):
        process = self.start("exits_with_three")
        self.assertTrue(self.ended(process))
        self.assertEqual(self.world.processes.wait(process, 0), 3)
        self.assertEqual(self.world.processes.wait(process, 0.01), 3)

    def test_a_started_child_has_all_three_standard_streams_at_the_null_device(self):
        process = self.start("reports_streams", report=self.fresh("report"))
        self.assertTrue(self.ended(process))
        self.assertEqual(self.harness.streams_the_child_saw(), ("null", "null", "null"))

    def test_a_started_child_is_in_the_callers_session_and_process_group(self):
        process = self.start("reports_session", report=self.fresh("report"))
        self.assertTrue(self.ended(process))
        self.assertEqual(self.harness.session_the_child_saw(), (True, True))

    def test_what_a_child_writes_to_the_report_descriptor_it_was_given_is_read_back_every_time(
        self,
    ):
        processes = self.world.processes
        number = processes.open_report()
        argv = self.harness.argv("writes_to_the_report", fd=number)
        process = processes.start(argv, self.harness.environment(), number)
        self.addCleanup(self.harness.end, process)
        self.assertTrue(self.ended(process))
        self.assertEqual(processes.read_report(process), "hello\n")
        self.assertEqual(processes.read_report(process), "hello\n")

    def test_a_child_started_with_an_input_file_reads_it_whole_as_its_standard_input(self):
        text = TEXT * 2000
        path = self.fresh("instruction")
        self.world.files.write_new(path, text)
        process = self.world.processes.start(
            self.harness.argv("copies_its_input", report=self.fresh("copied")),
            self.harness.environment(),
            None,
            path,
        )
        self.addCleanup(self.harness.end, process)
        self.assertTrue(self.ended(process))
        self.assertEqual(self.harness.what_the_child_read(), text.encode("utf-8"))

    def test_starting_with_an_input_file_that_is_not_there_raises_file_not_found_and_starts_nothing(
        self,
    ):
        self.assertRaisesExactly(
            FileNotFoundError,
            self.world.processes.start,
            self.harness.argv("exits_at_once"),
            self.harness.environment(),
            None,
            self.fresh("absent"),
        )

    def test_a_child_started_with_an_output_name_writes_its_standard_output_there(self):
        path = self.fresh("output")
        process = self.world.processes.start(
            self.harness.argv("prints_hello"), self.harness.environment(), None, None, path
        )
        self.addCleanup(self.harness.end, process)
        self.assertTrue(self.ended(process))
        self.assertEqual(self.world.files.read(path), b"hello\n")

    def test_starting_with_an_output_name_that_is_taken_or_has_no_folder_raises_and_starts_nothing(
        self,
    ):
        taken = self.fresh("taken")
        self.world.files.write_new(taken, "kept")
        for name, error in (
            (taken, FileExistsError),
            (f"{self.fresh('absent')}/in", FileNotFoundError),
        ):
            with self.subTest(name):
                self.assertRaisesExactly(
                    error,
                    self.world.processes.start,
                    self.harness.argv("prints_hello"),
                    self.harness.environment(),
                    None,
                    None,
                    name,
                )
        self.assertEqual(self.world.files.read(taken), b"kept")

    def test_a_child_started_without_a_report_descriptor_has_an_empty_report(self):
        process = self.start("exits_at_once")
        self.assertTrue(self.ended(process))
        self.assertEqual(self.world.processes.read_report(process), "")

    # ------------------------------------------------------------------ git: looking

    def look(self, where):
        environment = place.git_environment(self.harness.environment()["PATH"])
        return self.world.git.look_at_place(where, environment)

    def test_a_folder_that_is_not_there_has_no_facts_to_find(self):
        found = self.look(f"{self.harness.folder()}/absent")
        self.assertEqual(
            found,
            {
                "exists": False,
                "is_checkout": False,
                "head": None,
                "unclean": [],
                "nested": [],
                "filtered": [],
            },
        )

    def test_a_folder_that_is_not_a_checkout_exists_and_nothing_more(self):
        found = self.look(self.harness.folder())
        self.assertEqual(
            found,
            {
                "exists": True,
                "is_checkout": False,
                "head": None,
                "unclean": [],
                "nested": [],
                "filtered": [],
            },
        )

    def test_a_folder_inside_a_checkout_is_not_a_checkout_of_its_own(self):
        top, _ = self.harness.checkout({"inner/file": "x\n"})
        found = self.look(f"{top}/inner")
        self.assertEqual(
            (found["exists"], found["is_checkout"], found["head"]), (True, False, None)
        )

    def test_a_clean_checkout_gives_its_commit_and_nothing_unclean_or_nested(self):
        where, head = self.harness.checkout({"a": "1\n", "dir/b": "2\n"})
        self.assertEqual(
            self.look(where),
            {
                "exists": True,
                "is_checkout": True,
                "head": head,
                "unclean": [],
                "nested": [],
                "filtered": [],
            },
        )

    def test_a_new_a_changed_and_a_removed_file_are_each_unclean_and_named(self):
        where, _ = self.harness.checkout({"kept": "1\n", "changed": "1\n", "gone": "1\n"})
        self.harness.edit(where, "new", "n\n")
        self.harness.edit(where, "changed", "2\n")
        self.harness.remove(where, "gone")
        self.assertEqual(sorted(self.look(where)["unclean"]), ["changed", "gone", "new"])

    def test_every_name_the_filesystem_holds_comes_back_whole_as_unclean(self):
        where, _ = self.harness.checkout({"seed": "x\n"})
        names = [row["name"] for row in HOLDABLE_NAMES if self.harness.can_hold(where, row["name"])]
        self.assertGreater(len(names), 20)
        for name in names:
            self.harness.edit(where, name, "n\n")
        self.assertEqual(sorted(self.look(where)["unclean"]), sorted(names))

    def test_a_checkout_whose_own_path_is_awkward_is_looked_at_whole(self):
        where, head = self.harness.checkout({"a": "1\n"}, folder_name=AWKWARD_FOLDER)
        found = self.look(where)
        self.assertEqual((found["exists"], found["is_checkout"], found["head"]), (True, True, head))

    def test_a_plain_checkouts_git_folder_is_its_own_and_one_that_is_not_a_checkout_has_none(self):
        environment = place.git_environment(self.harness.environment()["PATH"])
        where, _ = self.harness.checkout({"a": "1\n"}, folder_name=AWKWARD_FOLDER)
        self.assertEqual(self.world.git.git_folders(where, environment), [f"{where}/.git"])
        self.assertEqual(self.world.git.git_folders(self.harness.folder(), environment), [])

    def test_a_repository_inside_the_place_is_nested_and_is_not_entered(self):
        where, _ = self.harness.checkout({"a": "1\n"})
        self.harness.nested_repository(where, "deep/inner")
        self.harness.nested_repository(where, "deep/inner/deeper")
        found = self.look(where)
        self.assertEqual(found["nested"], ["deep/inner"])

    def test_a_tracked_file_with_a_filter_attribute_is_named_and_nothing_else_is_looked_at(self):
        where, _ = self.harness.checkout({"a": "1\n", "data.big": "d\n"})
        self.harness.filter_attribute(where, "data.big")
        self.harness.edit(where, "new", "n\n")  # unclean, but not what is found
        found = self.look(where)
        self.assertEqual((found["filtered"], found["unclean"]), (["data.big"], []))

    def test_looking_changes_nothing_in_the_checkout_not_even_its_index(self):
        where, _ = self.harness.checkout({"a": "1\n", "b": "2\n"})
        self.harness.edit(where, "a", "changed\n")  # git would like to refresh its index now
        self.harness.edit(where, "new", "n\n")
        before = self.harness.everything_in(where)
        self.look(where)
        self.look(where)
        self.assertEqual(self.harness.everything_in(where), before)

    # --------------------------------------------------------------- git: freezing

    def freeze(self, where, opening, request_id="contract-1"):
        harness = self.harness
        command = place.freeze_argv(
            boundary.freeze_scope_name(request_id, self.world.identity.new_id()),
            60,
            where,
            opening,
            request_id,
        )
        return self.world.git.freeze(command, harness.freeze_environment())

    def frozen(self, where, opening):
        """(commit, added, changed, deleted) the freeze printed, or the failure."""
        answer = self.freeze(where, opening)
        self.assertEqual(answer.status, 0, answer)
        parsed = place.parse_freeze_output(answer.output)
        self.assertIsNotNone(parsed, answer)
        return parsed

    def test_files_that_are_as_they_were_freeze_to_the_opening_commit_itself_and_make_no_reference(
        self,
    ):
        self.harness.needs_the_freeze()
        where, head = self.harness.checkout({"a": "1\n", "b": "2\n"})
        self.assertEqual(self.frozen(where, head), (head, 0, 0, 0))
        self.assertEqual(self.harness.references(where), [])

    def test_a_new_a_changed_and_a_removed_file_are_counted_and_frozen_to_a_commit_on_a_reference_of_its_own(
        self,
    ):
        self.harness.needs_the_freeze()
        where, head = self.harness.checkout({"kept": "1\n", "changed": "1\n", "gone": "1\n"})
        self.harness.edit(where, "new one", "n\n")
        self.harness.edit(where, "new two", "n\n")
        self.harness.edit(where, "changed", "2\n")
        self.harness.remove(where, "gone")
        commit, added, changed, deleted = self.frozen(where, head)
        self.assertEqual((added, changed, deleted), (2, 1, 1))
        self.assertNotEqual(commit, head)
        self.assertEqual(
            self.harness.references(where), [("refs/shuttle/freeze/contract-1", commit)]
        )
        self.assertEqual(self.harness.parent_of(where, commit), head)
        self.assertEqual(
            sorted(self.harness.files_of(where, commit)), ["changed", "kept", "new one", "new two"]
        )

    def test_the_same_files_freeze_to_the_same_commit_whatever_the_history_says(self):
        self.harness.needs_the_freeze()
        where, head = self.harness.checkout({"a": "1\n"})
        self.harness.edit(where, "b", "2\n")
        first = self.frozen(where, head)
        self.harness.commit_everything(where)  # the places own history moves
        again = self.frozen(where, head)
        self.assertEqual(first, again)

    def test_every_name_the_filesystem_holds_is_counted_once_whole_and_frozen(self):
        self.harness.needs_the_freeze()
        where, head = self.harness.checkout({"seed": "x\n"})
        names = [row["name"] for row in HOLDABLE_NAMES if self.harness.can_hold(where, row["name"])]
        for name in names:
            self.harness.edit(where, name, "n\n")
        commit, added, _, _ = self.frozen(where, head)
        self.assertEqual(added, len(names))
        self.assertEqual(sorted(self.harness.files_of(where, commit)), sorted([*names, "seed"]))

    def test_a_freeze_of_a_place_that_is_not_a_checkout_or_not_there_fails(self):
        self.harness.needs_the_freeze()
        where, head = self.harness.checkout({"a": "1\n"})
        for gone in (self.harness.folder(), f"{self.harness.folder()}/absent"):
            with self.subTest(gone):
                answer = self.freeze(gone, head)
                self.assertNotEqual(answer.status, 0)
                self.assertIsNone(place.parse_freeze_output(answer.output))

    def test_a_freeze_with_an_opening_commit_the_place_does_not_have_fails(self):
        self.harness.needs_the_freeze()
        where, _ = self.harness.checkout({"a": "1\n"})
        answer = self.freeze(where, "f" * 40)
        self.assertNotEqual(answer.status, 0)
        self.assertIsNone(place.parse_freeze_output(answer.output))

    def test_a_freeze_whose_command_cannot_be_started_raises_os_error(self):
        self.assertRaisesExactly(
            FileNotFoundError,
            self.world.git.freeze,
            [f"{self.harness.folder()}/no-such-program"],
            {},
        )

    # ------------------------------------------------------------------ clock

    def test_the_steady_clock_does_not_go_back(self):
        first = self.world.clock.now()
        self.assertGreaterEqual(self.world.clock.now(), first)

    def test_a_timestamp_is_utc_iso_with_milliseconds(self):
        self.assertRegex(
            self.world.clock.timestamp(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$"
        )

    def test_a_later_timestamp_is_not_before_an_earlier_one(self):
        first = self.world.clock.timestamp()
        self.assertGreaterEqual(self.world.clock.timestamp(), first)

    # ---------------------------------------------------------------- signals

    def test_each_signal_calls_the_handler_with_its_name_and_the_undo_gives_the_old_handler_back(
        self,
    ):
        for name in HANDLED_SIGNALS:
            with self.subTest(name):
                earlier, mine = [], []
                self.harness.have_previous_handler(earlier.append)
                restore = self.world.signals.install(mine.append)
                self.harness.send(name)
                self.assertEqual((mine, earlier), ([name], []))
                restore()
                self.harness.send(name)
                self.assertEqual((mine, earlier), ([name], [name]))

    def test_a_signal_number_has_its_name_or_none(self):
        self.assertEqual(self.world.signals.name_of(15), "SIGTERM")
        self.assertEqual(self.world.signals.name_of(9), "SIGKILL")
        self.assertEqual(self.world.signals.name_of(2), "SIGINT")
        self.assertIsNone(self.world.signals.name_of(99999))
        for not_a_signal in (0, -2, -15):
            self.assertIsNone(self.world.signals.name_of(not_a_signal))

    # ------------------------------------------------- environment and identity

    def test_a_variable_that_is_set_reads_back_exactly_one_that_is_empty_reads_empty_and_one_that_is_not_set_reads_none(
        self,
    ):
        self.harness.set_variable("SHUTTLE_CONTRACT_SET", "a value = with \u00e9")
        self.harness.set_variable("SHUTTLE_CONTRACT_EMPTY", "")
        self.harness.set_variable("SHUTTLE_CONTRACT_PADDED", "  Mixed Case \t")
        read = self.world.environment.read_variable
        self.assertEqual(read("SHUTTLE_CONTRACT_SET"), "a value = with \u00e9")
        self.assertEqual(read("SHUTTLE_CONTRACT_EMPTY"), "")
        self.assertEqual(read("SHUTTLE_CONTRACT_PADDED"), "  Mixed Case \t")
        self.assertIsNone(read("shuttle_contract_set"))  # a name is not case-folded
        self.assertIsNone(read("SHUTTLE_CONTRACT_NOT_SET"))

    def test_the_host_name_is_exactly_the_one_the_harness_says_this_host_has(self):
        self.assertEqual(self.world.identity.host_name(), self.harness.host_name())

    def test_new_ids_are_32_lower_case_hex_digits_and_never_the_same_twice(self):
        ids = [self.world.identity.new_id() for _ in range(50)]
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids))
        self.assertEqual(len(set(ids)), 50)

    def test_the_account_folders_are_absolute_and_the_same_each_time(self):
        home, runtime = self.world.identity.home_folder(), self.world.identity.runtime_folder()
        if home is not None:  # an account may have none
            self.assertTrue(home.startswith("/"))
        self.assertTrue(runtime.startswith("/"))
        self.assertEqual(self.world.identity.home_folder(), home)
        self.assertEqual(self.world.identity.runtime_folder(), runtime)

    def test_the_account_folders_are_the_systems_and_not_what_the_environment_names(self):
        home, runtime = self.world.identity.home_folder(), self.world.identity.runtime_folder()
        self.harness.set_variable("HOME", "/somewhere/else")
        self.harness.set_variable("XDG_RUNTIME_DIR", "/elsewhere/too")
        self.assertEqual(self.world.identity.home_folder(), home)
        self.assertEqual(self.world.identity.runtime_folder(), runtime)

    def test_the_process_number_is_a_positive_whole_number_and_the_same_each_time(self):
        number = self.world.identity.process_number()
        self.assertIsInstance(number, int)
        self.assertGreater(number, 0)
        self.assertEqual(self.world.identity.process_number(), number)
