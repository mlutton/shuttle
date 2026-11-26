"""The real set of operations, whole, and the process's own edge (arguments, streams, exit)."""

import contextlib
import os
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from shuttle.core.shapes import Operations
from shuttle.world.boundary import BOUNDARY
from shuttle.world.clock import CLOCK
from shuttle.world.environment import ENVIRONMENT
from shuttle.world.files import FILES
from shuttle.world.identity import IDENTITY
from shuttle.world.processes import PROCESSES
from shuttle.world.signals import SIGNALS

OPERATIONS = Operations(
    files=FILES,
    processes=PROCESSES,
    boundary=BOUNDARY,
    clock=CLOCK,
    signals=SIGNALS,
    environment=ENVIRONMENT,
    identity=IDENTITY,
)


def start(main: Callable[[Sequence[str], TextIO, TextIO, Operations], int]) -> None:
    """Hand the process's arguments and standard streams, and the real operations, to `main`;
    end the process with the code it returns."""
    code = main(sys.argv[1:], sys.stdout, sys.stderr, OPERATIONS)
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        # The reader of standard output went away. The interpreter flushes again as it exits and
        # would end with code 120; point standard output at nothing so the code stays the run's.
        with contextlib.suppress(OSError, ValueError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(code)
