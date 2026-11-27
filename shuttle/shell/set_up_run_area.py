"""Step 5, set up the run area: the run's own folder, and what the driver's setup asks of it.

The folder is made new, empty and private. The driver's requests (shuttle.core.run_area) are
turned into a plan by the core and carried out here, in order, through the world's operations:
every path the plan names is inside the area, except the sources it copies from or links to, which
are only read (a share is a link, never opened). The folder is remembered in the state as soon as
it exists, so the tear-down finds it however this step ends. A refused plan or a failed action
fails the step with one line saying which.
"""

from collections.abc import Sequence

from shuttle.core import run_area
from shuttle.core.drivers import command
from shuttle.core.shapes import Operations, RunState, SetupRequest, SetupStep, StepResult


def _carry_out(world: Operations, step: SetupStep) -> None:
    files = world.files
    match step["do"]:
        case "folder":
            files.make_folders(step["target"])
        case "copy":
            files.copy_path(step["source"], step["target"], step["leave_out"])
        case "share":
            files.share_by_link(step["source"], step["target"])
        case "write":
            files.write_new(step["target"], step["text"])
        case "writable":
            files.make_writable(step["target"])
        case other:
            raise ValueError(f"unknown setup step {other!r}")


def set_up(state: RunState, requests: Sequence[SetupRequest]) -> StepResult:
    world = state["world"]
    problem = run_area.refusal(requests)
    if problem:  # refused before anything is made
        state["problems"]["setup"] = f"{problem}; nothing was made and nothing was launched"
        return {"ok": False}
    area = world.files.make_temporary_folder(run_area.AREA_PREFIX)
    state["run_area"] = area
    state["setup_variables"] = {}
    plan = run_area.plan(area, requests)
    for number, step in enumerate(plan["steps"], 1):
        try:
            _carry_out(world, step)
        except OSError as error:
            state["problems"]["setup"] = (
                f"setup step {number} ({step['do']}) failed ({type(error).__name__}); "
                "nothing was launched"
            )
            return {"ok": False}
    state["setup_variables"] = plan["variables"]
    return {"ok": True}


def step(state: RunState) -> None:
    result = set_up(state, command.setup_requests(state["raw"]["executor"]["settings"]))
    state["stand_ins"]["setup"] = result
    state["facts"]["setup"] = "failed" if result.get("ok") is False else "ok"
