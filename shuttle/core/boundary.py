"""The boundary: decisions about the scope and the box the executor runs in, and about the scopes
a gate and the closing freeze run in (they have no box), as pure functions.

The scope is a systemd user scope. It owns the time limit (its maximum runtime) and the grace
between asking and killing (its stop timeout); it ends everything inside when either runs out,
and the reason it ended can be read afterwards from its properties. The box is bubblewrap, started
inside the scope: it applies the executor's reach, which is hidden unless declared. Only what the
box binds in is there; the system folders and `/etc` are read-only, the place and the run area are
writable, and the rest of the machine (the caller's home folder, other checkouts, the user's
runtime folder with its systemd and D-Bus sockets, the real `/tmp`, the records) is not. The
reach limits what a lost or confused agent can do by mistake; it is not a security sandbox.
Nothing here touches the world: the shell reads the properties and gathers the paths, and acts on
these answers.
"""

import json
import math
from collections.abc import Mapping, Sequence
from typing import TypedDict

from shuttle.core import refusals

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
GATE_SCOPE_PREFIX = "shuttle-gate-"
FREEZE_SCOPE_PREFIX = "shuttle-freeze-"
PROPERTIES = ("LoadState", "ActiveState", "Result")

# The variables the shell needs to reach the user's systemd. The executor does not get them
# unless the caller named them.
BUS_VARIABLES = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")

# Why the scope ended.
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


def scope_name(request_id: str, run_part: str) -> str:
    """The executor's scope name: the request id, so a person listing units can match it to its
    request, then the run's own part, so no other run asks systemd for the same name. The part is
    the id of the run's request record (read back with `run_part_of`); the two together must fit
    the 255 characters systemd allows a unit name."""
    return f"{SCOPE_PREFIX}{request_id}-{run_part}"


def run_part_of(request_record: Mapping[str, object]) -> str:
    """The run's own part of its scope names, from its request record: the id in the record's
    header. A later command that finds a run's scopes reads it here and builds the names with
    `scope_name`, `gate_scope_name` and `freeze_scope_name`."""
    header = request_record["header"]
    if not isinstance(header, Mapping) or not isinstance(header.get("record_id"), str):
        raise ValueError("the request record has no record id")
    return str(header["record_id"])


def unit_of(name: str) -> str:
    return name + ".scope"


def for_the_scope_tool(argv: Sequence[str]) -> list[str]:
    """`argv` as the scope tool must be given it so the command it starts gets it unchanged.

    `systemd-run` expands `$NAME`, `${NAME}` and `$$` in the command it is given, and a `$` is
    only literal when written `$$`. The tool has an option that turns this off
    (`--expand-environment=no`), but only from systemd 254; doubling every `$` works on every
    version. `%` and a backslash are not touched (shown against systemd 262): left alone.
    """
    return [part.replace("$", "$$") for part in argv]


class Reach(TypedDict):
    """The paths of one run's reach, each already resolved (absolute, no link, no `..`).

    The box makes the system folders and `/etc` read-only; `visible` and `references` are
    read-only, `place`, `area` and `git_folders` writable. `home` and `tmp`
    are folders inside `area`: `tmp` is the executor's `/tmp` and `home` its `HOME`. `records` is
    hidden whatever else is bound.

    `git_folders` are the place's own git folder and the one it shares with the checkout it was
    made from, as the shell found them: for a linked working copy (the usual place) they are
    outside the place, and git cannot run without them. Nothing else of the repository the place
    was made from is shown. `resolver` is the file `/etc/resolv.conf` leads
    to, when there is one (see `_resolver_bind`).
    """

    place: str
    area: str
    home: str
    tmp: str
    references: Sequence[str]
    visible: Sequence[str]
    git_folders: Sequence[str]
    place_writable: bool
    resolver: str | None
    records: str


# Where the system keeps its programs, libraries and configuration. `/usr` and `/etc` are
# bound as they are. The four others are links into `/usr` on most machines and folders of their
# own on some, and a "try" bind follows a link and is skipped where the name is not there, so one
# argument list serves each layout. (A link bound by name would lead nowhere inside the box.)
_SYSTEM_FOLDERS = ("/usr", "/etc")
_SYSTEM_LINKS = ("/bin", "/sbin", "/lib", "/lib64")


def place_is_writable(changes_to_place: bool | None) -> bool:
    """Whether the box leaves the place writable: it does unless the document said, for any
    driver, that the executor may not change it. A document that says nothing leaves it writable
    (the drivers that need the setting refuse a document without it)."""
    return changes_to_place is not False


def _depth(path: str) -> int:
    return path.count("/") if path != "/" else 0


def _reach_binds(reach: Reach) -> list[str]:
    """What binds the reach's own paths, in the order they must be given.

    A bind covers whatever an earlier one put at or below its destination, so a path must come
    after every path above it: a folder listed as visible can hold the place, a reference can be
    inside the place, and the place can be under the machine's temporary folder, which was bound
    over before any of them. Ordered by the depth of the destination, and for equal depth with the
    read-only ones first so a path that is both visible and the place stays writable (a listing
    never makes anything read-only or writable that was not).
    """
    wanted = [
        (path, 0, ["--ro-bind", path, path])
        for path in dict.fromkeys([*reach["visible"], *reach["references"]])
    ]
    wanted += [(path, 1, ["--bind", path, path]) for path in _writable(reach)]
    wanted.sort(key=lambda item: (_depth(item[0]), item[1]))
    return [part for _, _, parts in wanted for part in parts]


def _inside(path: str, folder: str) -> bool:
    return refusals.inside_folder(path, folder)


def _writable(reach: Reach) -> list[str]:
    held = [reach["area"], reach["place"]]
    every = list(dict.fromkeys(reach["git_folders"]))
    for folder in every:
        others = [other for other in (*held, *every) if other != folder]
        if not any(_inside(folder, other) for other in others):
            held.append(folder)
    return held


# The paths the box's own binds are made at: a file the shell found under one of these is already
# shown or replaced by those binds, so it is not bound again.
_BOX_OWN = ("/usr", "/etc", "/tmp", "/proc", "/dev")


def _resolver_bind(reach: Reach) -> list[str]:
    """The bind that makes name lookup work where `/etc/resolv.conf` is a link to a file outside
    `/etc`: the link would lead nowhere in the box, and a bind cannot be made onto a link, so the
    file it leads to is bound at its own path, as the link names it. Nothing is bound where the
    file is a plain one in `/etc`, is under `/usr` (shown already) or is under `/tmp` (which the
    executor's own would cover), or where there is no file. The rest of `/run` stays hidden."""
    target = reach["resolver"]
    if target is None or any(_inside(target, own) for own in _BOX_OWN):
        return []
    return ["--ro-bind", target, target]


def _hidden_records(reach: Reach) -> list[str]:
    """The cover for the records folder when it sits inside a path the box binds in from the host
    where hiding by not binding it is not enough: an
    empty temporary filesystem over it. Elsewhere it is simply not bound."""
    holders = [
        *_SYSTEM_FOLDERS,
        reach["place"],
        reach["area"],
        *reach["git_folders"],
        *reach["references"],
        *reach["visible"],
    ]
    inside = any(refusals.inside_folder(reach["records"], holder) for holder in holders)
    return ["--tmpfs", reach["records"]] if inside else []


def box_arguments(reach: Reach) -> list[str]:
    """The bubblewrap arguments that give the executor its reach (the box), up to but not
    including its working directory and command."""
    return [
        "--ro-bind",
        "/usr",
        "/usr",
        *[part for link in _SYSTEM_LINKS for part in ("--ro-bind-try", link, link)],
        "--ro-bind",
        "/etc",
        "/etc",
        *_resolver_bind(reach),
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        # The executor's own `/tmp`, bound before every path that may be under the real `/tmp`
        # (the place, the run area, a reference, a visible folder in a test, often): a later
        # bind over `/tmp` would hide each of them.
        "--bind",
        reach["tmp"],
        "/tmp",
        *_reach_binds(reach),
        *_hidden_records(reach),
        "--setenv",
        "HOME",
        reach["home"],
    ]


def launch_argv(
    name: str,
    limit_seconds: float,
    argv: Sequence[str],
    environment_names: Sequence[str],
    reach: Reach,
    report_fd: int,
) -> list[str]:
    """The command that starts `argv` in the boundary.

    A scope with the limit and the grace, around bubblewrap with its own process space that dies
    with its parent and the reach `box_arguments` gives it. The variables the shell needed to
    reach systemd are taken out of the executor's environment unless the caller named them.
    Bubblewrap's status report goes to the descriptor `report_fd`, which says whether the
    executor was ever started (see `executor_started`). The executor starts in the place.
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
        *for_the_scope_tool(
            [
                "bwrap",
                "--unshare-pid",
                "--die-with-parent",
                "--json-status-fd",
                str(report_fd),
                *box_arguments(reach),
                *[part for variable in left_out for part in ("--unsetenv", variable)],
                "--chdir",
                reach["place"],
                "--",
                *argv,
            ]
        ),
    ]


def why_ended(properties: Mapping[str, str] | None) -> str:
    """Why the scope ended, from its properties after it was stopped: "timed_out", "ended" or
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


def scope_is_empty(properties: Mapping[str, str] | None) -> bool:
    """Whether the scope is seen empty: it is gone or failed. Unreadable is not empty."""
    return properties is not None and properties.get("ActiveState") in _SETTLED


def cause_of_end(wait: str | None, scope_end: str) -> str:
    """The cause that ended the wait, refined by why the scope ended.

    The wait ends when the executor exits, or a signal or a stop record is seen. When it ended
    by the executor going away, the scope says whether that was the limit.
    """
    if wait != "exited":
        return wait or CANNOT_TELL
    if scope_end == TIMED_OUT:
        return "time_limit"
    if scope_end == ENDED:
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
    """Whether the boundary never started the executor: the scope was seen to end by itself and
    bubblewrap never reported the executor running.

    That reads the same whether a tool was missing, `systemd-run` could not make the scope or
    `bwrap` could not make the box. A time limit, a signal, or a cause that cannot be told is
    not read as a failed launch: the timer may end the scope before it reports, and a failed
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


# A gate has no box: it runs in a scope of its own, with its limit on the scope,
# started through this one line of shell. The line says on the report descriptor that the gate's
# command is about to start (the scope's own tool exits with status 1 when it cannot make the
# scope, which a gate would read as its "no"), takes the variables that reached the user's systemd
# out of the gate's environment, and becomes the gate's command, so the status the shell sees is
# the gate's own.
GATE_STARTED = "started"
GATE_SCRIPT = f'echo {GATE_STARTED} >&"$1"; shift; unset {" ".join(BUS_VARIABLES)}; exec "$@"'


def gate_scope_name(request_id: str, run_part: str, index: int) -> str:
    """A gate's scope name: the request id, the run's own part and the gate's place in the list."""
    return f"{GATE_SCOPE_PREFIX}{request_id}-{run_part}-{index}"


def freeze_scope_name(request_id: str, run_part: str) -> str:
    """The scope the closing freeze runs in: the request id and the run's own part."""
    return f"{FREEZE_SCOPE_PREFIX}{request_id}-{run_part}"


def scoped_argv(name: str, limit_seconds: float, argv: Sequence[str]) -> list[str]:
    """The command that starts `argv` in a scope of its own, named `name`, with the limit as the
    scope's maximum runtime and the grace between asking and killing."""
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
        *for_the_scope_tool(argv),
    ]


def gate_argv(name: str, limit_seconds: float, argv: Sequence[str], report_fd: int) -> list[str]:
    """The command that starts the gate `argv` in a scope of its own with its limit on the scope
    and the grace between asking and killing; `report_fd` is where it says it started."""
    return scoped_argv(name, limit_seconds, ["sh", "-c", GATE_SCRIPT, "sh", str(report_fd), *argv])


def gate_started(report: str) -> bool:
    """Whether the gate's report says its scope was made and its command was about to start."""
    return GATE_STARTED in report.split()


def gate_answer(report: str, why: str, returncode: int | None) -> str:
    """A gate's answer: "yes", "no" or "failed", from what it reported, why its scope ended
    (`why_ended`, read after the scope was stopped) and the status its process ended with.

    Only a gate that said it started, whose scope was seen settled and did not end by its limit,
    and that ended with a status (not a signal) answers by that status; any other ending is failed.
    """
    started = gate_started(report)
    exit_code = returncode if returncode is not None and returncode >= 0 else None
    return refusals.gate_answer(started, exit_code, why != ENDED)
