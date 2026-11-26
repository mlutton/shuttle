"""The boundary's scope: the real set, through systemctl."""

import os
import subprocess
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


BOUNDARY = BoundaryOperations(show=show, stop=stop, forget=forget, resolve=resolve)
