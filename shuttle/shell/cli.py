"""The command line: python3 -m shuttle run <input document>

Exit codes:
  0  an outcome record was written (whatever the ending, "could not start" included)
  1  no outcome record was written; one line on standard error says why
"""

import sys
from collections.abc import Sequence
from typing import TextIO

from shuttle.core import decisions
from shuttle.shell import run


def main(argv: Sequence[str], out: TextIO | None = None, err: TextIO | None = None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parsed = decisions.parse_command_line(argv)
    if "refusal" in parsed:
        err.write(parsed["refusal"] + "\n")
        return 1
    return run.run(parsed["document_path"], out, err)


def entry() -> None:
    """What `python3 -m shuttle` runs: the command line, with the process's arguments."""
    sys.exit(main(sys.argv[1:]))
