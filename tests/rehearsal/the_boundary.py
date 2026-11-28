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
from shuttle.world import boundary as real_boundary

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


@functools.cache
def memory_cap_absent_reason() -> str | None:
    """Why this machine cannot cap memory for a user scope, or None when it can: the real
    operation's own trial, judged by the core's own rule (what the runs use)."""
    try:
        trial = real_boundary.try_memory_cap(
            boundary.TRIAL_MEMORY_BYTES, boundary.SWAP_WITH_A_CAP_BYTES
        )
    except OSError as error:
        return f"the trial scope could not be made or read: {error}"
    if boundary.memory_cap_held(trial):
        return None
    return f"a trial scope asked for a memory cap read back {trial!r}, not the cap it was given"


def require_memory_cap(case: unittest.TestCase) -> None:
    """For a test that needs a cap to be held: skip, saying why, on a machine that cannot hold
    one (where the cap is refused instead, which a test that needs no cap shows). The hosted
    runner's setting does not make the absence a failure: whether it can cap is for the report
    to say."""
    require(case)
    reason = memory_cap_absent_reason()
    if reason is not None:
        case.skipTest(f"no memory cap on this machine: {reason}")
