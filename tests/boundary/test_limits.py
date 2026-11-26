"""The harness holds a real command, and what it starts, to its resource limits.

A script that writes or allocates without end is ended by the limits (inherited through the scope
tool and the boundary) in about a second, and the test sees a failure instead of growth. The
script stops itself at four times the limit and says so, so even a harness that lost its limits
could not exhaust the machine here. No test keeps time.
"""

import importlib
import os
import resource
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")

# argv 1 is where it writes, argv 2 where it says what happened, argv 3 the largest it may try.
WRITES_WITHOUT_END = """
import sys
written, outcome = 0, "NOT LIMITED"
try:
    with open(sys.argv[1], "wb") as f:
        while written < int(sys.argv[3]):
            f.write(b"x" * (1 << 20))
            f.flush()
            written += 1 << 20
except OSError:
    outcome = "limited"
open(sys.argv[2], "w").write(outcome)
"""

# argv 1 where it says what happened, argv 2 the largest total it may try.
ALLOCATES_WITHOUT_END = """
import sys
held, outcome = [], "NOT LIMITED"
try:
    while len(held) * (64 << 20) < int(sys.argv[2]):
        held.append(bytearray(64 << 20))
except MemoryError:
    outcome = "limited"
open(sys.argv[1], "w").write(outcome)
"""


class TheLimitsReachTheExecutor(real_run.RealRun):
    def said(self, name):
        with open(os.path.join(self.place, name)) as f:
            return f.read()

    def test_a_script_that_writes_without_end_is_stopped_by_the_file_size_limit(self):
        limit = self.limits[resource.RLIMIT_FSIZE]
        big = os.path.join(self.place, "big")
        script = self.script("writes.py", WRITES_WITHOUT_END)
        doc = self.document(script, [big, os.path.join(self.place, "said"), str(4 * limit)])
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        self.assertEqual(self.said("said"), "limited")
        self.assertLessEqual(os.path.getsize(big), limit)

    def test_a_script_that_allocates_without_end_is_stopped_by_the_address_space_limit(self):
        limit = self.limits[resource.RLIMIT_AS]
        script = self.script("allocates.py", ALLOCATES_WITHOUT_END)
        doc = self.document(script, [os.path.join(self.place, "said"), str(4 * limit)])
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        self.assertEqual(self.said("said"), "limited")

    def test_a_test_can_raise_a_limit_for_itself_and_only_for_itself(self):
        self.raise_limit(resource.RLIMIT_FSIZE, 64 * 1024 * 1024, "a case that keeps a big file")
        self.assertEqual(self.limits[resource.RLIMIT_FSIZE], 64 * 1024 * 1024)
        self.assertEqual(real_run.DEFAULT_LIMITS[resource.RLIMIT_FSIZE], 16 * 1024 * 1024)
