"""Step 6, take the opening fingerprint: the place's own commit, after confirming the checkout is clean.

No commit is made. The place was looked at by the input checks before anything started; it is
looked at again here, since the gates ran in between, and a place that is not clean now (or not
there, or not a checkout) is a failed opening freeze: no fingerprint, and the executor does not
start.
"""

from shuttle.core import place
from shuttle.core.shapes import RunState
from shuttle.shell import the_place


def step(state: RunState) -> None:
    world, raw = state["world"], state["raw"]
    started = world.clock.now()
    facts = the_place.look(world, raw)
    refusal = place.check_place(raw.get("place"), facts)
    result = place.opening_result(refusal, facts, world.clock.now() - started)
    state["stand_ins"]["opening_fingerprint"] = result
    state["facts"]["opening_freeze"] = "ok" if result["ok"] else "failed"
    if refusal:
        state["problems"]["opening_freeze"] = refusal["problem"]
