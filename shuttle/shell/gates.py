"""The gates: named checks run before the executor starts.

A gate is a command with its own limit. It is read-only by its nature: it is started with PATH
only in its environment and answers by its exit code (0 yes, 1 no, anything else, a limit passed
or a start that failed: failed). Each runs in a scope of its own (shuttle.core.boundary) with its
limit on the scope: nothing here times it. After it ends, when it reported that it started, the scope is stopped by name and seen
empty, and why it ended is read from the scope; `boundary.gate_answer` decides the answer, and the
first that is not a yes refuses the run, naming the gate and its answer.
"""

from shuttle.core import boundary, decisions, refusals
from shuttle.core.refusals import Found
from shuttle.core.shapes import Document, Operations, StepResult
from shuttle.shell import stop_and_confirm_empty

POLL_SECONDS = 0.05  # how often the wait for a gate's exit looks again; it is not a deadline


def ask_gate(world: Operations, gate: Document, environment: dict[str, str], name: str) -> str:
    """Run one gate in its scope, wait for it to end, and return its answer: yes, no or failed."""
    try:
        report = world.processes.open_report()
        argv = boundary.gate_argv(
            name, float(gate["limit_seconds"]), [gate["command"], *gate["arguments"]], report
        )
        process = world.processes.start(argv, environment, report)
    except (OSError, ValueError):
        return refusals.gate_answer(False, None, False)
    while (returncode := world.processes.wait(process, POLL_SECONDS)) is None:
        pass  # the scope ends the gate when its limit runs out
    said = world.processes.read_report(process)
    if not boundary.gate_started(said):
        # This run did not make a scope of that name (the name may be somebody else's): it is
        # not stopped, and the gate failed.
        return refusals.gate_answer(False, None, False)
    why = boundary.why_ended(stop_and_confirm_empty.stop_boundary(world, name))
    return boundary.gate_answer(said, why, returncode)


def run_gates(
    world: Operations, request_id: str, run_part: str, gates: list[Document]
) -> tuple[Found | None, StepResult]:
    """Ask every gate in order, stopping at the first that does not say yes.

    Every scope is named from the request id and `run_part`, the run's own part (a run that
    writes a request record gives the record's id; the check form, which writes none, a fresh
    one), so a gate's scope is never one that another run, or a check of the same document, makes.

    Returns the refusal (or None) and the step's result: the time the gates took.
    """
    environment = decisions.build_environment([], _path_only(world))
    for (
        variable
    ) in boundary.BUS_VARIABLES:  # to reach the user's systemd; the gate is not given them
        value = world.environment.read_variable(variable)
        if value is not None:
            environment[variable] = value
    started = world.clock.now()
    answers: list[tuple[str, str]] = []
    for index, gate in enumerate(gates):
        name = boundary.gate_scope_name(request_id, run_part, index)
        answers.append((gate["name"], ask_gate(world, gate, environment, name)))
        if answers[-1][1] != "yes":
            break
    return refusals.check_gates(answers), {"duration_seconds": world.clock.now() - started}


def _path_only(world: Operations) -> dict[str, str]:
    path = world.environment.read_variable("PATH")
    return {} if path is None else {"PATH": path}
