"""The one full-flow test of a time limit: everything real, and one real wait.

The logic around the waiting (which cause wins, the order ask / grace / kill, the facts) is
by value on the simulated world in tests/by_value/test_waiting.py, and the real ask and kill
are held to the contract in test_world_contract.py. This test proves the pieces work together
on a real child that is still running when the limit passes: it is asked to end, it ends, the
record says time_limit, and the child is gone.
"""

import importlib
import io
import json
import os
import sys
import tempfile
import time
import unittest

from shuttle.shell import run
from shuttle.world import real

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat

LIMIT = 0.5  # long enough that the script has started before the limit passes

SLEEPS = """
import os, sys, time
open(sys.argv[1], "w").write(str(os.getpid()))
time.sleep(60)
"""


class FullFlowOfATimeLimit(unittest.TestCase):
    def test_a_script_still_running_at_the_limit_is_asked_to_end_and_the_ending_is_time_limit(self):
        with tempfile.TemporaryDirectory() as root:
            records = os.path.join(root, "records")
            os.mkdir(records)
            script, pid_file = (os.path.join(root, n) for n in ("script.py", "pid.txt"))
            with open(script, "w") as f:
                f.write(SLEEPS)
            document = os.path.join(root, "input.json")
            with open(document, "w") as f:
                json.dump(
                    {
                        "format_version": 1,
                        "request_id": "g-1",
                        "records_location": records,
                        "thread": "t",
                        "round": 1,
                        "kind": "plain",
                        "time_limit_seconds": LIMIT,
                        "executor": {
                            "name": "command",
                            "settings": {
                                "command": sys.executable,
                                "arguments": [script, pid_file],
                            },
                        },
                    },
                    f,
                )
            out, err = io.StringIO(), io.StringIO()
            started = time.monotonic()
            code = run.run(document, out, err, real.OPERATIONS)
            elapsed = time.monotonic() - started
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(out.getvalue().splitlines()[-1], "time_limit")
            with open(os.path.join(records, "g-1.outcome.json")) as f:
                receipt = flat(json.load(f)["receipt"])
            ending = receipt["the_ending"]
            self.assertEqual(
                (ending["ending"], ending["reason"], ending["failed_step"]),
                ("time_limit", "time_limit", "none"),
            )
            self.assertEqual(receipt["what_execution_saw"]["signal"], "SIGTERM")  # it was asked
            self.assertGreaterEqual(elapsed, LIMIT)
            with open(pid_file) as f:
                pid = int(f.read())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)  # ended and reaped by the run: the process is gone


if __name__ == "__main__":
    unittest.main()
