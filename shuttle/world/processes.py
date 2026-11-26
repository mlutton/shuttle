"""Child processes: the real set."""

import shutil
import subprocess
from collections.abc import Mapping, Sequence

from shuttle.core.shapes import ProcessOperations


def find_program(command: str) -> bool:
    try:
        return shutil.which(command) is not None
    # The handler is the old locate()'s, kept as it was. No input is known to make shutil.which
    # raise on the one Python available (3.14): a name with a NUL gives None.
    except (ValueError, OSError):  # not tested: no known input reaches it on Python 3.14
        return False


def start(argv: Sequence[str], environment: Mapping[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        list(argv),
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def poll(process: subprocess.Popen[bytes]) -> int | None:
    return process.poll()


def ask_to_end(process: subprocess.Popen[bytes]) -> None:
    process.terminate()


def kill(process: subprocess.Popen[bytes]) -> None:
    process.kill()


PROCESSES = ProcessOperations(
    find_program=find_program, start=start, poll=poll, ask_to_end=ask_to_end, kill=kill
)
