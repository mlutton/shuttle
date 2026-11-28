# A run can carry a memory cap, held by the scope

Status: accepted, 2026-11-27. Built as of `main` at `d89f730` (pull request 37): an optional `memory_limit_bytes` in the input document, held by the scope as a cap on memory and swap together, with `memory_limit` as a seventh ending. Not built: see Consequences.

## Context

The scope (see [0002](0002-the-boundary-is-a-scope-around-bubblewrap.md)) can carry a memory cap, and nothing set one. An out-of-memory kill on a development machine, from a test that read endless input, had already taken the other work on the machine with it. A cap held by the scope means an executor that grows without bound is ended by the boundary, and not by the machine's out-of-memory killer taking something else with it.

A trial by hand on one machine (systemd 262, bubblewrap 0.13.1) came before the design. The memory controller was delegated to the user's systemd, so a user scope could carry a cap. With swap available, a cap alone ended nothing: a program that allocated 300 MB under a 64 MB cap finished normally and was only slower. With swap also capped to zero, going over the cap ended the scope with the result `oom-kill`, readable after the run. The peak memory was readable after the end only for a scope that had failed. The trial was not repeated.

## Decision

- The cap is a setting in the input document, `memory_limit_bytes`: a whole number of bytes from 1 to 2^62. It is optional and has no default. Left out, the run has no cap and the machine is not asked anything.
- The scope carries `MemoryMax` set to the number and `MemorySwapMax` set to zero, so memory and swap are capped together.
- When the cap ends a run, the ending is a seventh one, `memory_limit`, next to `time_limit`. Both are the boundary ending the run at a limit the caller set. The record version went from 3 to 4.
- It is decided from the scope's own result (`oom-kill`, on a scope started with a cap), not from bubblewrap's report or an exit code. The receipt holds no exit code and `cannot tell` for the signal: what bubblewrap reports then is either nothing or `128 + 9`, and neither is the program's own exit.
- A document that names a cap on a machine that cannot hold one is refused before anything is launched, in the check form and the run alike (reason `memory_cap_unavailable`, step `input_check`), with a line that says to leave the setting out to run without a cap. The machine is asked by a trial: a short scope of its own with a 64 MiB cap and no swap, whose `memory.max` and `memory.swap.max` must read back exactly as asked. The trial is started only when the document names a cap.
- The cap is on the executor's scope only. A gate and the closing freeze run without one.
- A bad value is refused as `missing_setting`, as `freeze_limit_seconds` is.
- The scope's default for what happens when the kernel kills a process for the cap is left alone: the scope stops everything in it and its result is `oom-kill`.

Choices made while building (pull request 37), separate from the answers above:

- The unit is bytes because the document names a quantity's unit and bytes is what the scope takes. 2^62 is the top because the scope reads 2^63 - 1 and above as no cap at all, shown by hand.
- The machine is asked by a trial and not by inference, because the cap is rounded to a page and a user manager without the memory controller silently ignores the property, so a successful `systemd-run` says nothing.
- A capped run whose executor went away by itself has its scope read a bounded number of times (`SETTLE_READS`, 50) until it has ended, and only then stopped. The manager marks a scope `oom-kill` a little after the kernel's kill, and a stop that arrives first replaces that with a success. Without the reads, a run killed for a very small cap read as `could_not_start` with `launch_failed`.

## Alternatives considered

- **A reason under an existing ending, not a seventh ending.** Not taken: the cap's end is neither "ended by itself" nor Shuttle failing. The cost accepted: the fixed list of endings grows and the record version goes up.
- **A fixed number.** Not taken. What a real run needs is not known yet and differs by executor, and a required field would force a guess into every document; Shuttle carries no number of its own. The maintainers prefer no fixed numeric thresholds; why is not recorded.
- **A required field, like the time limit.** Not taken, for the same reason.
- **Cap memory only and leave swap open.** Not taken. With swap open the cap only slows a run, and nothing shows it: about 45 times slower in the trial for a working set held over the cap (1.38 s against 0.03 s, cap 64M, working set 150 MB, five passes; one test on one machine). The cost accepted: a run that would have survived by swapping is ended.
- **Run anyway where the cap cannot be enforced.** Not taken: running uncapped while the document says capped is a silent failure.
- **A "cap if the machine can, otherwise run anyway" mode in one document.** Not built. A caller who wants the run on a machine that cannot cap leaves the setting out. Such a mode would let one document run on machines of both kinds, at the price of a run that may or may not be capped depending on where it runs; it is to be added when a real caller needs one document for both.
- **Sampling peak memory while the run lives.** Not built. The receipt cannot report peak memory for a run that ended normally, because the manager keeps it only for a failed scope. Sampling is left for later telemetry.
- **Other values of the scope's out-of-memory policy.** Why the default was kept over `continue` or `kill` is not recorded. In the trial, under `continue` the scope ended `success` and only the program's exit and the journal showed the kill.
- **Capping the gates and the closing freeze.** Not built. Why the cap is on the executor's scope only is not recorded.
- **Why a bad value is `missing_setting` and not a new reason.** Not recorded beyond the precedent of `freeze_limit_seconds`.

## Consequences

- A machine-wide shortage reads the same as exceeding the cap. If the machine runs out of memory during a capped run and the kernel kills a process inside the scope, the scope's result is the same `oom-kill`, so the run reads as `memory_limit`. The reason line says so. Telling them apart needs the scope's peak (readable only for a failed scope) or the cgroup's counters (gone with the scope), and Shuttle reads neither.
- A scope that ends `oom-kill` with no cap named is not `memory_limit`: it ends `ended_by_itself`.
- Files kept in memory count against the cap: files written to the box's temporary folder, or to the place or run area where they sit on memory-backed storage such as a `tmpfs` `/tmp`. A program that allocated nothing and wrote files there ended `memory_limit` in review, and `ended_by_itself` with no cap.
- A cap near or below what the box itself needs ends the run as `memory_limit`; in one review a trivial program needed about 4 MB plus a page. One machine only.
- A child killed for the cap ends the whole run as `memory_limit`, even when the program would itself have exited 0 or 3. That is the intended reading.
- Whether the settling reads close the window for every cap and machine is not shown by the code. In the runs tried, after they were added, small caps read as `memory_limit` in every run; that is observation.
- The receipt's peak memory field is `not built`. No default cap, no cap on gates or the closing freeze, and no processor or process-count limits are built.
- The real cap tests skip, with a stated reason, on a machine whose trial fails, and `SHUTTLE_REQUIRE_BOUNDARY` does not turn that skip into a failure.
- Not tested: no real Codex run has been made under a cap.
