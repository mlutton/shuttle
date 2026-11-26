"""The checks a run makes before it launches anything, as pure functions over plain data.

Each check returns None, or a refusal: the reason code, the failed step and one line saying what
was found. The shell gathers the facts (a file's hash, whether a location is taken, a gate's exit
code) and hands them in; nothing here touches the world. `first_refusal` picks the one a run
records; `all_problems` lists every one, for the check form.
"""

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from shuttle.core import fixed
from shuttle.core.shapes import Conclusion

_INPUT = "input_check"
_GATES = "gates"
_NAME_CHARACTERS = frozenset(fixed.ID_CHARACTERS)

# What the check form says last, whether it found a refusal or not.
PROMISE = (
    "check: passing is not a promise; it says what a run would refuse now, "
    "not what will happen after the launch"
)


class Found(TypedDict):
    reason: str
    step: str
    problem: str


def _found(reason: str, step: str, problem: str) -> Found:
    return {"reason": reason, "step": step, "problem": problem}


def parse_kinds(with_statement: str, without_statement: str) -> dict[str, bool]:
    """The kinds from the two data files: kind name to whether a statement is expected.

    One name per line; blank lines and lines that start with '#' are skipped. A name on both
    lists expects a statement.
    """
    kinds: dict[str, bool] = {}
    for text, expects in ((without_statement, False), (with_statement, True)):
        for line in text.splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                kinds[name] = expects
    return kinds


def check_kind(kind: str, kinds: Mapping[str, bool]) -> Found | None:
    if kind in kinds:
        return None
    return _found("unknown_kind", _INPUT, f"kind {kind!r} is not one of the known kinds")


def instruction_hash(instruction: str) -> str:
    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()


def check_instruction(instruction: str | None, claimed_hash: str | None) -> Found | None:
    """The instruction against the hash the caller supplied. Both absent is accepted."""
    if instruction is None and claimed_hash is None:
        return None
    if instruction is None or claimed_hash is None:
        return _found(
            "instruction_hash_mismatch",
            _INPUT,
            "the instruction and its hash must be given together",
        )
    if instruction_hash(instruction) != claimed_hash:
        return _found(
            "instruction_hash_mismatch",
            _INPUT,
            "the instruction does not match the hash supplied for it",
        )
    return None


def check_references(
    references: Sequence[Mapping[str, Any]], found: Mapping[str, Mapping[str, Any]]
) -> Found | None:
    """Each reference against what was found: {"hash", "size"} by name, absent when unreadable."""
    for reference in references:
        name = reference["name"]
        seen = found.get(name)
        if seen is None:
            return _found("reference_missing", _INPUT, f"reference {name!r} could not be read")
        if seen["hash"] != reference["hash"] or seen["size"] != reference["size"]:
            return _found(
                "reference_hash_mismatch",
                _INPUT,
                f"reference {name!r} does not match its hash and size",
            )
    return None


def check_statement_location(
    expects_statement: bool, location: str | None, occupied: bool
) -> Found | None:
    if not expects_statement:
        return None
    if location is None:
        return _found(
            "missing_setting", _INPUT, "this kind expects a statement: statement_location is needed"
        )
    if occupied:
        return _found(
            "statement_location_occupied",
            _INPUT,
            f"statement_location {location!r} is already taken; it must be empty at the start",
        )
    return None


def check_reach(reach: object) -> Found | None:
    """Reach is reserved: any content is refused."""
    if reach is None or (isinstance(reach, (dict, list)) and not reach):
        return None
    return _found("reach_not_available", _INPUT, "reach is reserved; leave it out or empty")


_SECRET_PREFIXES = ("sk-", "ghp_", "gho_", "ghs_", "github_pat_", "xox", "AKIA", "Bearer ")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-+/=.]{32,}")


def looks_like_credential(value: str) -> bool:
    text = value.strip()
    if text.startswith(_SECRET_PREFIXES) or "-----BEGIN" in text:
        return len(text) >= 8
    return bool(_LONG_TOKEN.fullmatch(text)) and any(c.isdigit() for c in text)


def _environment_entry_refusal(entry: object) -> Found | None:
    if isinstance(entry, str) and "=" in entry:
        name, _, value = entry.partition("=")
        if looks_like_credential(value):
            return _found(
                "credential_like_value",
                _INPUT,
                f"environment entry {name!r} was given a value that looks like a credential; "
                "name the variable only",
            )
        return _found(
            "missing_setting",
            _INPUT,
            f"environment entry {name!r} was given a value; name the variable only",
        )
    if not (isinstance(entry, str) and entry and all(c in _NAME_CHARACTERS for c in entry)):
        return _found("missing_setting", _INPUT, "environment must be a list of variable names")
    return None


def check_credential_values(entries: object) -> Found | None:
    """The first environment entry whose value looks like a credential, wherever it sits in the
    list, as a refusal made before the request id is claimed (so no record keeps the value). The
    value is never repeated."""
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, str) and "=" in entry:
            name, _, value = entry.partition("=")
            if looks_like_credential(value):
                return _found(
                    "credential_like_value",
                    _INPUT,
                    f"environment entry {name!r} was given a value that looks like a credential; "
                    "nothing was done and no record was written, so the request id is NOT spent; "
                    "name the variable only",
                )
    return None


def check_environment_entries(entries: object) -> Found | None:
    """The environment part: names only. A value given with a name is refused, and one that looks
    like a credential is named as such (the value is never repeated)."""
    if not isinstance(entries, list):
        return _found("missing_setting", _INPUT, "environment must be a list of variable names")
    for entry in entries:
        refusal = _environment_entry_refusal(entry)
        if refusal:
            return refusal
    return None


def gate_answer(started: bool, exit_code: int | None, timed_out: bool) -> str:
    """A gate's answer from how it ended: exit 0 is yes, exit 1 is no, anything else is failed."""
    if not started or timed_out or exit_code is None:
        return "failed"
    return {0: "yes", 1: "no"}.get(exit_code, "failed")


def check_gates(answers: Sequence[tuple[str, str]]) -> Found | None:
    """The gates' answers, in order: the first that is not a yes decides."""
    for name, answer in answers:
        if answer == "yes":
            continue
        reason = "gate_said_no" if answer == "no" else "gate_failed"
        return _found(reason, _GATES, f"gate {name!r} answered {answer}")
    return None


def first_refusal(found: Sequence[Found | None]) -> Found | None:
    for refusal in found:
        if refusal:
            return refusal
    return None


def all_problems(found: Sequence[Found | None]) -> str:
    return "; ".join(refusal["problem"] for refusal in found if refusal)


def fill_request_id(raw: Any, generated: str) -> Any:
    """The document with a request id when it gave none; anything else is returned as it is."""
    if isinstance(raw, dict) and "request_id" not in raw:
        return {**raw, "request_id": generated}
    return raw


def conclude_check(refusal: Found | None, record_text: str | None) -> Conclusion:
    """What the check form prints: the refusal's record when there is one, then a verdict line
    and the promise line. The request id was printed first, as a run prints it."""
    lines = [record_text] if refusal and record_text else []
    lines.append(f"check: refused: {refusal['reason']}" if refusal else "check: no refusal found")
    lines.append(PROMISE)
    return {"stdout": lines, "stderr": [], "exit": 0}
