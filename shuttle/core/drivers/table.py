"""The executor drivers, by the name a document gives. The one place that names them."""

from shuttle.core.drivers import codex, command
from shuttle.core.drivers.interface import Driver

DRIVERS: dict[str, Driver] = {
    command.NAME: command,
    codex.NAME: codex,
}
