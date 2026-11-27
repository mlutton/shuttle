"""What every executor driver offers, so the shell and the document check never name one.

A driver is a module (no base class) with these functions and constants; the table in
`shuttle.core.drivers.table` maps a driver's name to its module, and that table is the only place
that names one. Every function is pure. A driver never names an ending: it says what it saw, and
the decisions read that.
"""

from collections.abc import Mapping
from typing import Protocol

from shuttle.core.shapes import (
    DriverFacts,
    LaunchContext,
    LaunchSpec,
    Observed,
    OutputFiles,
    SavedOutput,
    Settings,
    SetupRequest,
    StatementArrival,
)


class Driver(Protocol):
    NAME: str
    VERSION: str
    # The caller's variables the driver looks at (its tool's home, say); the shell reads exactly
    # these and hands them to `login_path` and `setup_requests`.
    READS: tuple[str, ...]
    STATEMENT: StatementArrival

    def settings_refusal(self, settings: Settings) -> tuple[str, str] | None:
        """(reason code, one line) when the settings are not this driver's, else None."""
        ...

    def program(self, settings: Settings) -> str:
        """The program the shell looks for, to fill `DriverFacts.tool_found`."""
        ...

    def login_path(self, environment: Mapping[str, str]) -> str | None:
        """The name of the login file, or None when the tool has none or it cannot be placed.
        The shell asks only whether it is there."""
        ...

    def check(self, settings: Settings, facts: DriverFacts) -> tuple[str, str] | None:
        """(reason code, one line) when the run is refused, else None. It never opens a login."""
        ...

    def setup_requests(
        self, settings: Settings, environment: Mapping[str, str]
    ) -> list[SetupRequest]:
        """What the tool asks of the run area (shuttle.core.run_area)."""
        ...

    def launch(self, settings: Settings, context: LaunchContext) -> LaunchSpec:
        """The one command to start. It exits when done; the instruction reaches it on standard
        input, never on the command line."""
        ...

    def output_files(self, run_area: str) -> OutputFiles:
        """Where the tool leaves what `observe` reads, inside the run area."""
        ...

    def observe(self, settings: Settings, saved: SavedOutput) -> Observed:
        """The driver group of the receipt, and the statement text, from what the tool left."""
        ...

    def declare(self) -> dict[str, list[str]]:
        """What the tool loads by itself, what it runs by itself, and what it needs set up."""
        ...
