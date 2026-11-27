"""The Codex driver: the executor driver for the Codex command-line tool, run once and exiting.

It offers the functions of `shuttle.core.drivers.interface`. Everything here is a decision over
plain data: nothing starts the tool, opens its login or reads a file. The facts it was shaped
from (the launch settings, the sandbox settings, what the event stream and the session record
hold) are those of codex-cli 0.172.0 as of 2026-11-25; a newer tool may differ, and a field that
is not found reads "cannot tell" rather than a guess.

The instruction reaches the tool on standard input. Its statement is its final message, which
the tool writes to a file the launch command names; the driver says whether there is one and judges
nothing: a message that is not the statement's shape is the shell's to refuse, and the ending is
the decisions' to name.

What the tool leaves is read a line at a time, so nothing held grows with the file. A line the
shell had to cut is judged by its first bytes: when they show it was not one a field is read from,
it costs nothing; otherwise what it would have held reads "cannot tell".
"""

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from shuttle.core import pairs
from shuttle.core.shapes import (
    DriverFacts,
    ExecutorDriverGroup,
    LaunchContext,
    LaunchSpec,
    Line,
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
        {
            "action": "copy",
            "name": f"{_HOME}/{_CONFIG}",
            "source": f"{home}/{_CONFIG}",
            "optional": True,  # the tool starts without one, as it does in an empty tool home
        },
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

# The events whose fields a number or an id is read from; a cut line of any other kind is no loss.
_READ_FROM = ("turn.completed", "thread.started")
_KIND = re.compile(rb'\{\s*"type"\s*:\s*"([A-Za-z0-9_.]+)"')
_COUNTS = {
    "tokens_in": "input_tokens",
    "tokens_out": "output_tokens",
    "tokens_cached": "cached_input_tokens",
}


def _object(line: bytes) -> dict[str, Any] | None:
    try:
        held = json.loads(line)
    except ValueError:
        return None
    return held if isinstance(held, dict) else None


def _kind_of_cut(prefix: bytes) -> str | None:
    """The type a cut line opens with, when its first bytes say."""
    found = _KIND.match(prefix)
    return found.group(1).decode() if found else None


def _count(held: object) -> int | None:
    """A token count the tool gave: a whole number that is not negative; anything else is not one."""
    return held if isinstance(held, int) and not isinstance(held, bool) and held >= 0 else None


class _Events:
    """What the event stream says, folded one line at a time."""

    def __init__(self) -> None:
        self.completed_items = 0
        self.turns = 0
        self.counts: dict[str, int | None] = {name: 0 for name in _COUNTS}
        self.started = False
        self.thread_id: str | None = None
        self.lost = False  # a cut line that may have held a count or the thread id

    def add(self, line: bytes, cut: bool) -> None:
        kind = _kind_of_cut(line) if cut else None
        event = None if cut else _object(line)
        if event is not None:
            kind = event.get("type") if isinstance(event.get("type"), str) else None
        if cut and (kind is None or kind in _READ_FROM):
            self.lost = True
        if kind == "item.completed":
            self.completed_items += 1
        if event is None:
            return
        if kind == "thread.started":
            self.started = True
            held = event.get("thread_id")
            self.thread_id = held if isinstance(held, str) and held else None
        elif kind == "turn.completed":
            self.turns += 1
            held_usage = event.get("usage")
            usage: dict[str, Any] = held_usage if isinstance(held_usage, dict) else {}
            for name, key in _COUNTS.items():
                added, had = _count(usage.get(key)), self.counts[name]
                self.counts[name] = None if added is None or had is None else had + added

    def tokens(self) -> dict[str, Pair]:
        """Each count: "none" when no turn finished, "cannot tell" when one was lost or gave no
        number for it, else the sum over the finished turns. A count is never made up as zero."""
        if self.lost:
            return {name: pairs.cannot_tell() for name in _COUNTS}
        if self.turns == 0:
            return {name: pairs.none() for name in _COUNTS}
        return {
            name: pairs.cannot_tell() if held is None else pairs.value(held)
            for name, held in self.counts.items()
        }

    def session(self) -> Pair:
        if self.lost:
            return pairs.cannot_tell()
        if not self.started:
            return pairs.none()
        return pairs.cannot_tell() if self.thread_id is None else pairs.value(self.thread_id)

    def activity(self) -> Pair:
        return pairs.cannot_tell() if self.lost else pairs.value(self.completed_items)


def _fold_events(lines: Iterable[Line] | None) -> _Events | None:
    if lines is None:
        return None
    folded = _Events()
    for line, cut in lines:
        folded.add(line, cut)
    return folded


# What the session record is read for: the last record of each of these types, or that it was lost.
_RECORD_KINDS = ("session_meta", "turn_context", "token_count")


def _fold_record(lines: Iterable[Line] | None) -> tuple[dict[str, dict[str, Any]], set[str]] | None:
    """The payload of the last record of each kind that is read, and the kinds a cut line may
    have held (a cut line of an unknown type, or one that wraps its type in a payload)."""
    if lines is None:
        return None
    found: dict[str, dict[str, Any]] = {}
    lost: set[str] = set()
    for line, cut in lines:
        if cut:
            kind = _kind_of_cut(line)
            lost |= {k for k in _RECORD_KINDS if kind in (None, "event_msg", k)}
            continue
        entry = _object(line)
        held = entry.get("payload") if entry else None
        if not isinstance(entry, dict) or not isinstance(held, dict):
            continue
        for kind in _RECORD_KINDS:
            if kind in (entry.get("type"), held.get("type")):
                found[kind] = held
    return found, lost


def _from_record(
    record: tuple[dict[str, dict[str, Any]], set[str]] | None, kind: str, key: str
) -> Pair:
    if record is None or kind in record[1]:
        return pairs.cannot_tell()
    held = record[0].get(kind, {}).get(key)
    return pairs.value(held) if isinstance(held, str) and held else pairs.cannot_tell()


def _number(held: object) -> int | float | None:
    return held if isinstance(held, int | float) and not isinstance(held, bool) else None


def _limits(
    record: tuple[dict[str, dict[str, Any]], set[str]] | None,
) -> tuple[Pair, Pair, Pair]:
    """The quota used, whether a limit was reached, and when it resets (only if it was)."""
    unknown = pairs.cannot_tell(), pairs.cannot_tell(), pairs.cannot_tell()
    if record is None or "token_count" in record[1]:
        return unknown
    limits = record[0].get("token_count", {}).get("rate_limits")
    if not isinstance(limits, dict):
        return unknown
    held = limits.get("primary")
    primary: dict[str, Any] = held if isinstance(held, dict) else {}
    used, reset = _number(primary.get("used_percent")), _number(primary.get("resets_at"))
    reached = limits.get("rate_limit_reached_type") is not None
    return (
        pairs.cannot_tell() if used is None else pairs.value(used),
        pairs.value(reached),
        pairs.value(reset) if reached and reset is not None else pairs.none(),
    )


def _read_last_message(lines: Iterable[Line] | None) -> tuple[bool, Pair]:
    """(whether the tool gave a final message, the waiting question): the message's last line
    that is not blank when that line ends in a question mark. A last line that was cut, or is not
    text, cannot be told."""
    if lines is None:
        return False, pairs.cannot_tell()
    given = False
    last: Line | None = None
    for line, cut in lines:
        given = True
        if line.strip() or cut:
            last = (line, cut)
    if last is None:
        return given, pairs.none()
    try:
        text = last[0].decode("utf-8")
    except UnicodeDecodeError:
        return given, pairs.cannot_tell()
    if last[1]:
        return given, pairs.cannot_tell()
    return given, pairs.value(text.strip()) if text.rstrip().endswith("?") else pairs.none()


def observe(settings: Settings, saved: SavedOutput) -> Observed:
    """The driver group from the saved event stream, last message and session record, each read
    once, a line at a time. A file that could not be opened, or a field it lacks (a count that is
    not a number, a start with no id), is "cannot tell"; "none" is for a stream that ran and holds
    no finished turn or no start at all.

    Time is not here: the tool writes none, and the run's own clock measures it.
    """
    events, record = _fold_events(saved["events"]), _fold_record(saved["session_record"])
    given, question = _read_last_message(saved["last_message"])
    unknown = pairs.cannot_tell()
    tokens = events.tokens() if events else {name: unknown for name in _COUNTS}
    quota, reached, reset = _limits(record)
    group: ExecutorDriverGroup = {
        "executor_driver_name": pairs.value(NAME),
        "executor_driver_version": pairs.value(VERSION),
        "tool_version": _from_record(record, "session_meta", "cli_version"),
        "model": _from_record(record, "turn_context", "model"),
        "effort": _from_record(record, "turn_context", "effort"),
        "tokens_in": tokens["tokens_in"],
        "tokens_out": tokens["tokens_out"],
        "tokens_cached": tokens["tokens_cached"],
        "activity": events.activity() if events else unknown,
        "session_id": events.session() if events else unknown,
        "refused_actions": unknown,  # the tool marks a refused action only in the text it prints
        "quota_level": quota,
        "vendor_limit_reached": reached,
        "vendor_limit_reset": reset,
        "tool_made_own_commits": unknown,
        "load_lists_differ": unknown,
        "load_lists_kept_file": unknown,
        "changed_self_loaded_file": unknown,
        "waiting_question": question,
    }
    return {"group": group, "reply_given": given}
