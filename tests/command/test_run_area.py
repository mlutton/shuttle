"""The run area's set-up and tear-down steps against the real files: a temporary folder the test
makes, a stand-in for a login whose content is a made-up marker, and the real operations.

The steps are called with the real operations (no process is started): the command driver asks
for no setup, so a whole run through the command does not reach the actions; the end-to-end test
shows the area made and removed by a run. What a driver's requests do is shown here.
"""

import importlib
import os
import stat
import sys
import tempfile
import unittest

from shuttle.core import run_area
from shuttle.shell import set_up_run_area, tear_down
from shuttle.world import real

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
importlib.import_module("rehearsal")

MARKER = "MARKER-not-a-real-login-4f9c1e"


def everything(root):
    """Every file's bytes by its name below `root`, links not followed, and each folder's name."""
    found = {}
    for folder, names, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                found[os.path.relpath(path, root)] = read(path)
        for name in names:
            found.setdefault(os.path.relpath(os.path.join(folder, name), root) + "/", b"")
    return found


def read(path):
    with open(path, "rb") as f:
        return f.read()


class TheRealRunArea(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = os.path.realpath(temporary.name)
        self.addCleanup(self.make_removable)
        self.tool = os.path.join(self.root, "tool-home")
        os.makedirs(os.path.join(self.tool, "history"))
        os.makedirs(os.path.join(self.tool, "cache", "deep"))
        for name, text in (
            ("config.toml", "settings"),
            ("history/log", "old"),
            ("cache/deep/x", "c"),
        ):
            with open(os.path.join(self.tool, name), "w") as f:
                f.write(text)
        os.chmod(os.path.join(self.tool, "config.toml"), 0o444)
        os.chmod(os.path.join(self.tool, "history"), 0o555)
        self.login = os.path.join(self.root, "login-stand-in")
        with open(self.login, "w") as f:
            f.write(MARKER)
        os.makedirs(os.path.join(self.root, "temporary"))
        was = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = os.path.join(self.root, "temporary")
        self.addCleanup(self.put_back, was)
        self.state = {"world": real.OPERATIONS, "problems": {}, "stand_ins": {}, "facts": {}}

    @staticmethod
    def put_back(was):
        if was is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = was

    def make_removable(self):
        for folder, names, _ in os.walk(self.root):
            for name in names:
                os.chmod(os.path.join(folder, name), 0o755)

    REQUESTS = [
        {"action": "copy", "name": "home", "source": None},
        {"action": "leave_out", "name": "home/history"},
        {"action": "leave_out", "name": "home/cache"},
        {"action": "share", "name": "home/login", "source": None},
        {"action": "write", "name": "home/generated.toml", "text": "made = true\n"},
        {"action": "writable", "name": "home/config.toml"},
        {"action": "variable", "variable": "TOOL_HOME", "in_run_area": "home"},
    ]

    def requests(self):
        filled = [dict(r) for r in self.REQUESTS]
        filled[0]["source"], filled[3]["source"] = self.tool, self.login
        return filled

    def test_each_action_lands_in_the_run_area_and_nothing_else_changes(self):
        before = everything(self.root)
        self.assertEqual(set_up_run_area.set_up(self.state, self.requests()), {"ok": True})
        area = self.state["run_area"]
        self.assertTrue(area.startswith(os.path.join(self.root, "temporary", run_area.AREA_PREFIX)))
        home = os.path.join(area, "home")
        self.assertEqual(self.state["setup_variables"], {"TOOL_HOME": home})
        with open(os.path.join(home, "config.toml")) as f:
            self.assertEqual(f.read(), "settings")
        self.assertTrue(os.stat(os.path.join(home, "config.toml")).st_mode & stat.S_IWUSR)
        self.assertEqual(sorted(os.listdir(home)), ["config.toml", "generated.toml", "login"])
        self.assertEqual(os.readlink(os.path.join(home, "login")), self.login)
        # the original is as it was, and the only change outside the area is the area itself
        outside = {k: v for k, v in everything(self.root).items() if not k.startswith("temporary/")}
        self.assertEqual(
            outside, {k: v for k, v in before.items() if not k.startswith("temporary/")}
        )
        self.assertEqual(os.stat(os.path.join(self.tool, "config.toml")).st_mode & 0o777, 0o444)

    def test_the_tear_down_removes_the_area_whole_the_read_only_copies_too_and_keeps_the_original(
        self,
    ):
        requests = [
            {"action": "copy", "name": "home", "source": self.tool},
            {"action": "share", "name": "login", "source": self.login},
        ]
        set_up_run_area.set_up(self.state, requests)
        area = self.state["run_area"]
        os.chmod(os.path.join(area, "home", "history"), 0o555)  # a read-only folder in the copy
        self.assertEqual(tear_down.remove(self.state), {"failure": ""})
        self.assertFalse(os.path.lexists(area))
        self.assertEqual(os.listdir(os.path.join(self.root, "temporary")), [])
        with open(self.login) as f:
            self.assertEqual(f.read(), MARKER)
        self.assertTrue(os.path.exists(os.path.join(self.tool, "history", "log")))

    def test_the_stand_in_login_is_in_no_file_but_its_own_and_nothing_printed(self):
        set_up_run_area.set_up(self.state, self.requests())
        tear_down.remove(self.state)
        holding = [name for name, data in everything(self.root).items() if MARKER.encode() in data]
        self.assertEqual(holding, ["login-stand-in"])
        self.assertNotIn(MARKER, repr(self.state))

    def test_a_write_below_a_shared_name_is_refused_and_the_original_is_untouched(self):
        requests = [
            {"action": "share", "name": "tool", "source": self.tool},
            {"action": "write", "name": "tool/new", "text": "x"},
        ]
        self.assertEqual(set_up_run_area.set_up(self.state, requests), {"ok": False})
        self.assertFalse(os.path.exists(os.path.join(self.tool, "new")))

    def test_a_source_that_is_not_there_fails_the_step_and_the_tear_down_still_clears_the_area(
        self,
    ):
        requests = [{"action": "copy", "name": "home", "source": os.path.join(self.root, "absent")}]
        self.assertEqual(set_up_run_area.set_up(self.state, requests), {"ok": False})
        self.assertIn("FileNotFoundError", self.state["problems"]["setup"])
        tear_down.remove(self.state)
        self.assertEqual(os.listdir(os.path.join(self.root, "temporary")), [])


if __name__ == "__main__":
    unittest.main()
