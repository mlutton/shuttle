"""The command driver: the executor driver for a plain command.

It offers the functions of `shuttle.core.drivers.interface`. It asks of the run area nothing, has
no login, and leaves no statement of its own: the command writes the statement file itself.
"""

from collections.abc import Mapping

from shuttle.core import pairs
from shuttle.core.shapes import (
    DriverFacts,
    ExecutorDriverGroup,
    LaunchContext,
    LaunchSpec,
    Observed,
    OutputFiles,
    SavedOutput,
    Settings,
    SetupRequest,
)

NAME = "command"
VERSION = "1"
READS: tuple[str, ...] = ()

_SETTINGS = ("command", "arguments")

# What this tool loads and runs by itself, and what it needs set up: nothing.
DECLARATIONS: dict[str, list[str]] = {
    "loads_by_itself": [],
    "runs_by_itself": [],
    "needs_setup": [],
}


def declare() -> dict[str, list[str]]:
    return DECLARATIONS


def settings_refusal(settings: Settings) -> tuple[str, str] | None:
    unknown = ", ".join(sorted(set(settings) - set(_SETTINGS)))
    if unknown:
        return "unknown_setting", f"unknown setting: {unknown}"
    command, arguments = settings.get("command"), settings.get("arguments")
    if not isinstance(command, str) or not command:
        return "missing_setting", "setting 'command' is missing"
    if not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
        return "missing_setting", "setting 'arguments' is missing or not a list of text"
    return None


def program(settings: Settings) -> str:
    return str(settings["command"])


def login_path(environment: Mapping[str, str]) -> str | None:
    return None


def check(settings: Settings, facts: DriverFacts) -> tuple[str, str] | None:
    if not facts["tool_found"]:
        return (
            "tool_not_installed",
            f"the command {settings['command']!r} was not found; install it or name one that exists",
        )
    return None


def setup_requests(settings: Settings, environment: Mapping[str, str]) -> list[SetupRequest]:
    return []


def launch(settings: Settings, context: LaunchContext) -> LaunchSpec:
    """The command and its arguments. The environment is built by the core."""
    return {"argv": [settings["command"]] + list(settings["arguments"])}


def output_files(run_area: str) -> OutputFiles:
    return {}


def observe(settings: Settings, saved: SavedOutput) -> Observed:
    """A plain command reports nothing of its own, and has no statement but its file.

    "none" means looked and nothing there; "cannot tell" means could not look.
    """
    nothing = pairs.none()
    group: ExecutorDriverGroup = {
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
    return {"group": group, "statement_text": None}
