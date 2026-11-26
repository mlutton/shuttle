"""The kinds a document may name, read from the two data files shipped beside the code."""

from shuttle.core import refusals
from shuttle.core.shapes import Operations

# The folder `shuttle/data/`, found from where this file sits (shuttle/shell/kinds.py).
DATA_FOLDER = __file__.rpartition("/")[0].rpartition("/")[0] + "/data"
WITH_STATEMENT = DATA_FOLDER + "/kinds_with_statement.txt"
WITHOUT_STATEMENT = DATA_FOLDER + "/kinds_without_statement.txt"


def read_kinds(world: Operations) -> dict[str, bool]:
    """Kind name to whether a statement is expected. Raises OSError when a file cannot be read."""
    return refusals.parse_kinds(
        world.files.read(WITH_STATEMENT).decode("utf-8"),
        world.files.read(WITHOUT_STATEMENT).decode("utf-8"),
    )
