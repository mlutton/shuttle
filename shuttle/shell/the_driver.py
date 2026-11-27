"""The executor driver a document names, and what the shell gathers for it.

The only module of the shell that reaches the table of drivers: every step asks here, so no step
names a driver. What is gathered is looked at, never opened: whether the program is found,
whether the login's name is there, and whether each source the driver's setup needs is there.
"""

from collections.abc import Iterator, Mapping
from typing import Any

from shuttle.core import decisions, run_area
from shuttle.core.drivers import table
from shuttle.core.drivers.interface import Driver
from shuttle.core.shapes import DriverFacts, LaunchContext, Line, Operations, SavedOutput


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


# The longest line read from the tool's output. It bounds what one line can cost; the stream as a
# whole has no size limit, since it is never held.
LINE_LIMIT = 1 << 20


def saved_output(world: Operations, driver: Driver, run_area: str) -> SavedOutput:
    """What the tool left, each file a single pass over its lines, or None when it is not there
    or cannot be opened. The session record is not found yet (the file operations cannot list a
    folder)."""
    files = driver.output_files(run_area)

    def lines(name: str | None) -> Iterator[Line] | None:
        if name is None:
            return None
        try:
            return world.files.read_lines(name, LINE_LIMIT)
        except OSError:
            return None

    return {
        "events": lines(files.get("events")),
        "last_message": lines(files.get("last_message")),
        "session_record": None,
    }


def missing_setup_source(world: Operations, raw: Mapping[str, Any]) -> str | None:
    """The first path the driver's set-up needs and that is not there, or None; looked at, never
    opened. The run's set-up fails on exactly such a path."""
    driver = of(raw)
    requests = driver.setup_requests(raw["executor"]["settings"], caller_variables(world, driver))
    followed = run_area.followed_sources(requests)

    def there(source: str) -> bool:
        return world.files.exists(world.boundary.resolve(source) if source in followed else source)

    return next((s for s in run_area.required_sources(requests) if not there(s)), None)
