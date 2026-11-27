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

**Record**:
A file Shuttle writes about one run: a request record or an outcome record.
