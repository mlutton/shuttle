"""Git inside the box, in the place a run is really made in: a linked working copy of the
caller's repository, and in a plain checkout.

Nothing else of the repository the place was made from is shown, and its working files stay
hidden.
"""

import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")
real_place = importlib.import_module("rehearsal.real_place")

# Runs git as the executor does (an identity given on the command line, as the empty home holds
# none) and reports each command's status, the commit it made, and whether it can see the
# working files of the repository the place was made from (argv 2).
USES_GIT = """
import json, os, subprocess, sys
place, origin = sys.argv[1], sys.argv[2]
def git(*args):
    done = subprocess.run(["git", "-c", "user.name=exec", "-c", "user.email=exec@example.invalid",
                           "-C", place, *args], capture_output=True, text=True)
    return done.returncode, done.stdout.strip()
seen = {"status": git("status", "--porcelain")[0]}
open(os.path.join(place, "made.txt"), "w").write("made by the executor\\n")
seen["add"] = git("add", "-A")[0]
seen["commit"] = git("commit", "-q", "-m", "the executor's commit")[0]
seen["log"] = git("log", "-1", "--format=%s")
seen["origin files visible"] = os.path.exists(os.path.join(origin, "kept.txt"))
json.dump(seen, open(os.path.join(place, "seen.json"), "w"))
"""


class GitInTheBox(real_run.RealRun):
    def run_git_in(self, place, origin):
        doc = self.document(self.script("uses-git.py", USES_GIT), [place, origin])
        doc["place"] = place
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(os.path.join(place, "seen.json")) as f:
            return json.load(f)

    def test_status_add_and_commit_work_in_a_linked_working_copy_and_its_origin_stays_hidden(self):
        origin = os.path.join(self.root, "callers-repo")
        real_place.make_checkout(origin, {"kept.txt": "kept\n"})
        place = os.path.join(self.root, "linked-place")
        head = real_place.make_linked_checkout(origin, place)
        seen = self.run_git_in(place, origin)
        self.assertEqual(
            (seen["status"], seen["add"], seen["commit"]), (0, 0, 0), "git failed in the box"
        )
        self.assertEqual(seen["log"], [0, "the executor's commit"])
        self.assertIs(seen["origin files visible"], False)
        self.assertNotEqual(real_place.git(place, "rev-parse", "HEAD"), head)  # the commit is real

    def test_the_same_in_a_plain_checkout(self):
        place = os.path.join(self.root, "plain-place")
        real_place.make_checkout(place, {"kept.txt": "kept\n"})
        seen = self.run_git_in(place, os.path.join(self.root, "nowhere"))
        self.assertEqual((seen["status"], seen["add"], seen["commit"]), (0, 0, 0))
