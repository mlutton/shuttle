# Shuttle

The words for what a Shuttle run starts, what it can reach and what it leaves behind.

## Language

### Reach and boundary

**Reach**:
What the executor can see and write. Any path in it is writable (the executor can read and change it), read-only (it can read and not change it) or hidden (it cannot see it).
_Avoid_: isolation (it names the goal; reach names the thing listed, tested and printed)

**Scope**:
The group that holds everything a run starts; it owns the run's lifetime and its limits. A gate and the closing freeze run in a scope with no box.
_Avoid_: boundary or box, for the scope alone

**Box**:
Where the reach is applied.
_Avoid_: boundary or scope, for the box alone

**Boundary**:
The scope and the box together, around the executor.
_Avoid_: scope or box, for the two together

### What a run is made of

**Executor**:
The program a run exists to run: an AI coding agent or a plain command.

**Gate**:
A command that must answer yes before the executor starts.

**Closing freeze**:
A fixed snapshot of the place's files, taken once the executor has ended.

**Driver**:
What Shuttle uses to start one kind of executor, set up what it needs and read what it left behind.

**Place**:
The caller's linked working copy of its repository, made for one run; it is the executor's working directory.

**Run area**:
A private folder made for one run, holding what the executor needs that is not the place.

**Lock**:
The file beside a run's run area (the area's name and `.lock`) and the exclusive hold its Shuttle keeps on it for the whole run. The kernel lets go of the hold when the process ends, however it ends, so a free lock is how a later run knows the run's Shuttle is gone.
_Avoid_: lock file, for the hold

**Sweep**:
What a real run does just before it makes its own run area: it removes the run areas of runs whose Shuttle is gone (their lock is free and no scope of the run is active), with their lock files, and a lock file with no area beside it and a free lock; nothing else. The check form does not sweep.
_Avoid_: clean-up or tidy (the tear-down removes a run's own area)

**Record**:
A file Shuttle writes about one run: a request record or an outcome record.

**Kept file**:
A file Shuttle copies out of the run area into the records folder, whole and unedited, before the tear-down removes the area, named `<request id>.<what>.kept`: the executor's statement, its standard output, its standard error and the final message its tool left. The receipt says where each was kept and its hash. Nothing is removed from a kept file, so it can hold anything the executor printed.
_Avoid_: log or artifact
