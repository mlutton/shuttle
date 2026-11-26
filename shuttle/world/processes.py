"""Child processes: the real set."""

import shutil
import subprocess
from collections.abc import Mapping, Sequence

from shuttle.core.shapes import ProcessOperations


def find_program(command: str) -> bool:
    return shutil.which(command) is not None


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
