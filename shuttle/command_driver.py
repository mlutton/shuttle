"""The command driver: the executor driver for a plain command.

An executor driver offers four functions (check, launch, observe, declare) and
its declarations as data. It never names an ending. There is no base class.
"""

import shutil

NAME = "command"
VERSION = "1"

# What this tool loads and runs by itself, and what it needs set up: nothing.
DECLARATIONS = {
    "loads_by_itself": [],
    "runs_by_itself": [],
    "needs_setup": [],
}


def declare():
    return DECLARATIONS


def locate(settings):
    """Shell: whether the command can be found and run. Returns True or False."""
    try:
        return shutil.which(settings["command"]) is not None
    except (ValueError, OSError):
        return False


def check(settings, tool_found):
    """Pure: the reason code that refuses these settings, or None."""
    if not tool_found:
        return "tool_not_installed"
    return None


def launch(settings):
    """Pure: the one command to start. It exits when done. The environment is built by the core."""
    return {"argv": [settings["command"]] + list(settings["arguments"])}


def observe(none_fact, cannot_tell):
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
