"""Runs the whole suite like `python -m unittest discover -s tests` and records the facts the
per-run report needs, as JSON: every test's id, outcome and time, the skip reasons, the
total time and the largest resident size reached (from resource.getrusage, this process and
the processes it started and waited for).

Usage: timed_tests.py <output.json>   (run from the project's root, by checks/report.py,
under coverage). Standard output and error carry nothing; the suite's own text goes to
<output.json>'s "text" field. Exit codes: 0 the file was written (whether or not every test
passed); 2 misuse. Times are read from the clock here, in the runner; the tests read none.
"""

# These scripts read files and run tools; the ban on that is for the package, not for them.
# ruff: noqa: TID251

import io
import json
import os
import resource
import sys
import time
import unittest
from typing import Any


class RecordingResult(unittest.TextTestResult):
    """Notes how long each test took and how it ended (a failing sub-test fails its test)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.records: list[dict[str, Any]] = []
        self._started = 0.0
        self._outcome = "passed"
        self._reason = ""

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self._outcome, self._reason = "passed", ""
        self._started = time.perf_counter()

    def stopTest(self, test: unittest.TestCase) -> None:
        seconds = time.perf_counter() - self._started
        super().stopTest(test)
        self.records.append(
            {
                "id": test.id(),
                "seconds": seconds,
                "outcome": self._outcome,
                "reason": self._reason,
            }
        )

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self._outcome, self._reason = "skipped", reason

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addFailure(test, err)
        self._outcome = "failed"

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        super().addError(test, err)
        self._outcome = "error"

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase, err: Any) -> None:
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._outcome = "failed"

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self._outcome = "failed"


def run_suite() -> dict[str, Any]:
    sys.path.insert(0, os.getcwd())  # as `python -m unittest` does, so `shuttle` imports
    suite = unittest.defaultTestLoader.discover("tests")
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, resultclass=RecordingResult, verbosity=1)
    started = time.perf_counter()
    result = runner.run(suite)
    total = time.perf_counter() - started
    assert isinstance(result, RecordingResult)
    return {
        "tests": result.records,
        "total_seconds": total,
        "was_successful": result.wasSuccessful(),
        "text": stream.getvalue(),
        "platform": sys.platform,
        "maxrss_self": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "maxrss_children": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: timed_tests.py <output.json>", file=sys.stderr)
        return 2
    data = run_suite()
    with open(argv[1], "w", encoding="utf-8") as f:
        json.dump(data, f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
