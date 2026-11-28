"""The real trial scope leaves nothing of its own when it times out.

The tool that makes the scope is replaced, ahead of the real one on PATH, by one that makes the
scope and leaves a process in it that outlives the tool being killed, so the timeout path is the
one taken, at once, with the trial given a short answer time. Only units whose name this call
made (found by what is new in the listing) are looked at; the unit the stand-in makes is named in
a file, and a failing test stops that one unit and no other.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from shuttle.world import boundary as world_boundary

PROBE = "shuttle-probe-*"


def probe_units():
    done = subprocess.run(
        ["systemctl", "--user", "list-units", "--all", "--plain", "--no-legend", PROBE],
        capture_output=True,
        text=True,
    )
    return {line.split()[0] for line in done.stdout.splitlines() if line.split()}


class TheTrialLeavesNothingOnTheTimeoutPath(unittest.TestCase):
    def setUp(self):
        real = shutil.which("systemd-run")
        if real is None or shutil.which("systemctl") is None:
            self.skipTest("no systemd-run on this machine")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tool = os.path.join(tmp.name, "systemd-run")
        with open(tool, "w") as f:
            f.write(
                f"#!{sys.executable}\n"
                "import os, sys\n"
                "args = sys.argv[1:]\n"
                "args = args[: args.index('--') + 1]\n"
                f"open({os.path.join(tmp.name, 'unit')!r}, 'w').write(\n"
                "    next(a for a in args if a.startswith('--unit=')).split('=', 1)[1] + '.scope')\n"
                f"os.execv({real!r}, [{real!r}, *args, 'sh', '-c', 'sleep 30 & sleep 30'])\n"
            )
        os.chmod(tool, os.stat(tool).st_mode | stat.S_IXUSR)
        self.addCleanup(self.stop_the_standins_unit, os.path.join(tmp.name, "unit"))
        was = os.environ["PATH"]
        os.environ["PATH"] = tmp.name + os.pathsep + was
        self.addCleanup(os.environ.__setitem__, "PATH", was)

    @staticmethod
    def stop_the_standins_unit(named_in):
        """Only the unit the stand-in made, if it made one and the test left it."""
        try:
            with open(named_in) as f:
                unit = f.read()
        except OSError:
            return
        for command in ("stop", "reset-failed"):
            subprocess.run(["systemctl", "--user", command, "--", unit], capture_output=True)

    def test_a_trial_that_times_out_raises_and_leaves_no_scope_of_its_own(self):
        before = probe_units()
        with self.assertRaises(OSError):
            world_boundary.try_memory_cap(64 * 1024 * 1024, 0, timeout=1.0)
        self.assertEqual(probe_units() - before, set())


if __name__ == "__main__":
    unittest.main()
