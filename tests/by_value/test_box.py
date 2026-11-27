"""By value: the argument list that gives the executor its reach, and the order it must have.

The box's behaviour is in tests/boundary/test_reach.py; this pins what a person reading the list
needs to rely on: what is bound read-only, what is writable, what is not there, and the order.
"""

import unittest

from shuttle.core import boundary

REACH: boundary.Reach = {
    "place": "/work/place",
    "area": "/scratch/area",
    "home": "/scratch/area/home",
    "tmp": "/scratch/area/tmp",
    "references": ["/refs/runbook"],
    "visible": ["/opt/tool"],
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
        self.assertEqual(
            [d for d in destinations(argv) if d.startswith("/run")],
            ["/run/systemd/resolve/stub-resolv.conf"],
        )

    def test_the_links_into_usr_are_bound_if_the_machine_has_them_so_one_list_serves_any_layout(
        self,
    ):
        got = binds(boundary.box_arguments(REACH))
        for link in ("/bin", "/sbin", "/lib", "/lib64"):
            self.assertIn(("--ro-bind-try", link, link), got)

    def test_the_resolver_settings_are_bound_where_the_usual_link_leads_after_etc(self):
        got = binds(boundary.box_arguments(REACH))
        wanted = ("--ro-bind-try", "/etc/resolv.conf", "/run/systemd/resolve/stub-resolv.conf")
        self.assertIn(wanted, got)
        self.assertLess(got.index(("--ro-bind", "/etc", "/etc")), got.index(wanted))

    def test_home_is_the_executors_own_and_the_working_directory_is_the_place(self):
        argv = boundary.launch_argv("n", 1, ["t"], [], REACH, 3)
        at = argv.index("--setenv")
        self.assertEqual(argv[at : at + 3], ["--setenv", "HOME", "/scratch/area/home"])
        at = argv.index("--chdir")
        self.assertEqual(argv[at : at + 2], ["--chdir", "/work/place"])


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
