# Coding standards

Read in full at review; a builder reads the rules its definition names. A machine enforces lint, format, types, nesting depth, the import rules between the package's folders, ignore comments for the import ban and the suite's time budget; those are not repeated here. The rules below are judgement: the reviewer answers once each rule under the headings other than "The review" (those are about the change), follows the rules under the heading "The review" (those are about the review itself), and cites a rule by its bold name.

## Design
- **Functional core.** Every decision is a pure function: arguments in, a value out. Files, the clock, the environment and processes belong to the shell.
- **Humble object.** The shell gathers facts, hands them to the core, acts on the answer. A decision found in the shell, or in a script under `checks/`, moves to a tested function.
- **Fail closed.** A guard that cannot establish the fact it guards on refuses, in one line that names what was not done, what could not be established, and what would fix it. A helper ends with its documented last line on every path, its own crash included.
- **One meaning per exit code.** Listed in the script's header.
- **Names are data.** A file name is never split, quoted by a tool, or pasted raw into rendered text; the names table in `tests/hostile/` holds the awkward names.

## Tests
- **Behaviour only.** The core is tested by value; the shell through the real command, failure paths included. A test asserts what a caller can see.
- **Waits are isolated.** Test everything that needs no wait fully and by value; one test covers the full flow. No test keeps time.
- **Tests bound their own resources.** A test that hands the command an input without an end (a device, a pipe, a file of any size) runs under the harness's file-size and address-space limits (`tests/rehearsal/real_run.py`), so a regression is a failed assertion in seconds, never a machine out of memory or disk; a time limit is not a resource limit. A reviewer checks that such a test starts the command through the harness, and that any limit it raises says why.
- **Red first.** Each new test of changed behaviour fails on the base commit; the builder says how that was shown. A test that pins unchanged behaviour says so in its name.

## Words
- **Docs with the change.** The README, a script's header and these documents change in the same commit as the behaviour they describe. A comment that restates code or will go stale is left out.
- **Printed numbers.** Every number in a pull request was printed by a command, and the text says which and where it ran.

## The review
- **Hunt the wrong answer.** The reviewer names the inputs and states tried, including those that held.
- **Findings are typed.** Each finding is a defect (a concrete input or state and the wrong result), a new use case, or a note. For each, the reviewer says whether a machine could have caught it and whether an agent could reach it by accident with the repository as it stands.
- **Rounds.** Round one: any defect holds the merge. From round two: only a critical defect holds. A finding is critical only if (a) its result is a wrong verdict, a lost run, data written where it must not be, a false statement in a report, a false statement in a document an agent reads, an instruction that, followed literally, produces a wrong action, or a guard that passes what it must refuse, and (b) an agent could reach it by accident with the repository as it stands. A route that needs a deliberate odd set-up or a configuration change is a note. The same class of defect twice in one change sends that part back to design, starting from a table of the cases.
- **One verdict.** "ready to merge" or "not ready: <reason>", for the exact commit read. The reviewer does not leave the call to the reader.
