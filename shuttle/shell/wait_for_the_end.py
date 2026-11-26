"""Step 8, wait for the end: until the executor exits or a signal is seen.

The wait keeps no deadline: the boundary owns the time limit and ends the executor when it runs
out, so the wait sees an exit. Why it ended is read in the next step.
"""

from shuttle.core import boundary
from shuttle.core.shapes import RunState

POLL_SECONDS = 0.05  # how often a signal is looked for while the executor runs


def step(state: RunState) -> None:
    world = state["world"]
    process = state["boundary_process"]
    while True:
        cause = boundary.wait_cause(world.processes.poll(process) is not None, state["signal"])
        if cause:
            break
        world.processes.wait(process, POLL_SECONDS)
    state["facts"]["wait"] = cause
