"""The statement's schema, read from the data file shipped beside the kinds files."""

import json
from typing import Any

from shuttle.core.shapes import Operations
from shuttle.shell import kinds

SCHEMA_FILE = kinds.DATA_FOLDER + "/statement_schema.json"


def read_schema(world: Operations) -> dict[str, Any]:
    """The schema as data. Raises OSError when the file cannot be read, ValueError when it is
    not JSON."""
    schema: dict[str, Any] = json.loads(world.files.read(SCHEMA_FILE).decode("utf-8"))
    return schema
