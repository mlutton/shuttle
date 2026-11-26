"""The gates: named checks run before the executor starts.

A gate is a command with its own short limit. It is read-only by its nature: it is started with
PATH only in its environment and answers by its exit code (0 yes, 1 no, anything else, a limit
passed or a start that failed: failed). Each answer is decided by `refusals.gate_answer`; the
first that is not a yes refuses the run, naming the gate and its answer.
"""

import contextlib

from shuttle.core import decisions, refusals
from shuttle.core.refusals import Found
from shuttle.core.shapes import Document, Operations, Process, StepResult

_POLL_SECONDS = 0.05
_GRACE_SECONDS = 1.0  # as of 2026-11-26: after the limit, how long a gate has to end when asked


def _wait_for_exit(world: Operations, process: Process, seconds: float) -> bool:
    deadline = world.clock.now() + seconds
    while world.processes.poll(process) is None:
        if world.clock.now() >= deadline:
            return False
        world.clock.wait(_POLL_SECONDS)
    return True


def _end(world: Operations, process: Process) -> None:
    with contextlib.suppress(OSError):
        world.processes.ask_to_end(process)
    if not _wait_for_exit(world, process, _GRACE_SECONDS):
        with contextlib.suppress(OSError):
            world.processes.kill(process)
        _wait_for_exit(world, process, _GRACE_SECONDS)


def ask_gate(world: Operations, gate: Document, environment: dict[str, str]) -> str:
    """Start one gate, wait up to its limit, and return its answer: yes, no or failed."""
    try:
        process = world.processes.start([gate["command"], *gate["arguments"]], environment)
    except (OSError, ValueError):
        return refusals.gate_answer(False, None, False)
    try:
        timed_out = not _wait_for_exit(world, process, float(gate["limit_seconds"]))
        if timed_out:
            _end(world, process)
    finally:
        if world.processes.poll(process) is None:
            _end(world, process)
    returncode = world.processes.poll(process)
    exit_code = returncode if returncode is not None and returncode >= 0 else None
    return refusals.gate_answer(True, exit_code, timed_out)


def run_gates(world: Operations, gates: list[Document]) -> tuple[Found | None, StepResult]:
    """Ask every gate in order, stopping at the first that does not say yes.

    Returns the refusal (or None) and the step's result: the time the gates took.
    """
    environment = decisions.build_environment([], _path_only(world))
    started = world.clock.now()
    answers: list[tuple[str, str]] = []
    for gate in gates:
        answers.append((gate["name"], ask_gate(world, gate, environment)))
        if answers[-1][1] != "yes":
            break
    return refusals.check_gates(answers), {"duration_seconds": world.clock.now() - started}


def _path_only(world: Operations) -> dict[str, str]:
    path = world.environment.read_variable("PATH")
    return {} if path is None else {"PATH": path}
