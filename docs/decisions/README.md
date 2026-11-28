# Decision records

A record here says why something in Shuttle is the way it is: the context, what was decided, what else was considered and why it was not taken, and what the decision costs. Each is a short rendering of the maintainers' decision notes.

The maintainers' notes are the source for the reasons. A correction is a pull request here; the maintainers carry an accepted correction back to the notes, and the record is rendered again from them. A record states its own status: what of it is built as of a named commit of `main`. That part is checked against the repository and goes stale as the code changes.

Where the notes say a reason was not recorded, the record says so; it does not supply one.

All five records were last rendered on 2026-11-28, against `main` at `d89f730`.

- [0001](0001-the-reach-is-hidden-unless-declared.md): the executor's reach is hidden unless declared.
- [0002](0002-the-boundary-is-a-scope-around-bubblewrap.md): the boundary is a systemd user scope around bubblewrap.
- [0003](0003-one-run-is-one-session-and-a-fix-is-a-new-run.md): one run is one session, and a fix is a new run.
- [0004](0004-a-run-can-carry-a-memory-cap.md): a run can carry a memory cap, held by the scope.
- [0005](0005-a-run-sweeps-the-areas-of-runs-that-are-gone.md): a run sweeps the run areas of runs that are gone.
