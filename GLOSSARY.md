# Shuttle

The words for what a Shuttle run starts, what it can reach and what it leaves behind.

## Language

### Isolation

**Reach**:
What the executor can see and write. Every path in it is writable, read-only or hidden.
_Avoid_: isolation (the goal, not the thing listed, tested and printed), access

**Writable**:
A path the executor can read and change.

**Read-only**:
A path the executor can read and cannot change.

**Hidden**:
A path the executor cannot see.

**Scope**:
The group that holds everything a run starts; it owns the run's lifetime and its limits. A gate and the closing freeze run in a scope with no box.
_Avoid_: boundary (for the scope alone), sandbox

**Box**:
Where the reach is applied.
_Avoid_: boundary (for the box alone), sandbox

**Boundary**:
The scope and the box together, around the executor.
_Avoid_: sandbox, using "scope" or "box" for the two together

### What a run is made of

**Executor**:
The one thing a run starts: an AI coding agent or a plain command.

**Driver**:
What Shuttle uses to start one kind of executor and to read what that executor left behind.

**Place**:
The caller's linked working copy of its repository, made for one run; it is the executor's working directory.

**Run area**:
A private folder made for one run, holding what the executor needs that is not the place, and removed when the run ends.

**Record**:
A file Shuttle writes about one run: the request record when the run is asked for, the outcome record when it ends.
