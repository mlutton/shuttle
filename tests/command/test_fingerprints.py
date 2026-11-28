"""The command seam: the place and the two fingerprints, through the real command.

Each test makes a real git checkout for the place, runs the real command on a script in the
real boundary, and reads what a caller can see: the outcome record, the printed lines and the
place's repository. The freeze runs in a scope of its own, so these skip, saying why, on a
machine without the boundary.
"""

import importlib
import json
import os
import select
import stat
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")
real_place = importlib.import_module("rehearsal.real_place")
flat = importlib.import_module("rehearsal.receipts").flat

# Changes the place in the three ways: adds, changes, deletes.
CHANGES_THE_PLACE = """
import os, sys
place = sys.argv[1]
open(os.path.join(place, "added one.txt"), "w").write("new\\n")
open(os.path.join(place, "added two.txt"), "w").write("new\\n")
open(os.path.join(place, "changed.txt"), "w").write("different\\n")
os.remove(os.path.join(place, "deleted.txt"))
"""

WRITES_NOTHING_IN_THE_PLACE = """
import sys
open(sys.argv[2], "w").write("started")
"""

# Tries to commit a change in the place, which the box refuses (the git folder is read-only), says
# on the witness file what git answered (the exit codes of the add and of the commit), then writes
# a file.
TRIES_TO_COMMIT_AND_IS_REFUSED = """
import os, subprocess, sys
place = sys.argv[1]
def git(*args):
    return subprocess.run(["git", "-c", "user.name=exec", "-c", "user.email=exec@example.invalid",
                           "-C", place, *args], capture_output=True).returncode
open(os.path.join(place, "changed.txt"), "w").write("written by the executor\\n")
added = git("add", "-A")
committed = git("commit", "-q", "-m", "the executor's own commit")
open(sys.argv[2], "w").write(f"{added} {committed}")
open(os.path.join(place, "later.txt"), "w").write("not committed\\n")
"""

# The freeze's edge cases, one script each (see FreezeEdgeCases).
LEAVES_A_FILE_NOBODY_CAN_READ = """
import os, sys
path = os.path.join(sys.argv[1], "secret.txt")
open(path, "w").write("hidden\\n")
os.chmod(path, 0)
"""

LEAVES_A_FOLDER_NOBODY_CAN_ENTER = """
import os, sys
folder = os.path.join(sys.argv[1], "d")
os.mkdir(folder)
open(os.path.join(folder, "f"), "w").write("hidden\\n")
os.chmod(folder, 0)
"""

CLONES_A_REPOSITORY_INTO_THE_PLACE = """
import os, subprocess, sys
inner = os.path.join(sys.argv[1], "cloned")
os.mkdir(inner)
def git(*args):
    subprocess.run(["git", "-c", "user.name=exec", "-c", "user.email=exec@example.invalid",
                    "-C", inner, *args], check=True, capture_output=True)
git("init", "-q", "-b", "main")
open(os.path.join(inner, "inside.txt"), "w").write("in the clone\\n")
git("add", "-A")
git("commit", "-q", "-m", "the clone")
"""

# Links that point outside the place: to a folder nobody can enter, to a file, to nothing.
MAKES_LINKS_THAT_POINT_OUTSIDE = """
import os, sys
place, folder = sys.argv[1], sys.argv[3]
os.symlink(folder, os.path.join(place, "to-a-folder"))
os.symlink(os.path.join(folder, "secret"), os.path.join(place, "to-a-file"))
os.symlink("/nowhere/at/all", os.path.join(place, "to-nothing"))
"""

# A file of this many bytes, made as a hole (it takes no room on the disk, and git still reads
# every byte of it): large enough to be the file that is too large for anything that reads a
# file whole into a small buffer (a pipe holds 64 KiB), small enough that hashing it takes a
# fraction of a second, and under the 16 MB file limit every real-command test runs with.
VERY_LARGE = 15 * 1024 * 1024

MAKES_A_VERY_LARGE_FILE = """
import os, sys
with open(os.path.join(sys.argv[1], "very large.bin"), "wb") as f:
    f.truncate(int(sys.argv[3]))
"""

FILES = {"kept.txt": "kept\n", "changed.txt": "before\n", "deleted.txt": "gone soon\n"}


def outcome_fields(case, request_id="r-1"):
    return flat(case.outcome(request_id)["receipt"])


class FingerprintCase(real_run.RealRun):
    def setUp(self):
        super().setUp()
        # a linked working copy of a repository of the caller's: the shape the place has
        self.main = os.path.join(self.root, "callers-repo")
        real_place.make_checkout(self.main, FILES)
        self.place = os.path.join(self.root, "linked")
        self.head = real_place.make_linked_checkout(self.main, self.place)
        # The executor writes its place, so a script says it ran by writing a file there. The repository's own ignore list keeps
        # that file out of the fingerprints and the counts these tests read.
        self.witness = os.path.join(self.place, "witness")
        self.ignore_the_witness()

    def ignore_the_witness(self):
        with open(os.path.join(self.main, ".git", "info", "exclude"), "a") as f:
            f.write("witness\n")

    def git(self, *arguments, where=None):
        return real_place.git(where or self.place, *arguments)

    def names_in(self, commit):
        """The names of the files a commit holds, whole and sorted."""
        done = subprocess.run(
            ["git", "-C", self.place, "ls-tree", "-r", "--name-only", "-z", commit],
            env=real_place.environment(),
            capture_output=True,
            check=True,
        )
        return sorted(os.fsdecode(name) for name in done.stdout.split(b"\0") if name)

    def document_for(self, text, arguments=(), **extra):
        doc = self.document(
            self.script("script.py", text), [self.place, self.witness, *arguments], **extra
        )
        doc["place"] = self.place
        return doc

    def finished(self, doc, variables=None):
        code, lines, err = self.run_to_the_end(doc, variables=variables)
        self.assertEqual((code, err), (0, ""), lines)
        return lines

    def callers_state(self):
        """What the caller can see of their repository, other than the reference of Shuttle's own."""
        gitdir = self.git("rev-parse", "--absolute-git-dir")
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir")

        def read(path):
            with open(path, "rb") as f:
                return f.read()

        return {
            "references": self.git("for-each-ref", "--exclude=refs/shuttle", where=self.main),
            "head of the place": self.git("symbolic-ref", "HEAD"),
            "index of the place": read(os.path.join(gitdir, "index")),
            "settings": read(os.path.join(common, "config")),
            "index of the repository": read(os.path.join(self.main, ".git", "index")),
            "status": self.git("status", "--porcelain=v1"),
        }


class AScriptThatChangesNothing(FingerprintCase):
    def test_gives_equal_fingerprints_and_the_receipt_says_it_changed_nothing(self):
        lines = self.finished(self.document_for(WRITES_NOTHING_IN_THE_PLACE))
        self.assertEqual(lines[-1], "ended_by_itself")
        saw = outcome_fields(self)["execution"]
        self.assertEqual(
            (saw["fingerprint_before"], saw["fingerprint_after"]), (self.head, self.head)
        )
        self.assertIs(saw["changed_nothing"], True)
        self.assertEqual(
            (saw["files_added"], saw["files_changed"], saw["files_deleted"]), (0, 0, 0)
        )
        self.assertEqual(self.git("for-each-ref", "refs/shuttle"), "")  # nothing was made


class AScriptThatAddsChangesAndDeletes(FingerprintCase):
    def test_gives_matching_counts_one_commit_of_the_working_files_and_leaves_the_callers_things_alone(
        self,
    ):
        before = self.callers_state()
        self.finished(self.document_for(CHANGES_THE_PLACE))
        saw = outcome_fields(self)["execution"]
        self.assertEqual(
            (saw["files_added"], saw["files_changed"], saw["files_deleted"]), (2, 1, 1)
        )
        self.assertIs(saw["changed_nothing"], False)
        self.assertEqual(saw["fingerprint_before"], self.head)
        after = saw["fingerprint_after"]
        self.assertNotEqual(after, self.head)
        # the commit is on a reference of Shuttle's own, whose parent is the opening commit
        self.assertEqual(
            self.git("for-each-ref", "refs/shuttle", "--format=%(refname) %(objectname)"),
            f"refs/shuttle/freeze/r-1 {after}",
        )
        self.assertEqual(self.git("rev-parse", f"{after}^"), self.head)
        self.assertEqual(
            self.names_in(after), ["added one.txt", "added two.txt", "changed.txt", "kept.txt"]
        )
        self.assertEqual(self.git("show", f"{after}:changed.txt"), "different")
        # the caller's branch, index and settings are as they were; the script's changes are
        # still in the place, not committed, not staged
        self.assertEqual(self.callers_state()["references"], before["references"])
        for name in (
            "head of the place",
            "index of the place",
            "settings",
            "index of the repository",
        ):
            self.assertEqual(self.callers_state()[name], before[name], name)
        self.assertEqual(
            self.git("status", "--porcelain=v1").splitlines(),
            ["M changed.txt", " D deleted.txt", '?? "added one.txt"', '?? "added two.txt"'],
        )


class TheClosingCommit(FingerprintCase):
    def test_is_made_by_execution_under_a_neutral_identity_with_no_hooks_no_signing_and_no_prompts(
        self,
    ):
        # Everything a caller could configure to get in the way: in the place's own settings, in
        # the global ones the command would read, and in hooks.
        hooks = os.path.join(self.root, "hooks")
        os.mkdir(hooks)
        marker = os.path.join(self.root, "a-hook-ran")
        for name in (
            "pre-commit",
            "commit-msg",
            "post-commit",
            "reference-transaction",
            "pre-push",
        ):
            path = os.path.join(hooks, name)
            with open(path, "w") as f:
                f.write(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        for key, value in (
            ("core.hooksPath", hooks),
            ("commit.gpgsign", "true"),
            ("gpg.program", "/nonexistent/gpg"),
            ("user.name", "The Caller"),
            ("user.email", "caller@example.invalid"),
            ("core.autocrlf", "true"),
        ):
            self.git("config", "--local", key, value, where=self.main)
        globals_ = os.path.join(self.root, "global-config")
        with open(globals_, "w") as f:
            f.write(f"[commit]\n\tgpgsign = true\n[core]\n\thooksPath = {hooks}\n")
        self.finished(
            self.document_for(CHANGES_THE_PLACE),
            variables={
                "GIT_CONFIG_GLOBAL": globals_,
                "GIT_AUTHOR_NAME": "Someone Else",
                "GIT_COMMITTER_EMAIL": "else@example.invalid",
                "GIT_DIR": os.path.join(self.root, "not-this-one"),
                "GIT_INDEX_FILE": os.path.join(self.root, "not-this-index"),
                "GIT_TERMINAL_PROMPT": "1",
            },
        )
        saw = outcome_fields(self)
        self.assertEqual(saw["ending"]["ending"], "ended_by_itself")
        after = saw["execution"]["fingerprint_after"]
        shown = self.git("log", "-1", "--format=%an|%ae|%cn|%ce|%ad|%cd|%G?", "--date=raw", after)
        self.assertEqual(shown, "Shuttle||Shuttle||946684800 +0000|946684800 +0000|N")
        self.assertFalse(os.path.exists(marker), "a hook ran")
        self.assertIn("r-1", self.git("log", "-1", "--format=%s", after))
        self.assertEqual(self.git("rev-parse", f"{after}^"), self.head)


class AScriptWhoseCommitTheBoxRefuses(FingerprintCase):
    def test_is_refused_the_commit_and_the_closing_fingerprint_still_tracks_the_working_files(self):
        self.finished(self.document_for(TRIES_TO_COMMIT_AND_IS_REFUSED))
        with open(self.witness) as f:
            added, committed = f.read().split()
        self.assertNotEqual(committed, "0", "the box let the commit through")
        self.assertNotEqual(added, "0", "the box let the index be written")
        executors_commit = self.git("rev-parse", "HEAD")
        self.assertEqual(executors_commit, self.head)  # the script's commit was refused
        saw = outcome_fields(self)["execution"]
        self.assertEqual(saw["fingerprint_before"], self.head)
        self.assertNotIn(saw["fingerprint_after"], (self.head, executors_commit))
        self.assertEqual(self.git("rev-parse", f"{saw['fingerprint_after']}^"), self.head)
        # the files as they are, both counted against the opening commit: the changed one the
        # commit would have held and the one never committed
        self.assertEqual(
            (saw["files_added"], saw["files_changed"], saw["files_deleted"]), (1, 1, 0)
        )
        self.assertEqual(self.git("show", f"{saw['fingerprint_after']}:later.txt"), "not committed")


class APlaceThatCannotBeRunOn(FingerprintCase):
    def rows(self):
        """(label, make the place so, reason): one per refusal the place can give."""
        outside = os.path.join(self.root, "elsewhere")

        def not_there():
            return os.path.join(self.root, "no-such-place")

        def not_a_checkout():
            os.mkdir(outside)
            return outside

        def inside_a_checkout():
            real_place.write(self.place, "inner-folder/x", "x\n")
            real_place.commit_everything(self.place)
            return os.path.join(self.place, "inner-folder")

        def empty_repository():
            os.mkdir(outside)
            self.git("init", "-q", where=outside)
            return outside

        def changed():
            with open(os.path.join(self.place, "kept.txt"), "w") as f:
                f.write("edited\n")
            return self.place

        def staged():
            real_place.write(self.place, "staged.txt", "s\n")
            self.git("add", "staged.txt")
            return self.place

        def new_file():
            real_place.write(self.place, "new.txt", "n\n")
            return self.place

        def removed():
            os.remove(os.path.join(self.place, "kept.txt"))
            return self.place

        def nested():
            inner = os.path.join(self.place, "vendor", "inner")
            os.makedirs(inner)
            real_place.make_checkout(inner)
            return self.place

        return [
            ("the place is not there", not_there, "place_missing"),
            (
                "the place is a folder that is not a checkout",
                not_a_checkout,
                "place_not_a_git_checkout",
            ),
            (
                "the place is a folder inside a checkout",
                inside_a_checkout,
                "place_not_a_git_checkout",
            ),
            (
                "the place is a repository with no commit",
                empty_repository,
                "place_not_a_git_checkout",
            ),
            ("a committed file was changed", changed, "place_has_uncommitted_changes"),
            ("a change is staged", staged, "place_has_uncommitted_changes"),
            ("a new unignored file is there", new_file, "place_has_uncommitted_changes"),
            ("a committed file was removed", removed, "place_has_uncommitted_changes"),
            ("a repository is nested in it", nested, "place_has_nested_repository"),
        ]

    def test_is_refused_before_anything_starts_and_the_check_form_says_the_same(self):
        for number in range(len(self.rows())):
            self.setUp()  # a fresh root and checkout for each row
            label, make, reason = self.rows()[number]
            with self.subTest(label):
                doc = self.document_for(WRITES_NOTHING_IN_THE_PLACE)
                doc["place"] = make()
                code, lines, err = self.run_to_the_end(doc)
                self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
                found = outcome_fields(self)["ending"]
                self.assertEqual(
                    (found["ending"], found["reason"], found["failed_step"]),
                    ("could_not_start", reason, "input_check"),
                )
                self.assertFalse(os.path.exists(self.witness), "the executor started")
                self.assertEqual(outcome_fields(self)["execution"]["fingerprint_before"], "none")
                # the check form: the same verdict, and it writes nothing
                doc["request_id"] = "r-check"
                path = os.path.join(self.root, "check.json")
                with open(path, "w") as f:
                    json.dump(doc, f)
                checked = subprocess.run(
                    [sys.executable, "-m", "shuttle", "check", path],
                    cwd=real_run.REPO,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(checked.stdout.splitlines()[-2], f"check: refused: {reason}")
                self.assertFalse(os.path.exists(os.path.join(self.records, "r-check.request.json")))

    def test_an_ignored_file_does_not_make_the_place_unclean_and_is_not_frozen(self):
        real_place.write(self.place, ".gitignore", "*.log\n")
        real_place.commit_everything(self.place)
        head = self.git("rev-parse", "HEAD")
        real_place.write(self.place, "left-over.log", "ignored\n")  # there before the run
        script = (
            "import os, sys\n"
            "open(os.path.join(sys.argv[1], 'run.log'), 'w').write('ignored')\n"
            "open(os.path.join(sys.argv[1], 'run.txt'), 'w').write('counted')\n"
        )
        self.finished(self.document_for(script))
        saw = outcome_fields(self)["execution"]
        self.assertEqual(saw["fingerprint_before"], head)
        self.assertEqual(saw["files_added"], 1)
        self.assertEqual(
            self.names_in(saw["fingerprint_after"]),
            [".gitignore", "changed.txt", "deleted.txt", "kept.txt", "run.txt"],
        )


class AFailedFreeze(FingerprintCase):
    def test_is_execution_failed_with_the_opening_fingerprint_only_and_no_closing_commit(self):
        script = (
            "import os, shutil, sys\n"
            "os.remove(os.path.join(sys.argv[1], '.git'))\n"  # a linked working copy's .git is a file
        )
        code, lines, err = self.run_to_the_end(self.document_for(script))
        self.assertEqual((code, err, lines[-1]), (0, "", "execution_failed"))
        found = outcome_fields(self)
        self.assertEqual(
            tuple(found["ending"][k] for k in ("ending", "reason", "failed_step")),
            ("execution_failed", "closing_freeze_failed", "closing_freeze"),
        )
        saw = found["execution"]
        self.assertEqual(saw["fingerprint_before"], self.head)
        for field in (
            "fingerprint_after",
            "changed_nothing",
            "files_added",
            "files_changed",
            "files_deleted",
        ):
            self.assertEqual(saw[field], "cannot tell", field)
        self.assertIn("closing freeze failed", found["ending"]["reason_text"])
        self.assertEqual(self.units_left(), [])


class FreezeEdgeCases(FingerprintCase):
    """What the freeze does with files that are hard to freeze. The spec asks for a row for each
    and does not say what must happen; each row pins what does happen, to be decided."""

    def test_a_file_that_cannot_be_read_fails_the_freeze_and_nothing_is_left_half_done(self):
        if os.geteuid() == 0:
            self.skipTest("a file mode cannot keep a file from the superuser")
        code, lines, err = self.run_to_the_end(self.document_for(LEAVES_A_FILE_NOBODY_CAN_READ))
        self.assertEqual((code, err, lines[-1]), (0, "", "execution_failed"))
        found = outcome_fields(self)
        self.assertEqual(found["ending"]["reason"], "closing_freeze_failed")
        self.assertEqual(found["execution"]["fingerprint_before"], self.head)
        self.assertEqual(found["execution"]["fingerprint_after"], "cannot tell")
        self.assertEqual(self.git("for-each-ref", "refs/shuttle"), "")

    def test_a_folder_that_cannot_be_entered_fails_the_freeze_as_an_unreadable_file_does(self):
        if os.geteuid() == 0:
            self.skipTest("a file mode cannot keep a folder from the superuser")
        folder = os.path.join(self.place, "d")
        self.addCleanup(lambda: os.path.isdir(folder) and os.chmod(folder, 0o700))
        code, lines, err = self.run_to_the_end(self.document_for(LEAVES_A_FOLDER_NOBODY_CAN_ENTER))
        self.assertEqual((code, err, lines[-1]), (0, "", "execution_failed"))
        found = outcome_fields(self)
        self.assertEqual(found["ending"]["reason"], "closing_freeze_failed")
        self.assertEqual(found["execution"]["fingerprint_after"], "cannot tell")
        self.assertEqual(self.git("for-each-ref", "refs/shuttle"), "")

    def test_a_repository_cloned_into_the_place_is_frozen_as_one_entry_that_names_its_commit(self):
        self.finished(self.document_for(CLONES_A_REPOSITORY_INTO_THE_PLACE))
        saw = outcome_fields(self)["execution"]
        self.assertEqual(
            (saw["files_added"], saw["files_changed"], saw["files_deleted"]), (1, 0, 0)
        )
        entry = self.git("ls-tree", saw["fingerprint_after"], "cloned")
        self.assertTrue(entry.startswith("160000 commit "), entry)  # a link to its commit
        self.assertEqual(self.names_in(saw["fingerprint_after"]), sorted([*FILES, "cloned"]))

    def test_links_that_point_outside_the_place_are_frozen_as_links_and_nothing_outside_is_read(
        self,
    ):
        folder = os.path.join(self.root, "outside")
        os.mkdir(folder)
        real_place.write(folder, "secret", "outside the place\n")
        os.chmod(folder, 0)  # nobody can enter it: a freeze that followed the link would fail
        self.addCleanup(os.chmod, folder, 0o700)
        self.finished(self.document_for(MAKES_LINKS_THAT_POINT_OUTSIDE, [folder]))
        saw = outcome_fields(self)["execution"]
        self.assertEqual(saw["files_added"], 3)
        after = saw["fingerprint_after"]
        for name, target in (
            ("to-a-folder", folder),
            ("to-a-file", os.path.join(folder, "secret")),
            ("to-nothing", "/nowhere/at/all"),
        ):
            self.assertTrue(self.git("ls-tree", after, name).startswith("120000 blob "), name)
            self.assertEqual(self.git("cat-file", "blob", f"{after}:{name}"), target)

    def test_a_very_large_file_is_frozen_whole_like_any_other(self):
        self.finished(self.document_for(MAKES_A_VERY_LARGE_FILE, [str(VERY_LARGE)]))
        saw = outcome_fields(self)["execution"]
        self.assertEqual(saw["files_added"], 1)
        self.assertEqual(
            self.git("cat-file", "-s", f"{saw['fingerprint_after']}:very large.bin"),
            str(VERY_LARGE),
        )


class AFreezeThatRunsOutOfItsLimit(FingerprintCase):
    def test_is_a_failed_closing_freeze_though_the_executors_own_limit_was_far_off(self):
        doc = self.document_for(WRITES_NOTHING_IN_THE_PLACE)
        doc["freeze_limit_seconds"] = 1e-6  # the scope's shortest limit: it ends the freeze at once
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "execution_failed"))
        found = outcome_fields(self)
        self.assertEqual(found["ending"]["reason"], "closing_freeze_failed")
        self.assertIn("limit", found["ending"]["reason_text"])
        self.assertEqual(found["execution"]["fingerprint_after"], "cannot tell")
        self.assertEqual(self.units_left(), [])


class FilterDrivers(FingerprintCase):
    """No command from any configuration runs in Shuttle's git work, and a place that depends on
    a filter driver is refused. The rule awaits the owner."""

    def setUp(self):
        super().setUp()
        self.marker = os.path.join(self.root, "marker-a-driver-ran")

    def define_driver(self, config_path, name, kind="clean"):
        """A driver whose command makes the marker, then (clean) changes what it is given."""
        command = f"touch '{self.marker}'; sed 's/^/FILTERED:/'"
        with open(config_path, "a") as f:
            f.write(f'[filter "{name}"]\n\t{kind} = {command}\n')

    def commit_a_filtered_file(self):
        real_place.write(self.place, ".gitattributes", "*.big filter=big\n")
        real_place.write(self.place, "data.big", "content\n")
        return real_place.commit_everything(self.place)

    def assert_refused_for_a_filter(self, doc, variables=None):
        code, lines, err = self.run_to_the_end(doc, variables=variables)
        self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
        found = outcome_fields(self)["ending"]
        self.assertEqual(
            (found["reason"], found["failed_step"]), ("place_has_filter_attribute", "input_check")
        )
        self.assertIn("filter drivers are not supported", found["reason_text"])
        self.assertIn("data.big", found["reason_text"])
        self.assertFalse(os.path.exists(self.witness), "the executor started")
        self.assertFalse(os.path.exists(self.marker), "a driver ran")

    def test_a_driver_in_the_repositorys_own_configuration_refuses_the_place_and_never_runs(self):
        self.commit_a_filtered_file()
        self.define_driver(os.path.join(self.main, ".git", "config"), "big")
        doc = self.document_for(WRITES_NOTHING_IN_THE_PLACE)
        self.assert_refused_for_a_filter(doc)
        # the check form agrees
        doc["request_id"] = "r-check"
        path = os.path.join(self.root, "check.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        checked = subprocess.run(
            [sys.executable, "-m", "shuttle", "check", path],
            cwd=real_run.REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            checked.stdout.splitlines()[-2], "check: refused: place_has_filter_attribute"
        )
        self.assertFalse(os.path.exists(self.marker), "a driver ran")

    def test_an_attribute_in_the_repositorys_info_file_refuses_the_place_too(self):
        self.define_driver(os.path.join(self.main, ".git", "config"), "big")
        real_place.write(self.place, "data.big", "content\n")
        real_place.commit_everything(self.place)
        info = os.path.join(self.main, ".git", "info")
        os.makedirs(info, exist_ok=True)
        with open(os.path.join(info, "attributes"), "w") as f:
            f.write("*.big filter=big\n")
        self.assert_refused_for_a_filter(self.document_for(WRITES_NOTHING_IN_THE_PLACE))

    def test_a_driver_in_the_global_configuration_refuses_the_place_fresh_or_settled(self):
        globals_ = os.path.join(self.root, "global-config")
        self.define_driver(globals_, "big")
        self.commit_a_filtered_file()
        data = os.path.join(self.place, "data.big")
        for label, when in (("fresh", 4_000_000_000), ("settled", 1_000_000_000)):
            with self.subTest(label):
                os.utime(data, (when, when))  # newer than the index (racy), or long before it
                real_place.git(self.place, "update-index", "--refresh")
                self.assert_refused_for_a_filter(
                    self.document_for(WRITES_NOTHING_IN_THE_PLACE),
                    variables={"GIT_CONFIG_GLOBAL": globals_},
                )
                os.remove(os.path.join(self.records, "r-1.outcome.json"))
                os.remove(os.path.join(self.records, "r-1.request.json"))

    def test_drivers_planted_from_outside_the_box_during_the_run_are_never_run(self):
        # The box keeps the executor out of the git folders, but a gate has no box and could plant
        # configuration there. So the test plays that part: the script says it is up, the test
        # (outside the box, after the opening freeze) defines a clean driver named by the
        # .gitattributes the script then writes, and a process driver named by info/attributes,
        # then lets the script go on; the closing freeze must not run either.
        up, go = self.pipe("up"), self.pipe("go")
        script = (
            "import os, sys\n"
            "place, up, go = sys.argv[1], sys.argv[3], sys.argv[4]\n"
            "open(up, 'w').write('u')\n"
            "descriptor = os.open(go, os.O_RDWR)\n"
            "os.read(descriptor, 1)\n"
            "open(os.path.join(place, '.gitattributes'), 'w').write('*.txt filter=x\\n')\n"
            "open(os.path.join(place, 'new.txt'), 'w').write('as written\\n')\n"
            "open(os.path.join(place, 'new.dat'), 'w').write('as written\\n')\n"
        )
        proc = self.start(self.document_for(script, [up, go]))
        said = os.open(up, os.O_RDWR)  # read and write, so it never sees an end of file
        ended = os.pidfd_open(proc.pid)
        try:
            ready, _, _ = select.select([said, ended], [], [])
            if said not in ready:
                stdout, stderr = proc.communicate(timeout=120)
                self.fail(f"the command ended before the script was up: {stdout!r} {stderr!r}")
        finally:
            os.close(said)
            os.close(ended)
        config = os.path.join(self.main, ".git", "config")
        self.define_driver(config, "x", "clean")
        self.define_driver(config, "p", "process")
        info = os.path.join(self.main, ".git", "info")
        os.makedirs(info, exist_ok=True)
        with open(os.path.join(info, "attributes"), "w") as f:
            f.write("*.dat filter=p\n")
        let_go = os.open(go, os.O_RDWR)
        os.write(let_go, b"g")
        os.close(let_go)
        stdout, stderr = proc.communicate(timeout=120)
        self.assertEqual((proc.returncode, stderr), (0, ""), stdout)
        self.assertFalse(os.path.exists(self.marker), "a driver ran")
        saw = outcome_fields(self)["execution"]
        self.assertEqual(
            (saw["files_added"], saw["files_changed"], saw["files_deleted"]), (3, 0, 0)
        )
        for name in ("new.txt", "new.dat"):  # the bytes on disk
            self.assertEqual(self.git("show", f"{saw['fingerprint_after']}:{name}"), "as written")
        self.assertEqual(sorted(os.listdir(self.records)), ["r-1.outcome.json", "r-1.request.json"])


PRINTS_ITS_WORKING_DIRECTORY = """
import os, sys
open(sys.argv[2], "w").write(os.getcwd())
"""


class TheExecutorsWorkingDirectory(FingerprintCase):
    def test_is_the_place(self):
        self.finished(self.document_for(PRINTS_ITS_WORKING_DIRECTORY))
        with open(self.witness) as f:
            self.assertEqual(f.read(), os.path.realpath(self.place))


if __name__ == "__main__":
    unittest.main()
