"""A tool's login reaches it by copy: it may replace the copy as the real tool does, and the
original is as it was.

The program that stands in for the tool is written and run by `run_a_stand_in_tool`
(tests/rehearsal/real_run.py). The login is made-up text; no test opens a real one. The stand-in
saves a refreshed login the way the real tool does (a temporary file beside it, then a rename over
it, with a lock file in the same folder).
"""

import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")

ORIGINAL = "a made-up stand-in, not a login\n"
REFRESHED = "a refreshed made-up stand-in\n"

STAND_IN = f"""
import json, os, sys
sys.stdin.read()
home = os.environ["CODEX_HOME"]
login = os.path.join(home, "auth.json")
seen = {{"login at start": open(login).read(), "is a link": os.path.islink(login)}}
# the tool's own way of saving a login: a lock file and a temporary file beside it, then a rename
open(os.path.join(home, "auth.json.lock"), "w").close()
temporary = os.path.join(home, ".auth-temporary")
open(temporary, "w").write({REFRESHED!r})
os.rename(temporary, login)
seen["login after"] = open(login).read()
seen["home"] = os.environ["HOME"]
json.dump(seen, open(os.path.join(os.getcwd(), "seen.json"), "w"))
arguments = sys.argv[1:]
sys.stdout.write('{{"type":"thread.started","thread_id":"t"}}\\n')
open(arguments[arguments.index("-o") + 1], "w").write("Done.")
"""


class AToolThatReplacesItsLogin(real_run.RealRun):
    def make_the_login(self, as_a_link=False):
        """The caller's login (made-up text) where the driver says it is; kept elsewhere and
        linked to when `as_a_link`. Returns the driver, the home, the login's path and the file that holds the text."""
        driver = real_run.tool_driver_names()[0]
        home = os.path.join(self.root, "callers-home")
        login = real_run.table.DRIVERS[driver].login_path({"HOME": home})
        os.makedirs(os.path.dirname(login))
        kept = os.path.join(self.root, "kept-elsewhere") if as_a_link else login
        with open(kept, "w") as f:
            f.write(ORIGINAL)
        os.chmod(kept, 0o600)
        if as_a_link:
            os.symlink(kept, login)
        return driver, home, login, kept

    def test_a_login_that_is_a_link_is_copied_as_the_file_it_leads_to_and_both_are_unchanged(self):
        driver, home, login, kept = self.make_the_login(as_a_link=True)
        doc = self.document(self.script("unused.py", ""))
        doc["executor"] = {"name": driver, "settings": {"model": "example-model"}}
        doc["network"], doc["changes_to_place"] = "off", "allowed"
        code, lines, err = self.run_a_stand_in_tool(doc, STAND_IN, {"HOME": home})
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(os.path.join(self.place, "seen.json")) as f:
            seen = json.load(f)
        self.assertEqual((seen["login at start"], seen["login after"]), (ORIGINAL, REFRESHED))
        self.assertIs(seen["is a link"], False)
        self.assertTrue(os.path.islink(login))  # the link is as it was
        with open(kept) as f:
            self.assertEqual(f.read(), ORIGINAL)

    def test_the_replacement_works_and_the_original_is_unchanged_after_the_run(self):
        driver, home, login, _ = self.make_the_login()
        doc = self.document(self.script("unused.py", ""))
        doc["executor"] = {"name": driver, "settings": {"model": "example-model"}}
        doc["network"], doc["changes_to_place"] = "off", "allowed"
        code, lines, err = self.run_a_stand_in_tool(doc, STAND_IN, {"HOME": home})
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(os.path.join(self.place, "seen.json")) as f:
            seen = json.load(f)
        self.assertEqual(seen["login at start"], ORIGINAL)  # it arrived
        self.assertIs(seen["is a link"], False)  # as a copy, in a folder it can write
        self.assertEqual(seen["login after"], REFRESHED)  # and the rename over it worked
        self.assertNotEqual(seen["home"], home)  # its own home, not the caller's
        with open(login) as f:
            self.assertEqual(f.read(), ORIGINAL)  # nothing was copied back
        self.assertEqual(sorted(os.listdir(os.path.dirname(login))), ["auth.json"])
