"""Child processes: the real set."""

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence

from shuttle.core.shapes import ProcessOperations

# The most of a report that is read: a child that fills it is not given more room.
_REPORT_LIMIT = 1 << 20

# The read ends of the reports opened and not yet started with, by the number the child sees.
_opened: dict[int, tuple[int, int]] = {}


class _Child(subprocess.Popen[bytes]):
    """A started child, with the read end of its report if it was given one."""

    report_from: int | None = None
    report_text: str | None = None


def find_program(command: str) -> str | None:
    found = shutil.which(command)
    return None if found is None else os.path.abspath(found)


def open_report() -> int:
    read, write = os.pipe()
    _opened[write] = (read, write)
    return write


def start(
    argv: Sequence[str],
    environment: Mapping[str, str],
    report: int | None = None,
    input_from: str | None = None,
    output_to: str | None = None,
) -> subprocess.Popen[bytes]:
    held = _opened.pop(report) if report is not None else None
    given = None
    kept = None
    try:
        given = open(input_from, "rb") if input_from is not None else None  # noqa: SIM115
        kept = open(output_to, "xb") if output_to is not None else None  # noqa: SIM115
        child = _Child(
            list(argv),
            env=dict(environment),
            stdin=given if given is not None else subprocess.DEVNULL,
            stdout=kept if kept is not None else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            pass_fds=(held[1],) if held else (),
        )
    except BaseException:
        if held:
            os.close(held[0])
        raise
    finally:
        if given is not None:
            given.close()
        if kept is not None:
            kept.close()
        if held:
            os.close(held[1])  # only the child holds the write end now
    if held:
        child.report_from = held[0]
    return child


def _drain(descriptor: int) -> bytes:
    """All that is in the pipe now, up to the limit; it never waits."""
    taken = bytearray()
    os.set_blocking(descriptor, False)
    while len(taken) < _REPORT_LIMIT:
        try:
            chunk = os.read(descriptor, 65536)
        except BlockingIOError:
            break  # nothing more is written yet
        if not chunk:
            break
        taken += chunk
    return bytes(taken)


def read_report(process: subprocess.Popen[bytes]) -> str:
    """What the child wrote to its report: all of it that is there, read once and kept."""
    if not isinstance(process, _Child) or process.report_from is None:
        return ""
    if process.report_text is None:
        taken = _drain(process.report_from)
        os.close(process.report_from)
        process.report_text = taken.decode("utf-8", errors="replace")
    return process.report_text


def poll(process: subprocess.Popen[bytes]) -> int | None:
    return process.poll()


def wait(process: subprocess.Popen[bytes], seconds: float) -> int | None:
    try:
        return process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return None


PROCESSES = ProcessOperations(
    find_program=find_program,
    start=start,
    poll=poll,
    wait=wait,
    open_report=open_report,
    read_report=read_report,
)
