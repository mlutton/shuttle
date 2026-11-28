"""The sweep of stale run areas against the real files: a temporary folder the test makes, set as
`TMPDIR`, and the real operations. No executor is started and no run area of the machine is
looked at: the sweep reads only the folder `TMPDIR` names.

A stale area whose scope has to be looked up asks the real manager (systemctl), so the tests that
remove one need the boundary; the ones that leave a look-alike alone never get that far. What a
killed Shuttle leaves, and a live run's area, are in tests/boundary/test_run_area_lock.py.
"""

import importlib
import io
import os
import stat
import sys
import tempfile
import unittest
import uuid

from shuttle.core import run_area
from shuttle.core.shapes import NotARegularFile
from shuttle.shell import sweep_run_areas
from shuttle.world import real

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
the_boundary = importlib.import_module("rehearsal.the_boundary")


class TheSweepOnTheRealFiles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = os.path.realpath(temporary.name)
        self.addCleanup(self.make_removable)
        self.temporary = os.path.join(self.root, "temporary")
        os.mkdir(self.temporary)
        was = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = self.temporary
        self.addCleanup(self.put_back, was)

    @staticmethod
    def put_back(was):
        if was is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = was

    def make_removable(self):
        os.chmod(self.temporary, 0o700)
        for folder, names, _ in os.walk(self.root):
            for name in names:
                os.chmod(os.path.join(folder, name), 0o700)

    def area(self):
        return os.path.join(self.temporary, run_area.area_name(uuid.uuid4().hex))

    def make_stale(self, area=None):
        """What a Shuttle killed hard leaves: the area with a login copy in it, and a lock file
        nobody holds."""
        area = area or self.area()
        os.makedirs(os.path.join(area, "home", ".tool"))
        with open(os.path.join(area, "home", ".tool", "login"), "w") as f:
            f.write("a made-up login")
        os.chmod(os.path.join(area, "home", ".tool"), 0o500)  # read-only, as a copy may be
        with open(run_area.lock_path(area), "w"):
            pass
        return area

    def sweep(self):
        err = io.StringIO()
        sweep_run_areas.sweep_before_the_run_makes_its_area({"world": real.OPERATIONS, "err": err})
        return err.getvalue()

    def listing(self):
        return sorted(os.listdir(self.temporary))

    def test_a_look_alike_is_left_alone_for_real_whatever_its_shape(self):
        # one name per shape: the right name and no lock file (an area from before the lock), a
        # lock file that is a link, a link to a folder, a file with the area's name, a lock file
        # that is a folder, a lock file that leads nowhere, a name that is almost the pattern
        before_the_lock = self.area()
        os.makedirs(os.path.join(before_the_lock, "home"))
        linked_lock = self.area()
        os.mkdir(linked_lock)
        with open(os.path.join(self.root, "elsewhere"), "w"):
            pass
        os.symlink(os.path.join(self.root, "elsewhere"), run_area.lock_path(linked_lock))
        real_folder = os.path.join(self.root, "real-folder")
        os.makedirs(os.path.join(real_folder, "home"))
        linked_area = self.area()
        os.symlink(real_folder, linked_area)
        with open(run_area.lock_path(linked_area), "w"):
            pass
        file_area = self.area()
        with open(file_area, "w") as f:
            f.write("not a folder")
        with open(run_area.lock_path(file_area), "w"):
            pass
        folder_lock = self.area()
        os.mkdir(folder_lock)
        os.mkdir(run_area.lock_path(folder_lock))
        dangling_lock = self.area()
        os.mkdir(dangling_lock)
        os.symlink(os.path.join(self.root, "nowhere"), run_area.lock_path(dangling_lock))
        almost = self.area() + "-old"
        os.mkdir(almost)
        with open(almost + ".lock", "w"):
            pass
        before = self.listing()
        self.assertEqual(self.sweep(), "")
        self.assertEqual(self.listing(), before)
        for path in (before_the_lock, linked_lock, folder_lock, dangling_lock, almost):
            self.assertTrue(os.path.isdir(path), path)
        self.assertTrue(os.path.islink(linked_area))
        self.assertTrue(os.path.isfile(file_area))
        self.assertTrue(os.path.isdir(os.path.join(real_folder, "home")))  # what the link leads to

    def test_a_stale_area_is_removed_with_its_lock_file_and_what_it_held_for_real(self):
        the_boundary.require(self)  # the scopes of the run are looked up through the manager
        area = self.make_stale()
        other = self.make_stale()
        unrelated = os.path.join(self.temporary, "unrelated")
        os.mkdir(unrelated)
        line = self.sweep()
        self.assertEqual(line, "shuttle: removed 2 stale run areas of runs that are gone\n")
        self.assertEqual(self.listing(), ["unrelated"])
        self.assertFalse(os.path.lexists(area))
        self.assertFalse(os.path.lexists(other))

    def test_a_lock_file_with_no_area_is_removed_for_real(self):
        lock = run_area.lock_path(self.area())
        with open(lock, "w"):
            pass
        self.assertEqual(
            self.sweep(),
            "shuttle: removed 0 stale run areas of runs that are gone and 1 lock file with no area beside it and a free lock\n",
        )
        self.assertEqual(self.listing(), [])

    def test_an_area_whose_lock_is_held_is_left_whole_and_nothing_is_said(self):
        area = self.area()
        real.OPERATIONS.files.create_lock(run_area.lock_path(area))
        self.addCleanup(real.OPERATIONS.files.release_lock, run_area.lock_path(area), True)
        real.OPERATIONS.files.make_private_folder(area)
        before = self.listing()
        self.assertEqual(self.sweep(), "")
        self.assertEqual(self.listing(), before)
        self.assertTrue(os.path.isdir(area))

    def test_an_area_that_cannot_be_removed_is_left_with_its_lock_and_the_line_says_so(self):
        if os.geteuid() == 0:
            self.skipTest("root can remove what the user cannot")
        the_boundary.require(self)
        area = self.make_stale()
        os.chmod(self.temporary, stat.S_IRUSR | stat.S_IXUSR)  # nothing in it can be removed
        line = self.sweep()
        self.assertEqual(
            line,
            "shuttle: removed 0 stale run areas of runs that are gone; left alone: "
            f"{os.path.basename(area)!r} (it could not be removed (PermissionError))\n",
        )
        self.assertTrue(os.path.isfile(run_area.lock_path(area)))
        # the lock was let go, so the next sweep, with the folder writable again, finishes it
        os.chmod(self.temporary, 0o700)
        self.assertEqual(self.sweep(), "shuttle: removed 1 stale run area of runs that are gone\n")

    def test_a_temporary_folder_that_is_not_there_is_one_line_and_the_run_goes_on(self):
        os.environ["TMPDIR"] = os.path.join(self.root, "no-such-folder")
        self.assertEqual(
            self.sweep(),
            "shuttle: stale run areas were not looked for (FileNotFoundError); "
            "nothing was removed and the run goes on\n",
        )

    def test_a_lock_file_swapped_for_a_link_is_never_taken_and_its_area_stays(self):
        area = self.make_stale()
        lock = run_area.lock_path(area)
        os.unlink(lock)
        with open(os.path.join(self.root, "elsewhere"), "w"):
            pass
        os.symlink(os.path.join(self.root, "elsewhere"), lock)
        self.assertRaises(NotARegularFile, real.OPERATIONS.files.try_lock, lock)
        self.assertEqual(self.sweep(), "")
        self.assertTrue(os.path.isdir(area))


if __name__ == "__main__":
    unittest.main()
