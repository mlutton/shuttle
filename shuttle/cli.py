"""The command line: python3 -m shuttle run <input document>

Exit codes:
  0  an outcome record was written (whatever the ending, "could not start" included)
  1  no outcome record was written; one line on standard error says why
"""

import sys

from shuttle import core, run


def main(argv, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    parsed = core.parse_command_line(argv)
    if "refusal" in parsed:
        err.write(parsed["refusal"] + "\n")
        return 1
    return run.run(parsed["document_path"], out, err)
