"""The grace before a kill, run in-process with a grace of a few hundredths of a second.

Nothing here waits out the real grace. The child is a script that ignores the first request
to end (SIGTERM) so only the kill ends it. A signal sent to this process during a run is
sent only after the child has written a file, which is after the run installed its handlers.
"""
import io
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest

from shuttle import run

LIMIT = 0.5   # long enough that the script has started and set its handler before the limit passes
GRACE = 0.05
GRACE_FOR_A_SIGNAL_TO_ARRIVE = 0.3

IGNORES_THE_FIRST_REQUEST = """
import signal, sys, time
pid_file, asked_file = sys.argv[1], sys.argv[2]
signal.signal(signal.SIGTERM, lambda number, frame: open(asked_file, "w").close())
open(pid_file, "w").write(str(__import__("os").getpid()))
time.sleep(60)
"""


def wait_for(path, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.005)
    return False


class TheGrace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.records = os.path.join(self.root, "records")
        os.mkdir(self.records)
        self.script = os.path.join(self.root, "script.py")
        with open(self.script, "w") as f:
            f.write(IGNORES_THE_FIRST_REQUEST)
        self.pid_file = os.path.join(self.root, "pid.txt")
        self.asked_file = os.path.join(self.root, "asked.txt")
        self.sent_at = None

    def document(self, time_limit_seconds):
        path = os.path.join(self.root, "input.json")
        with open(path, "w") as f:
            json.dump({
                "format_version": 1, "request_id": "g-1", "records_location": self.records,
                "thread": "t", "round": 1, "kind": "plain", "time_limit_seconds": time_limit_seconds,
                "executor": {"name": "command", "settings": {
                    "command": sys.executable, "arguments": [self.script, self.pid_file, self.asked_file]}},
            }, f)
        return path

    def signal_self_once(self, after_file):
        """Send SIGTERM to this process once `after_file` exists. Returns the thread; join it.

        A late signal must not kill the test runner, so SIGTERM is ignored outside the run.
        """
        previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        def send():
            if wait_for(after_file):
                self.sent_at = time.monotonic()
                os.kill(os.getpid(), signal.SIGTERM)
        thread = threading.Thread(target=send)
        thread.start()
        self.addCleanup(thread.join)
        return thread

    def run_it(self, time_limit_seconds, grace=GRACE):
        out, err = io.StringIO(), io.StringIO()
        code = run.run(self.document(time_limit_seconds), out, err, grace=grace)
        self.ended_at = time.monotonic()
        self.assertEqual(code, 0, err.getvalue())
        with open(os.path.join(self.records, "g-1.outcome.json")) as f:
            ending = json.load(f)["receipt"]["the_ending"]
        return (ending["ending"], ending["reason"], ending["failed_step"]), out.getvalue().splitlines()[-1]

    def assert_killed(self):
        with open(self.pid_file) as f:
            pid = int(f.read())
        end = time.monotonic() + 5
        while time.monotonic() < end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        self.fail("process %d is still running" % pid)

    def test_the_default_grace_is_the_documented_three_seconds(self):
        self.assertEqual(run.END_GRACE_SECONDS, 3)
        self.assertEqual(run.end_child.__defaults__, (3,))
        self.assertEqual(run.run.__defaults__[-1], 3)

    def test_a_script_that_ignores_the_first_request_is_killed_after_the_grace_at_the_time_limit(self):
        started = time.monotonic()
        ending, last_line = self.run_it(LIMIT)
        self.assertEqual(ending, ("time_limit", "time_limit", "none"))
        self.assertEqual(last_line, "time_limit")
        self.assertGreaterEqual(time.monotonic() - started, LIMIT + GRACE)   # the kill came after the grace
        self.assertTrue(os.path.exists(self.asked_file), "the script was asked to end first")
        self.assert_killed()

    def test_a_signal_during_the_grace_after_the_time_limit_changes_nothing_and_the_script_is_killed(self):
        self.signal_self_once(self.asked_file)   # the file exists once the limit has passed and the script was asked to end
        ending, last_line = self.run_it(LIMIT, GRACE_FOR_A_SIGNAL_TO_ARRIVE)
        self.assertEqual(ending, ("time_limit", "time_limit", "none"))
        self.assertEqual(last_line, "time_limit")
        self.assertLess(self.sent_at, self.ended_at, "the signal was sent while the run was still going")
        self.assert_killed()

    def test_when_a_signal_comes_first_the_ending_is_the_signal_and_the_script_that_ignores_the_request_is_killed(self):
        self.signal_self_once(self.pid_file)   # the script is running; the limit is far away
        ending, last_line = self.run_it(30, GRACE_FOR_A_SIGNAL_TO_ARRIVE)
        self.assertEqual(ending, ("stopped_from_outside", "signal", "none"))
        self.assertEqual(last_line, "stopped_from_outside")
        self.assert_killed()


if __name__ == "__main__":
    unittest.main()
