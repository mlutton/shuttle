# Shuttle

Shuttle runs one program, once, inside a boundary, and writes a truthful record of how the run ended.

A caller hands Shuttle one input document. Shuttle checks it, starts one executor (an AI coding agent or a plain command), stops everything the executor started, and writes one outcome record. The caller reads that record and nothing else.

## Status

Early build. It is not usable yet, and it may not be for a while. The first increment is a skeleton: `python3 -m shuttle run <input document>` runs one plain command from start to finish and writes a request record and an outcome record. Only the run form exists. The boundary, the fingerprints of the place, delivery and the other three forms are stand-ins or not built; a receipt field fed by a stand-in says "cannot tell". The code and its tests are published as they are written, so the tests are the best account of what works today.

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

## Tests

```
python3 -m unittest discover -s tests
```

The tests run the real command as a child process against a temporary records folder, and test each decision as a function over plain data. The `tests` workflow runs them on every pull request.

## Contributing

Issues and pull requests are open to collaborators only for now.
