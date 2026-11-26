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

One script decides whether a change is sound: lint (ruff, including a limit of three nested blocks and a ban on a core module importing the shell or a library that reaches the world), format check (ruff), strict types (mypy, over `shuttle/`) and the tests (under a 20 second budget). The pre-push hook and the hosted `tests (unittest)` job both run it and nothing else.

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

It prints one line per stage and a last line, `check: passed` or `check: failed: <stage>`. Exit code 0 means passed, 1 means a stage failed, 2 means the check could not run (a tool is missing; the last line names it and the install command). The script uses `.venv/bin/python` when it exists, else `python3`; set `PYTHON` to use another interpreter. Nothing is retried.

Switch on the pre-push hook, once per clone:

```
git config core.hooksPath .githooks
```

A push is then refused unless `./checks/all.sh` passes on each commit being pushed. The hook checks out that commit into a temporary folder and runs the script there, so uncommitted changes in your folder neither pass nor fail a push.

## Tests

```
python3 -m unittest discover -s tests
```

The tests are sorted by seam, all run by that one command:

- `tests/by_value/`: decisions as functions over plain data, and the rule test. Every module in `shuttle/` is listed as core or shell in `pyproject.toml` (`[tool.shuttle.modules]`); a core module may import only other core modules and a short allow-list of standard library modules, may not mention built-ins such as `open` and `print`, and no module may import a third-party package.
- `tests/command/`: the real command, the check script and the hook, run as child processes or against a temporary folder.
- `tests/boundary/`: tests of the boundary; none yet.

The `tests (unittest)` workflow runs the check on every pull request.

## Contributing

Issues and pull requests are open to collaborators only for now.
