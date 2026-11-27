"""Git inside the box, in the place a run is really made in: a linked working copy of the
caller's repository, and in a plain checkout.

The git folders (the place's own and, for a linked working copy, the one it shares with the
checkout it was made from) are read-only at their real paths: git reads the history, and the
executor can change neither the configuration, the hooks nor the history. The working files stay
writable, and the closing freeze, which runs outside the box, records what the executor changed.
Nothing else of the repository the place was made from is shown, and its working files stay hidden.
"""

import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")
real_place = importlib.import_module("rehearsal.real_place")
flat = importlib.import_module("rehearsal.receipts").flat

# Runs git as the executor does (an identity given on the command line, as the empty home holds
# none), and reports each command's status. It also tries to write into each git folder git
# names: the configuration, a new file in the hooks folder and a new file beside them. Each
# attempt says whether it was allowed. It writes a working file, and says whether it can see the
# working files of the repository the place was made from (argv 2).
USES_GIT = """
import json, os, subprocess, sys
place, origin = sys.argv[1], sys.argv[2]
def git(*args):
    done = subprocess.run(["git", "-c", "user.name=exec", "-c", "user.email=exec@example.invalid",
                           "-C", place, *args], capture_output=True, text=True)
    return done.returncode, done.stdout.strip()
def tries_to_write(folder):
    allowed = {}
    for label, parts in (("config", ("config",)), ("hook", ("hooks", "pre-commit")),
                         ("new file", ("new-file",))):
        path = os.path.join(folder, *parts)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "a").write("[core]\\n")
            allowed[label] = True
        except OSError:
            allowed[label] = False
    return allowed
open(os.path.join(place, "made.txt"), "w").write("made by the executor\\n")
folders = {git("rev-parse", "--path-format=absolute", option)[1]
           for option in ("--absolute-git-dir", "--git-common-dir")}
seen = {
    "status": git("status", "--porcelain")[0],
    "diff": git("diff")[0],
    "log": git("log", "-1", "--format=%s"),
    "add": git("add", "-A")[0],
    "commit": git("commit", "-q", "-m", "the executor's commit")[0],
    "config": git("config", "--local", "user.name", "changed")[0],
    "folders": sorted(folders),
    "writes": {folder: tries_to_write(folder) for folder in sorted(folders)},
    "origin files visible": os.path.exists(os.path.join(origin, "kept.txt")),
}
json.dump(seen, open(os.path.join(place, "seen.json"), "w"))
"""


def text_of(path):
    with open(path) as f:
        return f.read()


class GitInTheBox(real_run.RealRun):
    def run_git_in(self, place, origin, folders_wanted):
        doc = self.document(self.script("uses-git.py", USES_GIT), [place, origin])
        doc["place"] = place
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(os.path.join(place, "seen.json")) as f:
            seen = json.load(f)
        self.assertEqual(seen["folders"], sorted(folders_wanted))  # both were tried
        return seen

    def assert_read_only(self, seen):
        self.assertEqual(
            (seen["status"], seen["diff"], seen["log"][0]), (0, 0, 0), "git read failed"
        )
        self.assertEqual(seen["log"][1], "the place")
        for what in ("add", "commit", "config"):
            self.assertNotEqual(seen[what], 0, f"git {what} worked in the box")
        for folder, writes in seen["writes"].items():
            self.assertEqual(writes, {"config": False, "hook": False, "new file": False}, folder)

    def test_a_linked_working_copy_reads_but_cannot_change_either_of_its_git_folders(self):
        origin = os.path.join(self.root, "callers-repo")
        real_place.make_checkout(origin, {"kept.txt": "kept\n"})
        place = os.path.join(self.root, "linked-place")
        head = real_place.make_linked_checkout(origin, place)
        own = os.path.realpath(real_place.git(place, "rev-parse", "--absolute-git-dir"))
        shared = os.path.join(os.path.realpath(origin), ".git")
        configuration = text_of(os.path.join(shared, "config"))
        seen = self.run_git_in(place, origin, [own, shared])
        self.assert_read_only(seen)
        self.assertIs(seen["origin files visible"], False)
        self.assertEqual(real_place.git(place, "rev-parse", "HEAD"), head)  # nothing was committed
        self.assertEqual(text_of(os.path.join(shared, "config")), configuration)
        self.assertFalse(os.path.exists(os.path.join(shared, "hooks", "pre-commit")))

    def test_a_linked_working_copy_can_still_change_its_files_and_the_freeze_records_them(self):
        origin = os.path.join(self.root, "callers-repo")
        real_place.make_checkout(origin, {"kept.txt": "kept\n"})
        place = os.path.join(self.root, "linked-place")
        real_place.make_linked_checkout(origin, place)
        own = os.path.realpath(real_place.git(place, "rev-parse", "--absolute-git-dir"))
        self.run_git_in(place, origin, [own, os.path.join(os.path.realpath(origin), ".git")])
        with open(os.path.join(place, "made.txt")) as f:
            self.assertEqual(f.read(), "made by the executor\n")
        after = flat(self.outcome()["receipt"])["execution"]["fingerprint_after"]
        self.assertEqual(real_place.git(place, "show", f"{after}:made.txt"), "made by the executor")
        saw = flat(self.outcome()["receipt"])["execution"]
        self.assertGreaterEqual(saw["files_added"], 1)

    def test_a_plain_checkout_reads_but_cannot_change_its_git_folder(self):
        place = os.path.join(self.root, "plain-place")
        head = real_place.make_checkout(place, {"kept.txt": "kept\n"})
        git_folder = os.path.join(os.path.realpath(place), ".git")
        configuration = text_of(os.path.join(git_folder, "config"))
        seen = self.run_git_in(place, os.path.join(self.root, "nowhere"), [git_folder])
        self.assert_read_only(seen)
        self.assertEqual(real_place.git(place, "rev-parse", "HEAD"), head)
        self.assertEqual(text_of(os.path.join(git_folder, "config")), configuration)
        with open(os.path.join(place, "made.txt")) as f:
            self.assertEqual(f.read(), "made by the executor\n")
