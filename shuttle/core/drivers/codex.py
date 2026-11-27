"""The Codex driver: the executor driver for the Codex command-line tool, run once and exiting.

It offers the functions of `shuttle.core.drivers.interface`. Everything here is a decision over
plain data: nothing starts the tool, opens its login or reads a file. The facts it was shaped
from (the launch settings, the sandbox settings, what the event stream and the session record
hold) are those of codex-cli 0.172.0 as of 2026-11-25; a newer tool may differ, and a field that
is not found reads "cannot tell" rather than a guess.

The instruction reaches the tool on standard input. Its statement is its final message, which
the tool writes to a file the launch command names; the driver hands that text back and judges
nothing: a message that is not the statement's shape is the shell's to refuse, and the ending is
the decisions' to name.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

from shuttle.core import pairs
from shuttle.core.shapes import (
    DriverFacts,
    ExecutorDriverGroup,
    LaunchContext,
    LaunchSpec,
    Observed,
    OutputFiles,
    Pair,
    SavedOutput,
    Settings,
    SetupRequest,
)

NAME = "codex"
VERSION = "1"
READS: tuple[str, ...] = ("CODEX_HOME", "HOME")

PROGRAM = "codex"
_SETTINGS = ("model", "effort")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}")
_EFFORT = re.compile(r"[a-z]{1,16}")
# Where the tool leaves its own files, below the home it is given in the run area.
_HOME = "home"
_CONFIG = "config.toml"
_LOGIN = "auth.json"

DECLARATIONS: dict[str, list[str]] = {
    "loads_by_itself": [
        "the copied settings file",
        "AGENTS.md in the place",
        "skills, plugins and servers the settings file names",
    ],
    "runs_by_itself": [
        "shell commands the model chooses, inside the tool's own sandbox",
        "servers the settings file names",
    ],
    "needs_setup": [
        "a tool home in the run area",
        "the settings file copied in",
        "the login shared by a link",
        "folders for temporary files, caches and saved output",
    ],
}


def declare() -> dict[str, list[str]]:
    return DECLARATIONS


def settings_refusal(settings: Settings) -> tuple[str, str] | None:
    unknown = ", ".join(sorted(set(settings) - set(_SETTINGS)))
    if unknown:
        return "unknown_setting", f"unknown setting: {unknown}"
    model = settings.get("model")
    if not isinstance(model, str) or _MODEL.fullmatch(model) is None:
        return "missing_setting", "setting 'model' is missing or is not a model's name"
    effort = settings.get("effort")
    if "effort" in settings and (not isinstance(effort, str) or _EFFORT.fullmatch(effort) is None):
        return "missing_setting", "setting 'effort' is not a word of lower-case letters"
    return None


def program(settings: Settings) -> str:
    return PROGRAM


def _tool_home(environment: Mapping[str, str]) -> str | None:
    """The caller's own tool home: where the tool looks for its files unless told."""
    named = environment.get("CODEX_HOME")
    held = named or (environment["HOME"] + "/.codex" if environment.get("HOME") else None)
    return held if held and held.startswith("/") and "\0" not in held else None


def login_path(environment: Mapping[str, str]) -> str | None:
    home = _tool_home(environment)
    return None if home is None else f"{home}/{_LOGIN}"


def check(settings: Settings, facts: DriverFacts) -> tuple[str, str] | None:
    refusal = settings_refusal(settings)
    if refusal:
        return refusal
    if facts["network"] is None:
        return "missing_setting", "network is not in the document: say 'on' or 'off'"
    if facts["changes_allowed"] is None:
        return "missing_setting", "changes_to_place is not in the document: say 'allowed' or 'not'"
    if not facts["tool_found"]:
        return (
            "tool_not_installed",
            f"the program {PROGRAM!r} was not found; install it or name another executor",
        )
    if not facts["login_found"]:
        return "no_login", "no login was found for the tool; log in with it once, then run again"
    return None


def _keep(name: str) -> SetupRequest:
    """A request that only makes the folder above `name`, by writing an empty file in it."""
    return {"action": "write", "name": f"{name}/keep.txt", "text": ""}


def setup_requests(settings: Settings, environment: Mapping[str, str]) -> list[SetupRequest]:
    """A tool home inside the run area holding the settings file (copied) and the login (shared
    by a link, never copied or opened). Nothing else of the caller's tool home is taken: its
    history, sessions and caches are left behind because they are never named."""
    home = _tool_home(environment)
    if home is None:
        return []
    return [
        {"action": "copy", "name": f"{_HOME}/{_CONFIG}", "source": f"{home}/{_CONFIG}"},
        {"action": "share", "name": f"{_HOME}/{_LOGIN}", "source": f"{home}/{_LOGIN}"},
        _keep("tmp"),
        _keep("cache"),
        _keep("out"),
        {"action": "variable", "variable": "CODEX_HOME", "in_run_area": _HOME},
        {"action": "variable", "variable": "TMPDIR", "in_run_area": "tmp"},
        {"action": "variable", "variable": "XDG_CACHE_HOME", "in_run_area": "cache"},
    ]


def output_files(run_area: str) -> OutputFiles:
    return {
        "events": f"{run_area}/out/events.jsonl",
        "last_message": f"{run_area}/out/last-message.txt",
    }


def launch(settings: Settings, context: LaunchContext) -> LaunchSpec:
    """`exec` mode with the event stream on standard output and the final message in a file.

    The two standard settings become the tool's own sandbox: changes allowed or not is its
    workspace-write or read-only mode, network on or off is its sandbox's network setting. The
    sandbox is always on.
    """
    files = output_files(context["run_area"])
    argv = [PROGRAM, "exec", "-C", context["place"], "-m", settings["model"]]
    if "effort" in settings:
        argv += ["-c", f'model_reasoning_effort="{settings["effort"]}"']
    argv += ["-s", "workspace-write" if context["changes_allowed"] else "read-only"]
    argv += ["-c", "sandbox_workspace_write.exclude_slash_tmp=true"]
    network = "true" if context["network"] else "false"
    argv += ["-c", f"sandbox_workspace_write.network_access={network}"]
    argv += ["--json", "-o", files["last_message"], "-"]
    return {"argv": argv, "output_to": files["events"]}


# ---------------------------------------------------------------------------- observing


def _lines(text: str | None) -> list[dict[str, Any]] | None:
    """The JSON objects among the lines of a saved file; a line that is not one is skipped."""
    if text is None:
        return None
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            held = json.loads(line)
        except ValueError:
            continue
        if isinstance(held, dict):
            found.append(held)
    return found


def _number(held: object) -> int | float | None:
    return held if isinstance(held, int | float) and not isinstance(held, bool) else None


def _first(events: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((e for e in events if e.get("type") == kind), None)


def _payload(record: list[dict[str, Any]] | None, kind: str) -> dict[str, Any] | None:
    """The payload of the last record of this type (its own, or its payload's) in the session
    record, or None."""
    for entry in reversed(record or []):
        held = entry.get("payload")
        if isinstance(held, dict) and kind in (entry.get("type"), held.get("type")):
            return held
    return None


def _count(held: object) -> int | None:
    """A token count the tool gave: a whole number that is not negative; anything else is not one."""
    return held if isinstance(held, int) and not isinstance(held, bool) and held >= 0 else None


def _tokens(events: list[dict[str, Any]] | None) -> tuple[Pair, Pair, Pair]:
    """Tokens in, out and cached, summed over the turns the stream finished.

    No finished turn is "none" (the run did not get that far, and the tool gives no usage then).
    A count a finished turn does not give as a number is "cannot tell", never zero.
    """
    if events is None:
        return pairs.cannot_tell(), pairs.cannot_tell(), pairs.cannot_tell()
    turns = [e for e in events if e.get("type") == "turn.completed"]
    if not turns:
        return pairs.none(), pairs.none(), pairs.none()
    usages: list[dict[str, Any]] = [
        t["usage"] if isinstance(t.get("usage"), dict) else {} for t in turns
    ]

    def total(name: str) -> Pair:
        counts = [_count(u.get(name)) for u in usages]
        if any(c is None for c in counts):
            return pairs.cannot_tell()
        return pairs.value(sum(c for c in counts if c is not None))

    return total("input_tokens"), total("output_tokens"), total("cached_input_tokens")


def _from_record(record: list[dict[str, Any]] | None, kind: str, key: str) -> Pair:
    if record is None:
        return pairs.cannot_tell()
    held = (_payload(record, kind) or {}).get(key)
    return pairs.value(held) if isinstance(held, str) and held else pairs.cannot_tell()


def _limits(record: list[dict[str, Any]] | None) -> tuple[Pair, Pair, Pair]:
    """The quota used, whether a limit was reached, and when it resets (only if it was)."""
    limits = (_payload(record, "token_count") or {}).get("rate_limits")
    if not isinstance(limits, dict):
        return pairs.cannot_tell(), pairs.cannot_tell(), pairs.cannot_tell()
    held = limits.get("primary")
    primary: dict[str, Any] = held if isinstance(held, dict) else {}
    used, reset = _number(primary.get("used_percent")), _number(primary.get("resets_at"))
    reached = limits.get("rate_limit_reached_type") is not None
    return (
        pairs.cannot_tell() if used is None else pairs.value(used),
        pairs.value(reached),
        pairs.value(reset) if reached and reset is not None else pairs.none(),
    )


def _is_question(message: str | None) -> Pair:
    if message is None:
        return pairs.cannot_tell()
    return pairs.value(message) if message.rstrip().endswith("?") else pairs.none()


def observe(settings: Settings, saved: SavedOutput) -> Observed:
    """The driver group from the saved event stream, last message and session record, and the
    last message as the statement. A file that could not be read, or a field it lacks (a count
    that is not a number, a start with no id), is "cannot tell"; "none" is for a stream that ran
    and holds no finished turn or no start at all.

    Time is not here: the tool writes none, and the run's own clock measures it.
    """
    events, record = _lines(saved["events"]), _lines(saved["session_record"])
    started = None if events is None else _first(events, "thread.started")
    session = pairs.cannot_tell() if events is None else pairs.none()
    if started:  # a start that gives no usable id is a field the tool lacks
        held = started.get("thread_id")
        session = pairs.value(held) if isinstance(held, str) and held else pairs.cannot_tell()
    done = None if events is None else sum(1 for e in events if e.get("type") == "item.completed")
    unknown = pairs.cannot_tell()
    tokens_in, tokens_out, tokens_cached = _tokens(events)
    quota, reached, reset = _limits(record)
    group: ExecutorDriverGroup = {
        "executor_driver_name": pairs.value(NAME),
        "executor_driver_version": pairs.value(VERSION),
        "tool_version": _from_record(record, "session_meta", "cli_version"),
        "model": _from_record(record, "turn_context", "model"),
        "effort": _from_record(record, "turn_context", "effort"),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cached": tokens_cached,
        "activity": unknown if done is None else pairs.value(done),
        "session_id": session,
        "refused_actions": unknown,  # the tool marks a refused action only in the text it prints
        "quota_level": quota,
        "vendor_limit_reached": reached,
        "vendor_limit_reset": reset,
        "tool_made_own_commits": unknown,
        "load_lists_differ": unknown,
        "load_lists_kept_file": unknown,
        "changed_self_loaded_file": unknown,
        "waiting_question": _is_question(saved["last_message"]),
    }
    return {"group": group, "statement_text": saved["last_message"] or None}
