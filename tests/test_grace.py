"""The one full-flow test of a time limit, with a real process and real waiting.

The logic around the waiting (which cause wins, the order ask / grace / kill, the facts)
is tested by value in test_waiting.py. This test proves the pieces work together on a real
child: it ignores the ask, the limit passes, the grace passed in is short, it is killed,
and the record says time_limit.
"""

import io
import json
import os
import sys
import tempfile
import time
import unittest

from shuttle import run

LIMIT = 0.5  # long enough that the script has started and set its handler before the limit passes
GRACE = 0.05

IGNORES_THE_ASK = """
import os, signal, sys, time
signal.signal(signal.SIGTERM, lambda number, frame: open(sys.argv[2], "w").close())
open(sys.argv[1], "w").write(str(os.getpid()))
time.sleep(60)
"""


class FullFlowOfATimeLimit(unittest.TestCase):
    def test_a_script_that_ignores_the_ask_is_killed_after_the_limit_and_the_grace_and_the_ending_is_time_limit(
        self,
    ):
        with tempfile.TemporaryDirectory() as root:
            records = os.path.join(root, "records")
            os.mkdir(records)
            script, pid_file, asked_file = (
                os.path.join(root, n) for n in ("script.py", "pid.txt", "asked.txt")
            )
            with open(script, "w") as f:
                f.write(IGNORES_THE_ASK)
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
                                "arguments": [script, pid_file, asked_file],
                            },
                        },
                    },
                    f,
                )
            out, err = io.StringIO(), io.StringIO()
            started = time.monotonic()
            code = run.run(document, out, err, grace=GRACE)
            elapsed = time.monotonic() - started
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(out.getvalue().splitlines()[-1], "time_limit")
            with open(os.path.join(records, "g-1.outcome.json")) as f:
                ending = json.load(f)["receipt"]["the_ending"]
            self.assertEqual(
                (ending["ending"], ending["reason"], ending["failed_step"]),
                ("time_limit", "time_limit", "none"),
            )
            self.assertTrue(
                os.path.exists(asked_file), "the script was asked to end before it was killed"
            )
            self.assertGreaterEqual(elapsed, LIMIT + GRACE)
            with open(pid_file) as f:
                pid = int(f.read())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)  # killed and reaped by the run: the process is gone


if __name__ == "__main__":
    unittest.main()
