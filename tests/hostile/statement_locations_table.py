"""What an executor can leave at its statement path in the run area that is not a regular file.

A row is a dict:
- label: what is left there.
- leaves: a line of Python the executor script runs to leave it. It sees `os`, `location` (the
  statement's path in the run area) and `given` (a file that holds a secret line, which is not a statement).

Every row must end the run, write the outcome record, copy nothing
beside the records and read `wrong_shape`. Opening a pipe nobody writes waits for ever, and `/dev/zero` never ends, so a
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

PARENTS = (
    {
        "label": "the parent folder swapped for a link to another folder",
        "swaps": "os.rename(parent, parent + '.x'); os.symlink(victim + '/inner', parent)",
    },
    {
        "label": "the parent's parent swapped for a link to another folder",
        "swaps": "os.rename(grandparent, grandparent + '.x'); os.symlink(victim, grandparent)",
    },
    {
        "label": "the parent folder swapped for a link to a name that is not there",
        "swaps": "os.rename(parent, parent + '.x'); os.symlink(victim + '/absent', parent)",
    },
)
"""What an executor can do to the folders above the statement location while it runs.

A row is a dict:
- label: what is done.
- swaps: a line of Python the executor script runs to do it. It sees `os`, `parent` (the folder
  the location is in), `grandparent` (the folder that holds it) and `victim` (a folder with a
  folder `inner` in it, that the location's folders must never lead to).

Every row must end the run with the statement kept and judged as the executor wrote it, and
nothing written below `victim`: the copy to the location goes into the folder the parent was when
the run began, or nowhere. The test is tests/boundary/test_statement.py.
"""
