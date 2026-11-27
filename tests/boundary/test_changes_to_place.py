"""`changes_to_place: not` through the real box, with the command driver: the executor cannot
create, change or delete a file in the place, whatever driver would have enforced it; its own
`/tmp`, its run area and the statement path stay writable, and the statement still reaches its
copy target. With the setting `allowed` the same script changes the place.
"""

import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")
real_place = importlib.import_module("rehearsal.real_place")

# Tries each change to the place, and writes where the box lets it (its `/tmp` and the run area).
# It says what was allowed in its statement, at the path its notice gives it: a statement of the
# wrong shape is kept byte for byte, so the copy at the document's location is the report.
CHANGES_THE_PLACE = """
import json, os, re, sys
place = sys.argv[1]
given = sys.stdin.read()
def allowed(change):
    try:
        change()
        return True
    except OSError:
        return False
def create():
    open(os.path.join(place, "created.txt"), "w").write("new\\n")
def change():
    open(os.path.join(place, "tracked.txt"), "w").write("changed\\n")
def delete():
    os.remove(os.path.join(place, "tracked.txt"))
def make_folder():
    os.mkdir(os.path.join(place, "folder"))
def in_tmp():
    open("/tmp/mine", "w").write("tmp\\n")
tries = {fn.__name__: allowed(fn) for fn in (create, change, delete, make_folder, in_tmp)}
statement = re.search("exact path: (.+)", given).group(1)
open(os.path.join(os.path.dirname(statement), "scratch"), "w").write("area\\n")
open(statement, "w").write(json.dumps(tries))
"""


class ChangesToThePlace(real_run.RealRun):
    def run_it(self, setting):
        real_place.make_checkout(self.place, {"tracked.txt": "original\n"})
        statement = os.path.join(self.root, "statement.json")
        doc = self.document(self.script("changes.py", CHANGES_THE_PLACE), [self.place])
        self.expecting_a_statement(doc, statement)
        if setting is not None:
            doc["changes_to_place"] = setting
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(statement) as f:  # the statement reached its copy target
            return json.load(f)

    def test_with_not_the_place_cannot_be_changed_and_the_rest_of_the_run_works(self):
        tries = self.run_it("not")
        self.assertEqual(
            tries,
            {
                "create": False,
                "change": False,
                "delete": False,
                "make_folder": False,
                "in_tmp": True,
            },
        )
        self.assertEqual(os.listdir(self.place).count("created.txt"), 0)
        with open(os.path.join(self.place, "tracked.txt")) as f:
            self.assertEqual(f.read(), "original\n")
        self.assertEqual(real_place.git(self.place, "status", "--porcelain"), "")

    def assert_changed_as_before(self, setting):
        tries = self.run_it(setting)
        self.assertEqual(set(tries.values()), {True})
        self.assertTrue(os.path.exists(os.path.join(self.place, "created.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.place, "tracked.txt")))

    def test_with_allowed_the_place_is_changed_as_before(self):
        self.assert_changed_as_before("allowed")

    def test_without_the_setting_the_place_is_changed_as_before(self):
        self.assert_changed_as_before(None)
