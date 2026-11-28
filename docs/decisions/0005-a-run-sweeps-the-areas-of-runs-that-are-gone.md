# A run sweeps the run areas of runs that are gone

Status: accepted, 2026-11-27. Built as of `main` at `d89f730` (pull requests 38 and 39): each run holds a lock beside its run area, and a real run's set-up removes the areas of runs whose Shuttle is gone. Not built: see Consequences.

## Context

When Shuttle is killed hard (a `kill -9`, an out-of-memory kill), the run area it made stays in the temporary folder. Since the work on the executor's reach ([0001](0001-the-reach-is-hidden-unless-declared.md), pull request 30) the run area holds a copy of the tool's login, where before it held only a link. The copy sits in a folder only the user can read. About a hundred stale run areas from test runs sat in one machine's temporary folder when this was decided.

Before this change a run area was named `shuttle-run-area-` plus random characters, and nothing in it or its name recorded the request id, a process id or the scope's name. The area lives from set-up to tear-down, longer than the executor's scope. Shuttle's operations on the world had no list-folder, lock or process-alive operation.

## Decision

At the start of a real run, Shuttle removes the run areas of runs whose Shuttle is gone, and only those (the sweep, `GLOSSARY.md`). The reason for doing it at all: a credential should not pile up in a temporary folder; it is not an emergency, because only the user can read the folder.

Five design answers:

1. **A run's Shuttle is gone when its lock is free.** Each run creates a small file beside its area (the area's name and `.lock`), takes an exclusive lock on it before it makes the area, and holds the lock until tear-down. The kernel lets go of the lock when the process ends, a hard kill included, so a free lock tracks the one thing that matters, whether the Shuttle that made the area is alive, with no age rule or number. The file is outside the box, and a child the run starts does not inherit the lock.
2. **A gone Shuttle whose scope is still active: leave the area.** The area's name carries the run's own part of its scope names. The sweep removes an area only when its lock is free and no scope of that run is active; otherwise it leaves the area, stops nothing, and says so. The reason given is that no ending should happen automatically.
3. **What counts as Shuttle's.** Only a real folder (not a link) that matches the name pattern, is owned by the current user and has a regular lock file beside it that the user owns. A folder with no lock file is not removed. Accepted consequence: areas made before this change are not swept and are cleared by hand once.
4. **Where and when.** Only in a real run, not in the check form (which makes no area), at set-up, just before the run makes its own lock and area, and only in the temporary folder that run is about to use. The reason given: nothing runs between runs.
5. **When the sweep fails.** It never changes the run's ending and never refuses the run. It prints one line on standard error saying what was removed, what was left and why. No receipt field and no change to the records, to keep the change small.

Choices made while building (pull request 38), separate from the answers above:

- A lock file with no area beside it and a free lock is removed too, and counted separately in the line. It holds nothing, a Shuttle killed between steps leaves exactly this, and leaving it would make it litter that stays.
- The area is named `shuttle-run-area-` plus the 32 lower-case hex digits of the run's part, so areas from before the change, with an 8-character random suffix, cannot match.
- The scope question is one call per area that looked stale, for every unit whose name carries the run's part (the executor's scope, a gate's, the closing freeze's). Any state but `inactive` and `failed` counts as active, the same words the stop step treats as empty. A failure to ask leaves the area.
- The sweep runs after the driver's requests are accepted, so a refused set-up sweeps nothing and makes nothing. A line is printed only when something looked stale, so no existing run's standard error changes.
- Pull request 39 landed first: every real run the test harness starts gets a temporary folder of the test's own unless the test names one. Without it, most real-run tests would have listed and removed areas in the machine's real temporary folder, and the first test after a killed suite would have printed the sweep line.

## Alternatives considered

- **Accept the leak and say so in the README.** Not taken. Why that was not enough beyond the reason above is not recorded.
- **"Is the scope active" as the test for a gone run.** Not taken: the area outlives the executor's scope, so a run in its closing freeze would be called gone.
- **An age threshold.** Not taken: a number to tune, and wrong for a long run.
- **A process id written in a file.** Not taken: ids are reused.
- **Stopping a leftover scope.** Not taken: it would be an automatic ending. Why stopping counts as one beyond that is not recorded.
- **Sweeping folders that have no lock file.** Not taken: a folder that merely looks like a run area and was not made by Shuttle is left alone. No alternative to this was named.
- **Sweeping in the check form.** Why it is excluded is not recorded; the check form makes no area.
- **Why the sweep sits after the driver's requests are accepted.** Not recorded beyond what is above.
- **A count of removed areas in the record.** Not built, for now.
- **An always-on sweep between runs.** Not taken (answer 4).
- **A default temporary folder for tests, filed for later.** The first plan was to say the consequence in the pull request and file the default for later. Not taken: a test must not touch the real temporary folder.

## Consequences

- Areas with no lock file are not swept. Areas made before this change have none, and are cleared by hand.
- A hard-killed run's area stays until a later run starts in the same temporary folder. Nothing sweeps between runs or in another temporary folder. An area whose scope is still active stays until a run starts after the scope has ended.
- The sweep reads a lock file's owner and an area's kind and owner before it takes the lock, and not again. `remove_tree` refuses a link at the area's name and removes a link inside the area without following it. A link put at the area's own name after its check is not removed through, but its permission step can still widen the owner's mode on what it leads to.
- A stop signal that arrives during the sweep is acted on after the sweep step ends. In one observation with 40 planted areas, all 40 were removed and then the run ended `could_not_start` with the stop. The sweep's length depends on what was left behind.
- A sweep that meets a live run's lock file in the moment between its being made and locked reads it as a lock file with no area, and can print a line that is untrue of it. Five sweeps in a row meeting that gap fail the run's set-up (nothing is left on disk). Neither was seen in 600 runs, and nothing proves they cannot happen.
- A mount placed inside a stale area would be walked into by `remove_tree`. Shuttle's own box mounts only in its private namespace. A temporary folder on a filesystem without `flock` would fail every run at set-up; the README does not say so. Both are filed and not fixed, because no real run reaches them today.
- The sweep was not run against a real temporary folder holding old-style areas in review; every run of the review used a temporary folder of its own. That old-style areas were left untouched is shown only by their count before and after the checks.
- The wording of the printed line ("1 stale run area of runs that are gone" mixes singular and plural, and it does not name the folder it looked in) is filed and not changed.
