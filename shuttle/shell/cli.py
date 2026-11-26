"""The command line: python3 -m shuttle run <input document>
       python3 -m shuttle check <input document>

Exit codes of the run form (the check form's are in shuttle/shell/check_form.py):
  0  an outcome record was written (whatever the ending, "could not start" included)
  1  no outcome record was written; one line on standard error says why

This is the one place the real operations are wired in: `entry` hands `main` to the world,
which gives it the process's arguments and streams and the real set of operations.
"""

from collections.abc import Sequence
from typing import TextIO

from shuttle.core import decisions
from shuttle.core.shapes import Operations
from shuttle.shell import check_form, run
from shuttle.world import real


def main(argv: Sequence[str], out: TextIO, err: TextIO, world: Operations) -> int:
    parsed = decisions.parse_command_line(argv)
    if "refusal" in parsed:
        err.write(parsed["refusal"] + "\n")
        return 1
    if parsed["form"] == "check":
        return check_form.check(parsed["document_path"], out, err, world)
    return run.run(parsed["document_path"], out, err, world)


def entry() -> None:
    """What `python3 -m shuttle` runs: the command line, with the process's own edge."""
    real.start(main)
