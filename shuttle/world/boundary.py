"""The boundary's scope: the real set, through systemctl."""

import contextlib
import os
import subprocess
import uuid
from collections.abc import Mapping, Sequence

from shuttle.core.shapes import BoundaryOperations

# A systemctl that does not answer in this long is not answering.
_ANSWER_SECONDS = 30


def _systemctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["systemctl", "--user", *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_ANSWER_SECONDS,
        )
    except subprocess.SubprocessError as error:
        raise OSError(f"systemctl did not answer ({type(error).__name__})") from error


def show(unit: str, properties: Sequence[str]) -> Mapping[str, str]:
    done = _systemctl("show", "-p", ",".join(properties), "--", unit)
    if done.returncode != 0:
        raise OSError(f"systemctl show failed with status {done.returncode}")
    found: dict[str, str] = {}
    for line in done.stdout.splitlines():
        name, separator, value = line.partition("=")
        if separator:
            found[name] = value
    return found


def stop(unit: str) -> None:
    _systemctl("stop", "--", unit)  # a unit already gone is a stop that has nothing to do


def forget(unit: str) -> None:
    _systemctl("reset-failed", "--", unit)


def resolve(path: str) -> str:
    return os.path.realpath(path)


# What the trial scope runs: it finds its own cgroup (the line of /proc/self/cgroup that starts
# with 0::, the only kind there is on the unified hierarchy) and prints the two files that say
# what the cgroup is held to. On a machine where the memory controller is not there for a user
# scope the files are missing, or say "max", whatever the scope was asked for.
_READ_THE_CAP = (
    'p=$(sed -n "s/^0:://p" /proc/self/cgroup) || exit 1; '
    'cat "/sys/fs/cgroup$p/memory.max" "/sys/fs/cgroup$p/memory.swap.max"'
)


def try_memory_cap(memory_max: int, swap_max: int) -> tuple[str, str]:
    unit = f"shuttle-probe-{uuid.uuid4().hex}"
    try:
        done = subprocess.run(
            [
                "systemd-run",
                "--user",
                "--scope",
                "--quiet",
                f"--unit={unit}",
                "-p",
                f"MemoryMax={memory_max}",
                "-p",
                f"MemorySwapMax={swap_max}",
                "--",
                "sh",
                "-c",
                _READ_THE_CAP,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_ANSWER_SECONDS,
        )
    except (subprocess.SubprocessError, UnicodeDecodeError) as error:
        raise OSError(f"the trial scope did not answer ({type(error).__name__})") from error
    finally:
        # A scope that failed stays loaded until it is reset; one that is gone says "not loaded".
        with contextlib.suppress(OSError):  # not answering: the caller is told by what follows
            forget(f"{unit}.scope")
    lines = done.stdout.split()
    if done.returncode != 0 or len(lines) != 2:
        raise OSError(f"the trial scope could not read its limits (status {done.returncode})")
    return lines[0], lines[1]


BOUNDARY = BoundaryOperations(
    show=show, stop=stop, forget=forget, resolve=resolve, try_memory_cap=try_memory_cap
)
