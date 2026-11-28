"""The command driver: the executor driver for a plain command.

It offers the functions of `shuttle.core.drivers.interface`. It asks of the run area nothing, has
no login, and leaves no statement of its own: the command writes the statement file itself, at the path in the run area its notice gives it. It
refuses a document that asks for `network` off, since nothing yet enforces that for it. Changes to
the place not allowed needs no refusal here: the box makes the place read-only whichever driver
runs.
"""

from collections.abc import Mapping

from shuttle.core import pairs
from shuttle.core.run_area import standard_error_path, standard_output_path
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
    StatementArrival,
)

NAME = "command"
VERSION = "1"
STATEMENT: StatementArrival = "file"
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
    # This driver has no sandbox of its own (as the Codex driver's tool has), and the box does
    # not yet cut the network, so that restriction would be silently unhonoured: refuse it.
    if facts["network"] is False:
        return (
            "unknown_setting",
            "the command driver cannot enforce network off yet; leave the setting out or "
            "choose an executor that can",
        )
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
    """Its standard output and standard error, which the run keeps; it has no final message."""
    return {
        "standard_output": standard_output_path(run_area),
        "standard_error": standard_error_path(run_area),
    }


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
    return {"group": group, "reply_given": False}
