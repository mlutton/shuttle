"""Step 5, set up the run area: the run's own folder, and what the driver's setup asks of it.

The folder is made new, empty and private. The driver's requests (shuttle.core.run_area) are
turned into a plan by the core and carried out here, in order, through the world's operations:
every path the plan names is inside the area, except the sources it copies from, which are only
read. The folder is remembered in the state as soon as
it exists, so the tear-down finds it however this step ends. A refused plan or a failed action
fails the step with one line saying which.
"""

from collections.abc import Sequence
from typing import assert_never

from shuttle.core import run_area
from shuttle.core.shapes import Operations, RunState, SetupRequest, SetupStep, StepResult
from shuttle.shell import the_driver


def _carry_out(world: Operations, step: SetupStep) -> None:
    files = world.files
    match step["do"]:
        case "folder":
            files.make_folders(step["target"])
        case "copy":
            if step.get("optional") and not files.exists(step["source"]):
                return  # the request said a missing source is no error
            files.copy_path(step["source"], step["target"], step["leave_out"])
        case "write":
            files.write_new(step["target"], step["text"])
        case "writable":
            files.make_writable(step["target"])
        case never:
            assert_never(never)  # the type checker refuses a kind of step with no case here


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
    raw = state["raw"]
    driver = the_driver.of(raw)
    requests = driver.setup_requests(
        raw["executor"]["settings"], the_driver.caller_variables(state["world"], driver)
    )
    result = set_up(state, requests)
    state["stand_ins"]["setup"] = result
    state["facts"]["setup"] = "failed" if result.get("ok") is False else "ok"
