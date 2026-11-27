"""Whether this machine has the real boundary, for the tests that run a real executor.

A test that needs it calls `require()` in its set-up. Where the boundary is absent the test
skips and says why; where SHUTTLE_REQUIRE_BOUNDARY is set (the hosted runner sets it) its absence
is a failure instead, so a runner that lost the boundary cannot pass by skipping everything.
"""

import functools
import os
import shutil
import subprocess
import tempfile
import unittest

from shuttle.core import boundary

PROGRAMS = ("systemd-run", "systemctl", "bwrap")


@functools.cache
def absent_reason() -> str | None:
    """Why the boundary is absent here, or None when it works."""
    for program in PROGRAMS:
        if shutil.which(program) is None:
            return f"{program} is not installed"
    try:
        with tempfile.TemporaryDirectory() as folder:
            area = os.path.realpath(folder)
            for name in ("home", "tmp", "place"):
                os.mkdir(os.path.join(area, name))
            reach: boundary.Reach = {
                "place": os.path.join(area, "place"),
                "area": area,
                "home": os.path.join(area, "home"),
                "tmp": os.path.join(area, "tmp"),
                "references": [],
                "visible": [],
                "git_folders": [],
                "place_writable": True,
                "resolver": None,
                "records": os.path.join(area, "records"),
            }
            # The box the runs use, so a machine that cannot make it is seen to lack it.
            done = subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    "--scope",
                    "--quiet",
                    "--",
                    "bwrap",
                    "--unshare-pid",
                    "--die-with-parent",
                    *boundary.box_arguments(reach),
                    "--chdir",
                    reach["place"],
                    "--",
                    "/usr/bin/true",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
    except (OSError, subprocess.SubprocessError) as error:
        return f"the boundary could not be started ({type(error).__name__})"
    if done.returncode != 0:
        return "the boundary could not run a command: " + " ".join(done.stderr.split())[:200]
    return None


def require(case: unittest.TestCase) -> None:
    reason = absent_reason()
    if reason is None:
        return
    if os.environ.get("SHUTTLE_REQUIRE_BOUNDARY"):
        case.fail(f"the boundary is required here and is absent: {reason}")
    case.skipTest(f"no boundary on this machine: {reason}")
