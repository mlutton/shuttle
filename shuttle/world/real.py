"""The real set of operations, whole, and the process's own edge (arguments, streams, exit)."""

import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from shuttle.core.shapes import Operations
from shuttle.world.clock import CLOCK
from shuttle.world.environment import ENVIRONMENT
from shuttle.world.files import FILES
from shuttle.world.identity import IDENTITY
from shuttle.world.processes import PROCESSES
from shuttle.world.signals import SIGNALS

OPERATIONS = Operations(
    files=FILES,
    processes=PROCESSES,
    clock=CLOCK,
    signals=SIGNALS,
    environment=ENVIRONMENT,
    identity=IDENTITY,
)


def start(main: Callable[[Sequence[str], TextIO, TextIO, Operations], int]) -> None:
    """Hand the process's arguments and standard streams, and the real operations, to `main`;
    end the process with the code it returns."""
    sys.exit(main(sys.argv[1:], sys.stdout, sys.stderr, OPERATIONS))
