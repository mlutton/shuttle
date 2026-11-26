# Shuttle

Shuttle runs one program, once, inside a boundary, and writes a truthful record of how the run ended.

A caller hands Shuttle one input document. Shuttle checks it, starts one executor (an AI coding agent or a plain command), stops everything the executor started, and writes one outcome record. The caller reads that record and nothing else.

## Status

Early build. It is not usable yet, and it may not be for a while. The first increment is a skeleton: `python3 -m shuttle run <input document>` runs one plain command from start to finish (ending it when its time limit runs out or the command is interrupted) and writes a request record and an outcome record. Only the run form exists. The boundary (the command runs as a plain child process, and confirming that everything it started is stopped is a stand-in), the fingerprints of the place, delivery and the other three forms are stand-ins or not built; a receipt field fed by a stand-in says "cannot tell". The code and its tests are published as they are written, so the tests are the best account of what works today.

## What it will promise

- Every run ends with exactly one of six endings: ended by itself, time limit, stopped from outside, asked for a human, could not start, execution failed.
- What Shuttle observed is kept apart from what the executor says about its own work.
- Once the ending is known, nothing prevents a record carrying that ending.
- A request record is written before anything starts and an outcome record when the run ends, so the two together are the trace of the run.
- Each vendor's tool sits behind an executor driver, so a run looks the same from outside whichever tool did the work.

## Shape

- Outside: a command-line tool with four forms (run, check, stop, status).
- Inside: functions over plain data. Each decision is a pure function; the code that touches files and processes is a thin shell around them.
- Python, standard library only.

## Checking a change

One script decides whether a change is sound: lint (ruff, including a limit of three nested blocks and a ban on anything under `shuttle/core/` importing `shuttle/shell/` or a library that reaches the world), format check (ruff), strict types (mypy, over `shuttle/`) and the tests (under a 20 second budget). The pre-push hook and the hosted `tests (unittest)` job both run it and nothing else.

Shuttle needs Python 3.12 or newer: 3.12 is the lowest version on which the whole suite passes (one command test fails on 3.11), and it is the version the hosted job uses.

Install the development tools once (they are not runtime dependencies; the package itself uses only the standard library), preferably in a virtual environment inside the clone:

```
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run the check:

```
./checks/all.sh
```

It prints one line per stage and a last line, `check: passed` or `check: failed: <stage>`. Exit code 0 means passed, 1 means a stage failed, 2 means the check could not run (a tool is missing; the last line names it and the install command), 3 means the argument was not recognised. The script uses `.venv/bin/python` when it exists, else `python3`; set `PYTHON` to use another interpreter. Nothing is retried.

`./checks/all.sh --fix` applies what ruff can change mechanically (safe lint fixes and the formatter, never an ignore comment or a configuration edit) and needs ruff only. It lists each file it changed (`changed: <path>`) and each file ruff could not parse or write (`failed: <path>`), then ends `fix: changed N files; now run ./checks/all.sh`, `fix: nothing to change` or `fix: failed; ...` (exit 1). It runs no types or tests; run the check afterwards. File names in this output and in the guard listing are shown escaped (a newline, a backslash, a control or direction character, or a byte that is not valid UTF-8 appears as an escape such as `\n` or `\xff`), one per line.

Switch on the pre-push hook, once per clone:

```
git config core.hooksPath .githooks
```

A push is then refused unless `./checks/all.sh` passes on each commit being pushed. The hook checks out that commit into a temporary folder and runs the script there, so uncommitted changes in your folder neither pass nor fail a push. From a linked worktree the hook uses the worktree's own `.venv` if it has one, else the main working tree's.

## Tests

```
python3 -m unittest discover -s tests
```

The tests are sorted by seam, all run by that one command:

- `tests/by_value/`: decisions as functions over plain data, and the rule test. Where a module sits in `shuttle/` is its classification, and nothing is registered anywhere: `shuttle/core/` (sub-folders included, executor drivers in `shuttle/core/drivers/`) decides and touches nothing, `shuttle/shell/` reaches the world, and only `__init__.py` and `__main__.py` may sit at the package root, each kept thin (the version string; one hand-over to the shell's command line). A module under `shuttle/core/` may import only other modules under `shuttle/core/` and a short allow-list of standard library modules, and may not mention built-ins such as `open` and `print`; a module anywhere else in the package fails the test, and no module may import a third-party package.
- `tests/command/`: the real command, the check script and the hook, run as child processes or against a temporary folder.
- `tests/boundary/`: tests of the boundary; none yet.

The `tests (unittest)` workflow runs the check on every pull request. Its `base check (unittest)` job also runs the base branch's copy of `checks/all.sh` against the pull request's files, so a pull request cannot pass by weakening the script, and lists in the job summary any guard files (changed, added or deleted; a moved file shows as deleted from its old path) the pull request changes (`checks/`, `.githooks/`, `.github/`, `tests/hostile/`, `pyproject.toml`, `requirements-dev.txt`, and the tests that are rules or loop an attack list: `tests/by_value/test_rules.py`, `test_check_helpers.py` (it pins the guard list), `test_name_functions.py`, `test_names_table.py`, `tests/command/test_hostile_tables.py`, `test_fix_mode.py`). It does not cover the workflow file or the lint configuration, which still come from the pull request; the summary is how a reviewer sees them.

## Hostile-case tables

The cases reviewers used to rebuild by hand for every pull request are kept as data in `tests/hostile/`, three tables with no logic in them: `names_table.py` (file names that break careless code: a space, a newline, a backtick, bytes that are not UTF-8, look-alikes of the guard folders; each row says whether a real filesystem can hold it), `imports_table.py` (the forms by which a core module might reach the shell, the entry file, the world or a third-party package, and the forms that must stay allowed; each row says whether the rule test, the linter or both refuse it) and `suppressions_table.py` (every lint-ignore spelling tried in review, whether the pinned ruff honours it, and whether the rule test must refuse it). A row says what it attacks; a row that exposed a function's bug and could not be fixed there is marked as a known gap with the reason, and its test fails if the gap closes.

- The import table drives `check_module` in `tests/by_value/test_rules.py` and, in one real ruff run, checks the "which guard" column against the real linter. The suppression table is checked against the real ruff in one run, so an upgrade that makes ruff honour a spelling the rule test lets through fails a test instead of opening a hole.
- A function in `checks/**/*.py` (every file at any depth, every definition at any nesting, `async` and methods included) that takes file names must be run against the whole names table. It is recognised by a parameter whose name contains `path`, `file`, `name`, `folder`, `root`, `link` or `source` (or has the word `dir` in it), or whose annotation mentions `Path`; the rule is `tests/by_value/test_name_functions.py`, and it cannot see a name carried in a parameter called something else. Add a test to `tests/by_value/test_names_table.py` that loops the table and states the function's invariant in its name, then register the function in `tests/hostile/registry.py`; the registered test must refer to the table. An unregistered function fails the rule test, naming the function and where to add it. A function that does not carry file names can be exempted there, with a reason (and the exemption fails if no such parameter is there).
- The tables are guard files: `tests/hostile/` and the tests that loop it are in the guard listing, and the listing adds a section that names each row (by table and label) that was at the base and is not at the head, each row that changed, and every known-gap mark, with its reason, on every run. A known gap needs a registered function, its name in the reason and a reason of a sentence.
- The tables cover names, import forms and lint-ignore spellings. They do not cover tree shapes (symbolic links, `.pyw` files, folder names such as `__pycache__`, `.pyi` files); those keep their hand-written tests.
- To add a case, add a row. The tests that loop a table need no change.

## The per-run report

```
./checks/report.sh
```

Prints, as Markdown, what a run of the suite looks like before a reviewer looks: tests run and skipped (with each skip's reason), total time, the eight slowest tests, time per test folder, peak memory, and for every Python file under `shuttle/` and `checks/` the statements, the statements never run and their line ranges. It is generated by that run, never checked in, and nothing fails on a number in it: it makes a lack of tests visible, it does not judge it. The report names the commit and the command it came from; on a hosted pull request run that is the head commit of the pull request, with the base it was merged with, not GitHub's merge commit. Statement counts differ between Python versions (the report prints its version), so compare a local and a hosted report by file, not number for number. The hosted job log carries one line with the test count and total time.

- It runs the whole suite once under coverage.py (a pinned development tool), so it takes longer than `./checks/all.sh`, and its times and memory include coverage's overhead. `./checks/all.sh` never runs coverage. Child processes the tests start (the real `python -m shuttle`) are counted, through coverage's `patch = subprocess` setting in `pyproject.toml`; children a test starts with an environment of its own (an explicit `env=`) are not measured, so the fix-mode, base-check and hook tests add nothing; and code that only runs from copies of the scripts in temporary trees is not counted against the originals (the report names the files under the table). Every Python file under `shuttle/` and `checks/` has a row, found by walking the folders; one coverage has no data for shows all its statements as never run.
- Peak memory is the largest resident size any one process of the run reached (from `resource.getrusage`), not a total.
- A line, or the block it opens, that is left untested on purpose ends with `# not tested: <reason>`. The report lists each with its file, line and reason; a marker with an empty reason fails the rule test, and so does the marker text inside a string or docstring (coverage would exclude that line without listing it; the report also shows a visible line if the two ever disagree). Lines without a marker are simply reported as never run.
- The hosted `tests (unittest)` job runs it after the check (a second run of the suite, which never changes whether the job passes), appends it to the job summary and keeps the same Markdown as the build artifact `report`. The `base check (unittest)` job keeps its guard file listing as the artifact `guard-files`. Download either with `gh run download <run id> -n report` (or `-n guard-files`).

## Contributing

Issues and pull requests are open to collaborators only for now.
