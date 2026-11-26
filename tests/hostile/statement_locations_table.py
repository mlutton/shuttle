"""What an executor can leave at the statement location that is not a regular file.

A row is a dict:
- label: what is left there.
- leaves: a line of Python the executor script runs to leave it. It sees `os`, `location` (the
  statement location) and `given` (a file that holds a secret line, which is not a statement).

Every row must end the run, write the outcome record, copy nothing beside the records and read
`wrong_shape`. Opening a pipe nobody writes waits for ever, and `/dev/zero` never ends, so a
test that runs these has to fail by assertion, not hang. The test is
tests/boundary/test_statement.py.
"""

LOCATIONS = (
    {"label": "a link to a file", "leaves": "os.symlink(given, location)"},
    {"label": "a link to a folder", "leaves": "os.symlink(os.path.dirname(given), location)"},
    {"label": "a link to a missing name", "leaves": "os.symlink(given + '.absent', location)"},
    {"label": "a link to /dev/zero", "leaves": "os.symlink('/dev/zero', location)"},
    {
        "label": "a link to a named pipe",
        "leaves": "os.mkfifo(given + '.pipe'); os.symlink(given + '.pipe', location)",
    },
    {"label": "a named pipe", "leaves": "os.mkfifo(location)"},
    {"label": "a folder", "leaves": "os.mkdir(location)"},
)
