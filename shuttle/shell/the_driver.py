"""The executor driver a document names, and what the shell gathers for it.

The only module of the shell that reaches the table of drivers: every step asks here, so no step
names a driver. What is gathered is looked at, never opened: whether the program is found, and
whether the login's name is there.
"""

from collections.abc import Mapping
from typing import Any

from shuttle.core import decisions
from shuttle.core.drivers import table
from shuttle.core.drivers.interface import Driver
from shuttle.core.shapes import DriverFacts, LaunchContext, Operations, SavedOutput


def of(raw: Mapping[str, Any]) -> Driver:
    """The driver the checked document names."""
    return table.DRIVERS[raw["executor"]["name"]]


def caller_variables(world: Operations, driver: Driver) -> dict[str, str]:
    """The caller's variables the driver reads, those that are set."""
    found: dict[str, str] = {}
    for name in driver.READS:
        value = world.environment.read_variable(name)
        if value is not None:
            found[name] = value
    return found


def facts(world: Operations, raw: Mapping[str, Any]) -> DriverFacts:
    driver = of(raw)
    login = driver.login_path(caller_variables(world, driver))
    network, changes = decisions.standard_settings(raw)
    return {
        "tool_found": world.processes.find_program(driver.program(raw["executor"]["settings"])),
        "login_found": login is not None and world.files.exists(login),
        "network": network,
        "changes_allowed": changes,
    }


def launch_context(world: Operations, raw: Mapping[str, Any], run_area: str) -> LaunchContext:
    """What a launch command is built from; a standard setting the document left out is the
    cautious one (the check has refused a driver that needs it)."""
    network, changes = decisions.standard_settings(raw)
    return {
        "place": world.boundary.resolve(raw["place"]),
        "run_area": run_area,
        "network": network is True,
        "changes_allowed": changes is True,
    }


def saved_output(world: Operations, driver: Driver, run_area: str) -> SavedOutput:
    """The text of what the tool left, each None when it is not there or cannot be read. The
    session record is not found yet (the file operations cannot list a folder)."""
    files = driver.output_files(run_area)

    def read(name: str | None) -> str | None:
        if name is None:
            return None
        try:
            return world.files.read(name).decode("utf-8")
        except (OSError, ValueError):
            return None

    return {
        "events": read(files.get("events")),
        "last_message": read(files.get("last_message")),
        "session_record": None,
    }
