"""The boundary: decisions about the box the executor runs in, as pure functions.

The box is a systemd user scope around bubblewrap. The scope owns the time limit (its maximum
runtime) and the grace between asking and killing (its stop timeout); it ends everything inside
when either runs out, and the reason it ended can be read afterwards from its properties. Nothing
here touches the world: the shell reads the properties and acts on these answers.
"""

import json
import math
from collections.abc import Mapping, Sequence

# The limit's bounds, in seconds. The scope's timer takes whole microseconds, and a value that
# rounds to zero microseconds means "no maximum", so the shortest limit is one microsecond. The
# longest is far inside what the timer takes (a little over 1.8e13 seconds on systemd 262, shown
# by `systemd-run -p RuntimeMaxSec=...`); it stops a limit that is "none" in all but name.
SHORTEST_LIMIT_SECONDS = 1e-6
LONGEST_LIMIT_SECONDS = 10**9

# Seconds between asking everything in the scope to end and killing what is left: the scope's
# stop timeout, a fixed policy.
GRACE_SECONDS = 3

SCOPE_PREFIX = "shuttle-run-"
PROPERTIES = ("LoadState", "ActiveState", "Result")

# The variables the shell needs to reach the user's systemd. The executor does not get them
# unless the caller named them.
BUS_VARIABLES = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")

# Why the boundary ended.
TIMED_OUT = "timed_out"
ENDED = "ended"
CANNOT_TELL = "cannot_tell"

# A scope that is gone, or failed, has nothing left in it.
_SETTLED = ("inactive", "failed")
# What a scope that ended for any cause but its time limit reads as: it ended by itself, or by
# something other than execution.
_ENDED_RESULTS = ("success", "signal", "oom-kill", "exit-code", "core-dump")


def usable_time_limit(seconds: object) -> bool:
    """A finite number the scope's timer can take: at least one microsecond, at most the longest."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return False
    try:
        value = float(seconds)
    except OverflowError:
        return False
    return math.isfinite(value) and SHORTEST_LIMIT_SECONDS <= value <= LONGEST_LIMIT_SECONDS


def limit_microseconds(seconds: float) -> int:
    """The limit in whole microseconds, for the scope's timer. Never zero (zero means no maximum)."""
    return max(1, round(seconds * 1_000_000))


def scope_name(request_id: str) -> str:
    """The scope's name, from the request id (used once, and made of characters a unit name holds)."""
    return SCOPE_PREFIX + request_id


def unit_of(name: str) -> str:
    return name + ".scope"


def launch_argv(
    name: str,
    limit_seconds: float,
    argv: Sequence[str],
    environment_names: Sequence[str],
    protected_paths: Sequence[str],
    report_fd: int,
) -> list[str]:
    """The command that starts `argv` in the boundary.

    A scope with the limit and the grace, around bubblewrap with its own process space that dies
    with its parent, the whole filesystem bound in and each protected path bound read-only over
    it. The variables the shell needed to reach systemd are taken out of the executor's
    environment unless the caller named them. Bubblewrap's status report goes to the descriptor
    `report_fd`, which says whether the executor was ever started (see `executor_started`).
    """
    left_out = [v for v in BUS_VARIABLES if v not in environment_names]
    return [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        f"--unit={name}",
        "-p",
        f"RuntimeMaxSec={limit_microseconds(limit_seconds)}us",
        "-p",
        f"TimeoutStopSec={GRACE_SECONDS}s",
        "--",
        "bwrap",
        "--unshare-pid",
        "--die-with-parent",
        "--json-status-fd",
        str(report_fd),
        "--bind",
        "/",
        "/",
        *[part for path in protected_paths for part in ("--ro-bind", path, path)],
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        *[part for variable in left_out for part in ("--unsetenv", variable)],
        "--",
        *argv,
    ]


def why_ended(properties: Mapping[str, str] | None) -> str:
    """Why the boundary ended, from its properties after it was stopped: "timed_out", "ended" or
    "cannot_tell". None means the properties could not be read.

    Only the scope's own timer reads as "timed_out". A scope that is still running, or that
    ended for a reason this does not know, is "cannot_tell": the ending is never a guess.
    """
    if properties is None or properties.get("ActiveState") not in _SETTLED:
        return CANNOT_TELL
    result = properties.get("Result")
    if result == "timeout":
        return TIMED_OUT
    if result in _ENDED_RESULTS:
        return ENDED
    return CANNOT_TELL


def is_empty(properties: Mapping[str, str] | None) -> bool:
    """Whether the boundary is seen empty: its scope is gone or failed. Unreadable is not empty."""
    return properties is not None and properties.get("ActiveState") in _SETTLED


def cause_of_end(wait: str | None, boundary_end: str) -> str:
    """The cause that ended the wait, refined by why the boundary ended.

    The wait ends when the executor exits, or a signal or a stop record is seen. When it ended
    by the executor going away, the boundary says whether that was the limit.
    """
    if wait != "exited":
        return wait or CANNOT_TELL
    if boundary_end == TIMED_OUT:
        return "time_limit"
    if boundary_end == ENDED:
        return "exited"
    return CANNOT_TELL


def executor_started(report: str) -> bool:
    """Whether bubblewrap's status report says the executor was started inside the box.

    The report is bubblewrap's `--json-status-fd`: one JSON object per line. Once the executor is
    running in the box, a line with a "child-pid" member (a positive whole number) is written.
    Lines that are not JSON objects, and members and objects not known, are ignored.
    """
    for line in report.splitlines():
        try:
            found = json.loads(line)
        except (ValueError, RecursionError):  # not JSON, or nested too deep to read
            continue
        pid = found.get("child-pid") if isinstance(found, dict) else None
        if type(pid) is int and pid > 0:
            return True
    return False


def launch_failed(cause: str, report: str) -> bool:
    """Whether the boundary never started the executor: the box was seen to end by itself and
    bubblewrap never reported the executor running.

    That reads the same whether a tool was missing, `systemd-run` could not make the scope or
    `bwrap` could not make the box. A time limit, a signal, or a cause that cannot be told is
    not read as a failed launch: the timer may end the box before it reports, and a failed
    launch is never a guess.
    """
    return cause == "exited" and not executor_started(report)


def wait_cause(child_exited: bool, signal_name: str | None) -> str | None:
    """What ends the wait, or None to keep waiting. The first cause seen wins; an exit that is
    already there wins over a signal."""
    if child_exited:
        return "exited"
    if signal_name:
        return "signal"
    return None
