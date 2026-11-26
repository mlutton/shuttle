"""The environment: the real set."""

import os

from shuttle.core.shapes import EnvironmentOperations


def read_variable(name: str) -> str | None:
    return os.environ.get(name)


ENVIRONMENT = EnvironmentOperations(read_variable=read_variable)
