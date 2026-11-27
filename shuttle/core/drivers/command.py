"""The command driver: the executor driver for a plain command.

An executor driver offers four functions (check, launch, observe, declare) and
its declarations as data. It never names an ending. There is no base class.
"""

from shuttle.core import pairs
from shuttle.core.shapes import CommandSettings, ExecutorDriverGroup, LaunchSpec, SetupRequest

NAME = "command"
VERSION = "1"

# What this tool loads and runs by itself, and what it needs set up: nothing.
DECLARATIONS: dict[str, list[str]] = {
    "loads_by_itself": [],
    "runs_by_itself": [],
    "needs_setup": [],
}


def declare() -> dict[str, list[str]]:
    return DECLARATIONS


def setup_requests(settings: CommandSettings) -> list[SetupRequest]:
    """Pure: what this tool asks of the run area. A plain command asks for nothing."""
    return []


def check(settings: CommandSettings, tool_found: bool) -> str | None:
    """Pure: the reason code that refuses these settings, or None."""
    if not tool_found:
        return "tool_not_installed"
    return None


def launch(settings: CommandSettings) -> LaunchSpec:
    """Pure: the one command to start. It exits when done. The environment is built by the core."""
    return {"argv": [settings["command"]] + list(settings["arguments"])}


def observe() -> ExecutorDriverGroup:
    """Pure: the driver group of the receipt. A plain command reports nothing of its own.

    "none" means looked and nothing there; "cannot tell" means could not look.
    """
    nothing = pairs.none()
    return {
        "executor_driver_name": pairs.value(NAME),
        "executor_driver_version": pairs.value(VERSION),
        "tool_version": nothing,
        "model": nothing,
        "effort": nothing,
        "tokens_in": nothing,
        "tokens_out": nothing,
        "tokens_cached": nothing,
        "activity": nothing,
        "session_id": nothing,
        "refused_actions": nothing,
        "quota_level": nothing,
        "vendor_limit_reached": nothing,
        "vendor_limit_reset": nothing,
        "tool_made_own_commits": pairs.cannot_tell(),
        "load_lists_differ": nothing,
        "load_lists_kept_file": nothing,
        "changed_self_loaded_file": nothing,
        "waiting_question": nothing,
    }
