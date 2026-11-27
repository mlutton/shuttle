"""By value: the argument list that gives the executor its reach, and the order it must have.

The box's behaviour is in tests/boundary/test_reach.py; this pins what a person reading the list
needs to rely on: what is bound read-only, what is writable, what is not there, and the order.
"""

import importlib
import os
import sys
import unittest

from shuttle.core import boundary

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")

REACH: boundary.Reach = {
    "place": "/work/place",
    "area": "/scratch/area",
    "home": "/scratch/area/home",
    "tmp": "/scratch/area/tmp",
    "references": ["/refs/runbook"],
    "visible": ["/opt/tool"],
    "git_folders": [],
    "place_writable": True,
    "resolver": None,
    "records": "/records",
}


def binds(argv):
    """(kind, source, destination) of each bind in the argument list, in order."""
    found = []
    for at, part in enumerate(argv):
        if part in ("--ro-bind", "--bind", "--ro-bind-try"):
            found.append((part, argv[at + 1], argv[at + 2]))
    return found


def destinations(argv):
    return [destination for _, _, destination in binds(argv)]


class TheBinds(unittest.TestCase):
    def test_the_system_is_read_only_and_the_place_and_the_run_area_are_the_only_writable_paths(
        self,
    ):
        got = binds(boundary.box_arguments(REACH))
        read_only = [d for kind, _, d in got if kind != "--bind"]
        self.assertIn("/usr", read_only)
        self.assertIn("/etc", read_only)
        self.assertEqual(
            [(s, d) for kind, s, d in got if kind == "--bind"],
            [
                ("/scratch/area/tmp", "/tmp"),
                ("/scratch/area", "/scratch/area"),
                ("/work/place", "/work/place"),
            ],
        )
        for path in ("/opt/tool", "/refs/runbook"):
            self.assertIn(("--ro-bind", path, path), got)

    def test_nothing_else_of_the_machine_is_bound_and_the_records_are_never_named(self):
        argv = boundary.box_arguments(REACH)
        for hidden in ("/home", "/var", "/records", "/root", "/mnt"):
            self.assertFalse([d for d in destinations(argv) if d.startswith(hidden)], hidden)
        self.assertNotIn("/records", argv)
        self.assertEqual([d for d in destinations(argv) if d.startswith("/run")], [])

    def test_the_links_into_usr_are_bound_if_the_machine_has_them_so_one_list_serves_any_layout(
        self,
    ):
        got = binds(boundary.box_arguments(REACH))
        for link in ("/bin", "/sbin", "/lib", "/lib64"):
            self.assertIn(("--ro-bind-try", link, link), got)

    # Where /etc/resolv.conf leads, as the shell found it, and whether the file is bound there.
    RESOLVER_LAYOUTS = (
        ("the stub file of systemd-resolved", "/run/systemd/resolve/stub-resolv.conf", True),
        ("the other file of systemd-resolved", "/run/systemd/resolve/resolv.conf", True),
        ("the file of NetworkManager", "/run/NetworkManager/resolv.conf", True),
        ("a file kept under the machine's own variable data", "/var/lib/x/resolv.conf", True),
        ("a file under /usr, shown already", "/usr/lib/x/resolv.conf", False),
        ("a plain file in /etc", "/etc/resolv.conf", False),
        ("a file under /tmp, which the executor's own would cover", "/tmp/r/resolv.conf", False),
        ("no file, or a link that leads nowhere", None, False),
    )

    def test_the_file_the_resolver_settings_lead_to_is_bound_at_its_own_path_after_etc_if_at_all(
        self,
    ):
        for label, target, bound in self.RESOLVER_LAYOUTS:
            with self.subTest(label):
                got = binds(boundary.box_arguments({**REACH, "resolver": target}))
                wanted = ("--ro-bind", target, target)
                self.assertEqual(wanted in got, bound)
                if bound:
                    self.assertLess(got.index(("--ro-bind", "/etc", "/etc")), got.index(wanted))
                self.assertEqual([d for _, _, d in got].count(target), 1 if bound else 0)

    def test_the_git_folders_are_writable_and_a_git_folder_inside_the_place_is_not_bound_again(
        self,
    ):
        linked = ["/main/.git", "/main/.git/worktrees/place"]
        got = binds(boundary.box_arguments({**REACH, "git_folders": linked}))
        self.assertIn(("--bind", "/main/.git", "/main/.git"), got)
        self.assertNotIn("/main/.git/worktrees/place", [d for _, _, d in got])  # it is inside
        self.assertFalse([d for _, _, d in got if d == "/main"])  # nothing else of it
        plain = ["/work/place/.git"]
        got = binds(boundary.box_arguments({**REACH, "git_folders": plain}))
        self.assertNotIn("/work/place/.git", [d for _, _, d in got])

    def test_a_git_folder_comes_after_the_tmp_bind_when_it_is_under_the_real_tmp(self):
        order = destinations(
            boundary.box_arguments({**REACH, "git_folders": ["/tmp/main/.git"], "place": "/tmp/p"})
        )
        self.assertLess(order.index("/tmp"), order.index("/tmp/main/.git"))

    def test_home_is_the_executors_own_and_the_working_directory_is_the_place(self):
        argv = boundary.launch_argv("n", 1, ["t"], [], REACH, 3)
        at = argv.index("--setenv")
        self.assertEqual(argv[at : at + 3], ["--setenv", "HOME", "/scratch/area/home"])
        at = argv.index("--chdir")
        self.assertEqual(argv[at : at + 2], ["--chdir", "/work/place"])


class WhatTheShellGathersForTheBox(unittest.TestCase):
    """A run hands the core the facts: where the resolver settings lead, and the place's git
    folders; the core decides from them (the table above)."""

    def argv_of_a_run(self, **prepare):
        world = scenes.scene()
        if "links" in prepare:
            for name, leads_to in prepare["links"].items():
                world.put_link(name, leads_to)
                world.put_file(leads_to, "nameserver 127.0.0.53\n")
        if "git_folders" in prepare:
            world.places[scenes.PLACE]["git_folders"] = prepare["git_folders"]
        code, _, err = scenes.run_in(world)
        assert code == 0, err
        return world.started[0][0]

    def test_where_the_resolver_settings_lead_is_bound_at_its_own_path(self):
        target = "/run/systemd/resolve/stub-resolv.conf"
        argv = self.argv_of_a_run(links={"/etc/resolv.conf": target})
        self.assertIn(("--ro-bind", target, target), binds(argv))

    def test_a_machine_with_no_resolver_settings_binds_nothing_for_them(self):
        argv = self.argv_of_a_run()
        self.assertEqual([d for d in destinations(argv) if d.startswith("/run")], [])

    def test_a_linked_places_git_folders_are_bound_writable_and_nothing_else_of_its_origin(self):
        argv = self.argv_of_a_run(git_folders=["/main/.git", "/main/.git/worktrees/place"])
        self.assertIn(("--bind", "/main/.git", "/main/.git"), binds(argv))
        self.assertFalse([d for d in destinations(argv) if d == "/main"])

    def test_a_plain_places_git_folder_is_inside_the_place_and_adds_no_bind(self):
        argv = self.argv_of_a_run()
        self.assertNotIn(f"{scenes.PLACE}/.git", destinations(argv))


class TheOrderTheBindsMustHave(unittest.TestCase):
    """A later bind covers what an earlier one put at or below its destination. So the executor's
    own `/tmp` comes before every path that may be under the real `/tmp`, and each path comes after
    every path above it; a read-only path never ends up over a writable one at the same place."""

    def order(self, **change):
        return destinations(boundary.box_arguments({**REACH, **change}))

    def test_the_executors_tmp_is_bound_before_every_path_of_the_reach(self):
        order = self.order(
            place="/tmp/p/place",
            area="/tmp/shuttle-run-area-x",
            references=["/tmp/ref"],
            visible=["/tmp/visible"],
        )
        tmp = order.index("/tmp")
        for path in ("/tmp/p/place", "/tmp/shuttle-run-area-x", "/tmp/ref", "/tmp/visible"):
            self.assertLess(tmp, order.index(path), path)

    def test_a_path_comes_after_the_path_above_it_whatever_the_order_it_was_given_in(self):
        order = self.order(
            place="/work/place",
            references=["/work/place/docs/ref"],
            visible=["/work/place/vendor", "/work"],
        )
        for above, below in (
            ("/work", "/work/place"),
            ("/work/place", "/work/place/docs/ref"),
            ("/work/place", "/work/place/vendor"),
        ):
            self.assertLess(order.index(above), order.index(below), (above, below))

    def test_a_folder_listed_as_visible_that_is_the_place_leaves_it_writable(self):
        got = binds(boundary.box_arguments({**REACH, "visible": ["/work/place"]}))
        place = [kind for kind, _, d in got if d == "/work/place"]
        self.assertEqual(place, ["--ro-bind", "--bind"])  # the writable one is last, so it holds

    def test_the_same_path_listed_twice_is_bound_once(self):
        order = self.order(visible=["/opt/tool", "/opt/tool"], references=["/opt/tool"])
        self.assertEqual(order.count("/opt/tool"), 1)


class TheRecordsAreHiddenEvenInsideWhatIsBound(unittest.TestCase):
    def tmpfs_over(self, **change):
        argv = boundary.box_arguments({**REACH, **change})
        return [argv[i + 1] for i, part in enumerate(argv) if part == "--tmpfs"]

    def test_records_that_are_not_inside_a_bound_path_need_no_cover(self):
        self.assertEqual(self.tmpfs_over(), [])
        self.assertEqual(self.tmpfs_over(records="/tmp/elsewhere/records"), [])

    def test_records_inside_the_place_a_reference_or_a_system_folder_are_covered_last(self):
        for where in ("/work/place/records", "/refs/runbook/records", "/etc/records"):
            with self.subTest(where):
                argv = boundary.box_arguments({**REACH, "records": where})
                self.assertEqual(self.tmpfs_over(records=where), [where])
                self.assertGreater(argv.index("--tmpfs"), argv.index("/work/place"))


if __name__ == "__main__":
    unittest.main()
