Tests of the boundary go here: the real one, a systemd user scope around bubblewrap, that contains the executor, stops everything it started and is seen empty.

- `test_end_to_end.py`: the one end-to-end test. One request through every piece that is real so far, from the input document to the outcome record. Later tickets extend it; they do not add their own.
- `test_arguments.py`: arguments (the executor's and a gate's) and a records location with `$`, `%` and a backslash arrive and are protected unchanged.
- `test_boundary.py`: what is left after a child outlives its script and after the command is killed hard, what a script cannot write, a boundary whose tools fail (the run could not start), and a script that kills itself.

They skip, with the reason, on a machine without the boundary (`tests/rehearsal/the_boundary.py`), and fail instead where `SHUTTLE_REQUIRE_BOUNDARY` is set, which the hosted runner sets. No test here sleeps or reads a clock: a script says it is up through a pipe, and the time limit is the boundary's.
