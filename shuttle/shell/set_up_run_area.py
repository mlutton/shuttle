"""Step 5, set up the run area: the run's own folder, and what the driver's setup asks of it.

The folder is made new, empty and private, named for the run, with a lock held beside it for as
long as the run lives. The driver's requests (shuttle.core.run_area) are
turned into a plan by the core and carried out here, in order, through the world's operations:
every path the plan names is inside the area, except the sources it copies from, which are only
read. The folder is remembered in the state as soon as
it exists, so the tear-down finds it however this step ends. A refused plan or a failed action
fails the step with one line saying which.
"""

import contextlib
from collections.abc import Sequence
from typing import assert_never

from shuttle.core import run_area
from shuttle.core.shapes import Operations, RunState, SetupRequest, SetupStep, StepResult
from shuttle.shell import sweep_run_areas, the_driver


def _carry_out(world: Operations, step: SetupStep) -> None:
    files = world.files
    match step["do"]:
        case "folder":
            files.make_folders(step["target"])
        case "copy":
            # a link is followed only where the request said so (a login kept elsewhere and linked
            # to); the file it leads to is what is copied
            source = (
                world.boundary.resolve(step["source"]) if step.get("follow") else step["source"]
            )
            if step.get("optional") and not files.exists(source):
                return  # the request said a missing source is no error
            files.copy_path(source, step["target"], step["leave_out"])
        case "write":
            files.write_new(step["target"], step["text"])
        case "writable":
            files.make_writable(step["target"])
        case never:
            assert_never(never)  # the type checker refuses a kind of step with no case here


def _for(step: SetupStep) -> str:
    """What a failed copy names: the file it was to copy and what to do about it. The name is the
    caller's own path, shown as a quoted literal."""
    if step["do"] != "copy":
        return ""
    return (
        f" on {step['source']!r}; give a regular file the run may read at that path "
        "(a pipe, a device or a socket cannot be copied), or take it out of the tool's setup"
    )


def _make_area(world: Operations, run_part: str) -> str:
    """The run's area and its lock. The lock is made and held first, so the area is never on disk
    with its lock free: a sweep that finds the area finds the lock held. A lock whose area could
    not be made is let go and removed."""
    files = world.files
    area = f"{files.temporary_folder()}/{run_area.area_name(run_part)}"
    lock = run_area.lock_path(area)
    files.create_lock(lock)
    try:
        files.make_private_folder(area)
    except BaseException:
        with contextlib.suppress(OSError):
            files.release_lock(lock, True)
        raise
    return area


def set_up(state: RunState, requests: Sequence[SetupRequest]) -> StepResult:
    world = state["world"]
    problem = run_area.refusal(requests)
    if problem:  # refused before anything is made
        state["problems"]["setup"] = f"{problem}; nothing was made and nothing was launched"
        return {"ok": False}
    sweep_run_areas.sweep_before_the_run_makes_its_area(state)
    area = _make_area(world, state["run_part"])
    state["run_area"] = area
    state["setup_variables"] = {}
    plan = run_area.plan(area, requests)
    for number, step in enumerate(plan["steps"], 1):
        try:
            _carry_out(world, step)
        except OSError as error:
            state["problems"]["setup"] = (
                f"setup step {number} ({step['do']}) failed ({type(error).__name__})"
                f"{_for(step)}; nothing was launched"
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
