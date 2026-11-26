"""The command driver: the executor driver for a plain command.

An executor driver offers four functions (check, launch, observe, declare) and
its declarations as data. It never names an ending. There is no base class.
"""

from collections.abc import Mapping
from typing import Any

from shuttle.shapes import LaunchSpec

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


def check(settings: Mapping[str, Any], tool_found: bool) -> str | None:
    """Pure: the reason code that refuses these settings, or None."""
    if not tool_found:
        return "tool_not_installed"
    return None


def launch(settings: Mapping[str, Any]) -> LaunchSpec:
    """Pure: the one command to start. It exits when done. The environment is built by the core."""
    return {"argv": [settings["command"]] + list(settings["arguments"])}


def observe(none_fact: str, cannot_tell: str) -> dict[str, str]:
    """Pure: the driver group of the receipt. A plain command reports nothing of its own.

    "none" means looked and nothing there; "cannot tell" means could not look.
    """
    return {
        "executor_driver_name": NAME,
        "executor_driver_version": VERSION,
        "tool_version": none_fact,
        "model": none_fact,
        "effort": none_fact,
        "tokens_in": none_fact,
        "tokens_out": none_fact,
        "tokens_cached": none_fact,
        "activity": none_fact,
        "session_id": none_fact,
        "refused_actions": none_fact,
        "quota_level": none_fact,
        "vendor_limit_reached": none_fact,
        "vendor_limit_reset": none_fact,
        "tool_made_own_commits": cannot_tell,
        "load_lists_differ": none_fact,
        "load_lists_kept_file": none_fact,
        "changed_self_loaded_file": none_fact,
        "waiting_question": none_fact,
    }
