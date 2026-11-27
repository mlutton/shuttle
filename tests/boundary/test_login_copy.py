"""A tool's login reaches it by copy: it may replace the copy as the real tool does, and the
original is as it was.

The program that stands in for the tool is written and run by `run_a_stand_in_tool`
(tests/rehearsal/real_run.py). The login is made-up text; no test opens a real one. The stand-in
saves a refreshed login the way the real tool does (a temporary file beside it, then a rename over
it, with a lock file in the same folder), which fails on a link and on a single bound file.
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
    def test_the_replacement_works_and_the_original_is_unchanged_after_the_run(self):
        driver = real_run.tool_driver_names()[0]
        home = os.path.join(self.root, "callers-home")
        login = real_run.table.DRIVERS[driver].login_path({"HOME": home})
        os.makedirs(os.path.dirname(login))
        with open(login, "w") as f:
            f.write(ORIGINAL)
        os.chmod(login, 0o600)
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
