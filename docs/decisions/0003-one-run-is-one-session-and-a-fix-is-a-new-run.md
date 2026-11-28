# One run is one session, and a fix is a new run

Status: accepted, 2026-11-24. Partly built as of `main` at `36ea58b`: a run starts one executor and ends with it, and a request id is used once. Not built: anything that hands a fix run what it needs.

## Context

The earlier way of working kept an agent open between rounds and fixed things in the same session. That practice was moved away from; what went wrong with it is not recorded beyond the design's statement that long sessions linger between rounds and report on their own work in prose, and that a caller could not tell how a run ended, what it changed, or whether anything it started was still alive.

## Decision

One run starts one executor and ends with it; nothing stays open between runs. A fix round after a run is a new run, handed what it needs, and no agent is kept open between rounds. A run with a used request id is refused, so a fix run takes a new id.

Built as of `36ea58b`:

- A run starts one executor through one command and writes its records (`README.md`), and the boundary stops everything the executor started.
- The run area is removed whole at every ending the command lives to see.
- The Codex driver starts the tool in its exit-when-done `exec` mode with the instruction on standard input. It copies in only what the tool needs; the tool's history, sessions and caches are left behind because they are never named. Nothing in Shuttle resumes a tool's earlier session.
- A final message that is a question ends the run as "ended by itself", with the statement "wrong shape" and the question kept as the receipt's `waiting_question`. The input document requires `thread` and `round`, which are copied unchanged into every record's header.

Not built: handing a fix run what it needs. The round and the loop are not Shuttle's; joining a build run to its judge run is out of scope. How a caller knows what a fix run must be handed is not decided.

## Alternatives considered

- **Keep the builder open between rounds and fix there.** Not taken; it is the practice being left. Why it was a problem is not recorded beyond the Context. A case for it was made before the decision: continuing the same session is cheap and keeps context, and suits a narrow fix round, while a fresh session suits a case where the earlier attempt's framing was the problem. After the decision, the holder of that view agreed with the decision on cost grounds: with a record to start from, a narrow fix round is a new run handed the gap, and the price is that each run re-reads its input.
- **Resume the tool's own earlier conversation.** From a reading of the Codex CLI source (gathered by helper agents, checked only through the paths they cited, and not run), Codex has a resume command. Whether it was weighed is not recorded, and Shuttle does not use it.
- **A service that supervises long-lived agents.** Not taken: one command is one run, and nothing stays in the background. Beyond the reasons here, no reason is recorded.

## Consequences

- Each fix run starts without the earlier run's context, and each run re-reads its input. No source says the records Shuttle writes are enough for a caller to hand over what the next run needs, and Shuttle does not do the handing.
- With an empty tool home, Codex rebuilds about 39 MB of caches each run (a figure from the Codex driver prototype). The driver starts with an empty tool home except what it copies in.
- A run cannot ask a human and carry on. In the first version "asked for a human" is not reachable as an ending: a tool that waits ends as "time limit", and a tool that exits with a question as its last message ends "ended by itself". One report of a set of probes (not re-run) found that Codex in non-interactive mode never showed an approval prompt, and that a tool whose endpoint was unreachable did not end by itself in 90 seconds.
- A used request id cannot be reused, so a retry needs a new id.
- It rules out an agent kept alive between requests, and any interactive exchange with one run.
- The word "session" comes from the proposal that led to this decision. It is also a vendor's word for what an agent executor has. Shuttle's `GLOSSARY.md` has no entry for a run or a session, and the code does not use the word for what a run is.
