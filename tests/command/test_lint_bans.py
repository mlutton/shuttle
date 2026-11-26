"""The lint stage refuses a test that sleeps or reads the clock.

The boundary owns the time limit, so no test keeps time (tests/ruff.toml). The real ruff is run
on source text handed to it as if it sat in the tests' folders; nothing is written.
"""

import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def findings(source, where="tests/by_value/probe.py"):
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--stdin-filename",
            where,
            "--output-format",
            "concise",
            "-",
        ],
        input=source,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return [line for line in done.stdout.splitlines() if "TID251" in line]


class TheTestsMayNotKeepTime(unittest.TestCase):
    def test_each_way_of_sleeping_or_reading_the_clock_is_refused_in_every_test_folder(self):
        for call in (
            "time.sleep(1)",
            "time.time()",
            "time.monotonic()",
            "time.perf_counter()",
            "datetime.datetime.now()",
            "datetime.date.today()",
        ):
            for where in ("tests/by_value/t.py", "tests/command/t.py", "tests/boundary/t.py"):
                with self.subTest(call=call, where=where):
                    source = f"import datetime\nimport time\n\n\ndef f():\n    {call}\n"
                    self.assertTrue(findings(source, where))

    def test_importing_the_name_to_call_it_bare_is_refused_too(self):
        self.assertTrue(findings("from time import sleep\n\n\ndef f():\n    sleep(1)\n"))

    def test_what_a_test_may_still_do_is_not_refused(self):
        source = (
            "import datetime\nimport subprocess\nimport time\n\n\ndef f():\n"
            "    subprocess.run(['true'])\n    return datetime.datetime(2026, 1, 1), time.strftime\n"
        )
        self.assertEqual(findings(source), [])

    def test_the_package_keeps_its_own_ban_on_the_whole_module(self):
        self.assertTrue(findings("import time\n", "shuttle/shell/x.py"))


if __name__ == "__main__":
    unittest.main()
