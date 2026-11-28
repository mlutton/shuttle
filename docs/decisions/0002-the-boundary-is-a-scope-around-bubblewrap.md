# The boundary is a systemd user scope around bubblewrap

Status: accepted, 2026-11-25 (the choice of mechanism); confirmed 2026-11-27 that the scope stays. Built as of `main` at `14f9cd3`, with the stop and status forms not built and no real Codex run made in the boundary as it now is.

## Context

A caller needs a run to start one executor and to know, from the run itself, that everything the executor started has ended. A stop by process group misses what is started detached (a new session, a user service, a timer) or through a daemon such as a terminal-multiplexer server, so the design relied on a control group, or something like it, that is stopped and then seen empty, to confirm that a run "stops everything it started". That reliance was not tested for mechanisms beyond those in the trial below. What the box lets the executor see and write is a separate decision: [0001](0001-the-reach-is-hidden-unless-declared.md).

## Decision

Shuttle starts the executor in a systemd user scope and, inside it, runs bubblewrap with its own process space that dies with its parent. The scope holds the time limit (its maximum runtime) and is stopped by name and seen empty; the box holds the reach. Together they are the boundary (`GLOSSARY.md`). The boundary belongs to execution, not to each driver. The time limit has one owner, the scope: the command observes why the scope ended and names the ending; it has no second deadline.

Built as of `14f9cd3`: the executor is launched with `systemd-run --user --scope` with `RuntimeMaxSec` and `TimeoutStopSec=3s` around `bwrap --unshare-pid --die-with-parent`; the run stops the scope by name, sees it empty and reads from it why it ended, and a reason it cannot read is "execution failed".

## Alternatives considered

- **A plain process group.** Not taken. In a trial on 2026-11-24 a `setsid` double fork, a `systemd-run` started from inside, a private terminal-multiplexer server started inside, and a scheduled timer all survived the stop unseen.
- **A scope alone.** Not taken. In the same trial the `systemd-run` and timer escapes survived the stop and the scope's emptiness check did not notice them, and killing the parent of `systemd-run --scope` left the executor running with the scope active.
- **A transient systemd service instead of a scope.** The trial measured it: the same survivors as the scope. Whether it was weighed against the scope beyond that table was not recorded.
- **Bubblewrap alone.** Not taken, because the scope tracks everything a run starts, ends all of it and holds the time limit. In the trial, bubblewrap alone left no survivor except through the multiplexer socket, and its parent-death test left none. It remains the fallback if Shuttle must ever run without a user systemd.
- **Each driver owning its whole launch.** Considered and rejected: each driver would re-implement stopping and confirming.
- **A container runtime (docker, podman) and other isolation tools (firejail, Landlock).** Whether any of these was weighed is not recorded. The trial did not probe docker or podman, and the other tools were not reached.

## Evidence and its limits

All of it is single runs on one machine, and the trial's causes are guesses.

- In bubblewrap and in a scope around bubblewrap, the `systemd-run` and timer escapes could not start, because the user bus was unreachable. The trial calls this a side effect of an error, not a designed rule.
- A process started through a multiplexer socket outside the boundary survived in every mechanism except one that also hid `/tmp` and the user's runtime folder. The two were hidden together, never separately, so which mattered is not known.
- A prototype of the Codex driver, run once in the scope-around-bubblewrap boundary, tested parent death with a plain `sleep`, not Codex: killing the parent left nothing alive and the scope inactive; timing and process counts were not saved. In the same prototype a write outside the place was refused with Codex, only with Codex's temporary-folder exclusion set. That prototype bound the whole filesystem writable, which the boundary no longer does.
- No source shows the parent-death test of the combined boundary with the real Codex.

## Consequences

- It needs a machine with a user systemd, `systemd-run`, `systemctl`, `bwrap` and user namespaces. Where bubblewrap never started the executor, the run ends "could not start" with reason `launch_failed`. The tests that run a real script in the boundary skip without it, and the hosted check sets `SHUTTLE_REQUIRE_BOUNDARY` so a missing boundary fails there.
- A process started through a socket outside the boundary can survive the stop. The user's systemd and D-Bus sockets are hidden in the box as built, which closes the route found; whether it closes every such route was not tested.
- The scope's emptiness check cannot see a survivor outside the scope, and no process boundary covers network side effects.
- The grace between asking and killing does not reach the executor: on a stop bubblewrap exits at once and takes its namespace with it. Left as it is until a real Codex run shows the tool needs time to clean up.
- The receipt's `signal` reads "cannot tell" for every run inside the boundary, because bubblewrap reports "killed by signal n" and "exited 128+n" identically.
- The scope tool expands `$` in the command it is given, so Shuttle doubles every `$`; the option that turns this off needs systemd 254.
- The stop and status forms are not built.
- It is not a security sandbox.
