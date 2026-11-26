"""The check form: python3 -m shuttle check <input document>

Runs every check a run would make before it launches (the document, the input checks, the
executor driver's check, the gates, and whether the request id is already used) and nothing
more. It launches nothing, writes no record and does not claim the request id. An absent request
id is generated and printed first, as a run prints it. A refusal is printed as the outcome
record a run would have written, on one line; the last two lines are a verdict and the words
that passing is not a promise.

Exit codes (the check form writes no record, so the exit code is not about one):
  0  the check ran to its end, passing or refusing
  1  the document could not be read far enough to check; one line on standard error says why
"""

import json
from typing import TextIO

from shuttle import __version__
from shuttle.core import decisions, refusals
from shuttle.core.refusals import Found
from shuttle.core.shapes import (
    Conclusion,
    Decision,
    Operations,
    Receipt,
    ReceiptFacts,
    RunState,
)
from shuttle.shell import gates, input_checks, records, run


def _id_in_use(state: RunState) -> Found | None:
    source = run.header_source_of(state)
    location, request_id = source["records_location"], source["request_id"]
    world = state["world"]
    if world.files.exists(records.request_path(location, request_id)) or world.files.exists(
        records.outcome_path(location, request_id)
    ):
        return {
            "reason": "request_id_used",
            "step": "id_claim",
            "problem": decisions.claim_problem("used", request_id, location, ""),
        }
    return None


def _every_check(state: RunState) -> list[Found | None]:
    """Every check, in the order a run makes them. A document whose shape is refused has nothing
    further to look at."""
    world, raw = state["world"], state["raw"]
    shape = state["facts"].get("input_check")
    if shape:
        return [
            {"reason": shape, "step": "input_check", "problem": state["problems"]["input_check"]}
        ]
    found: list[Found | None] = [_id_in_use(state), *input_checks.run_input_checks(world, raw)]
    reason, text = run.driver_check(world, raw)
    if reason:
        found.append({"reason": reason, "step": "executor_driver_check", "problem": text or ""})
    gate_refusal, _ = gates.run_gates(world, raw.get("gates", []))
    return [*found, gate_refusal]


def _receipt(state: RunState, decision: Decision, problems: str) -> Receipt:
    world = state["world"]
    facts: ReceiptFacts = {
        "receipt_id": world.identity.new_id(),
        "execution_version": __version__,
        "host": world.identity.host_name(),
        "input_hash": state.get("input_hash"),
        "launched": False,
        "started_at": None,
        "ended_at": None,
        "executor_duration": None,
        "exit_code": None,
        "signal": None,
        "executor_driver_observations": None,
        "stand_ins": {},
        "reason_text": problems,
    }
    return decisions.build_receipt(decision, facts)


def _record_text(state: RunState, refusal: Found, problems: str) -> str:
    world = state["world"]
    # An id used before is not the refusal's step order: the decision takes the first found.
    decision: Decision = {
        "ending": "could_not_start",
        "reason": refusal["reason"],
        "failed_step": refusal["step"],
    }
    header = decisions.build_header(
        "outcome", run.header_source_of(state), world.identity.new_id(), world.clock.timestamp()
    )
    record = {"header": header, "receipt": _receipt(state, decision, problems)}
    return json.dumps(record)


def _conclude(state: RunState) -> Conclusion:
    if state["facts"].get("unreadable"):
        return decisions.conclude({"kind": "unreadable", "problem": state.get("problem")})
    found = _every_check(state)
    refusal = refusals.first_refusal(found)
    text = _record_text(state, refusal, refusals.all_problems(found)) if refusal else None
    return refusals.conclude_check(refusal, text)


def check(document_path: str, out: TextIO, err: TextIO, world: Operations) -> int:
    state: RunState = {
        "document_path": document_path,
        "out": out,
        "err": err,
        "world": world,
        "facts": {},
        "stand_ins": {},
        "problems": {},
        "signal": None,
    }
    run.step_read_and_validate_document(state)
    try:
        conclusion = _conclude(state)
    except Exception as error:  # fail closed: say what was not done
        conclusion = decisions.conclude(
            {
                "kind": "unreadable",
                "problem": f"the check could not be completed ({type(error).__name__}); "
                "nothing was launched or written; it says nothing about the input",
            }
        )
    for line in conclusion["stdout"]:
        out.write(line + "\n")
    for line in conclusion["stderr"]:
        err.write(line + "\n")
    return conclusion["exit"]
