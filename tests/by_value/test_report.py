"""The per-run report (checks/report.py), built from data: durations, skips, coverage, markers."""

import importlib
import os
import re
import sys
import tomllib
import unittest

CHECKS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "checks")
sys.path.insert(0, CHECKS)
report = importlib.import_module("report")

T = report.TestRecord
F = report.FileCoverage


def facts(**changes):
    base = {
        "commit": "abc123",
        "command": "./checks/report.sh",
        "python": "3.12.1",
        "coverage": "7.13.0",
        "tests": (),
        "total_seconds": 0.0,
        "was_successful": True,
        "peak_self_kib": 2048,
        "peak_children_kib": 4096,
        "files": (),
        "markers": (),
    }
    return report.Facts(**{**base, **changes})


def outside_fences(markdown):
    """The lines of a Markdown text that are not inside a fenced block, and the fence count."""
    outside, fence, fences = [], None, 0
    for line in markdown.splitlines():
        if fence is None and re.fullmatch(r"`{3,}", line):
            fence, fences = line, fences + 1
        elif fence is not None and line == fence:
            fence = None
        elif fence is None:
            outside.append(line)
    assert fence is None, "a fence was never closed"
    return outside, fences


class SmallHelpersTest(unittest.TestCase):
    def test_line_ranges(self):
        self.assertEqual(report.ranges([]), "")
        self.assertEqual(report.ranges([5]), "5")
        self.assertEqual(report.ranges([1, 2, 3, 7, 9, 10]), "1-3, 7, 9-10")
        self.assertEqual(report.ranges((10, 9, 9, 1)), "1, 9-10")

    def test_memory_is_kibibytes_on_linux_and_bytes_on_macos(self):
        self.assertEqual(report.to_kib(5000, "linux"), 5000)
        self.assertEqual(report.to_kib(5 * 1024 * 1024, "darwin"), 5 * 1024)

    def test_the_folder_is_the_first_part_of_the_test_id(self):
        self.assertEqual(report.folder_of("by_value.test_x.C.test_y"), "by_value")
        self.assertEqual(report.folder_of("loose"), "(other)")

    def test_the_slowest_are_the_eight_longest_ties_broken_by_name(self):
        tests = tuple(T(f"command.t{i}", float(i % 5), "passed") for i in range(20))
        top = report.slowest(tests)
        self.assertEqual(len(top), 8)
        self.assertEqual([t.seconds for t in top], [4.0] * 4 + [3.0] * 4)
        self.assertEqual([t.id for t in top[:4]], sorted(t.id for t in top[:4]))

    def test_time_per_folder_lists_the_known_folders_even_when_empty_and_unknown_ones(self):
        tests = (T("by_value.a", 0.5, "passed"), T("by_value.b", 0.25, "passed"), T("x.y", 1, "ok"))
        self.assertEqual(
            report.time_per_folder(tests),
            [("boundary", 0, 0.0), ("by_value", 2, 0.75), ("command", 0, 0.0), ("x", 1, 1.0)],
        )

    def test_percent_of_nothing_is_not_a_number(self):
        self.assertEqual(report.percent(0, 0), "n/a")
        self.assertEqual(report.percent(4, 1), "75%")


class MarkerTest(unittest.TestCase):
    def test_a_marker_gives_its_line_and_reason(self):
        source = "x = 1\ndef f():  # not tested: needs a real tty\n    return 2\n"
        found, problems = report.find_markers("shuttle/a.py", source)
        self.assertEqual(found, [report.Marker("shuttle/a.py", 2, "needs a real tty")])
        self.assertEqual(problems, [])

    def test_an_empty_reason_is_a_problem(self):
        for source in ("x = 1  # not tested:\n", "x = 1  # not tested:   \n"):
            with self.subTest(source=source):
                found, problems = report.find_markers("a.py", source)
                self.assertEqual(found, [])
                self.assertEqual(len(problems), 1)
                self.assertIn("a.py line 1", problems[0])
                self.assertIn("no reason", problems[0])

    def test_a_near_miss_that_coverage_would_not_honour_is_a_problem(self):
        for text in ("# not tested", "# Not tested because", "# not_tested: x"):
            with self.subTest(text=text):
                found, problems = report.find_markers("a.py", f"x = 1  {text}\n")
                self.assertEqual(found, [], text)
                self.assertEqual(len(problems), 1, text)

    def test_text_in_a_string_is_not_a_marker(self):
        found, problems = report.find_markers("a.py", 'x = "# not tested:"\n')
        self.assertEqual((found, problems), ([], []))


class ConfigTest(unittest.TestCase):
    def test_the_project_settings_are_written_with_absolute_sources_and_an_outside_data_file(self):
        pyproject = {
            "tool": {
                "ruff": {"line-length": 100},
                "coverage": {
                    "run": {
                        "source": ["shuttle", "checks"],
                        "parallel": True,
                        "patch": ["subprocess"],
                    },
                    "report": {"exclude_also": ["# not tested:"]},
                },
            }
        }
        text = report.coverage_config(pyproject, "/proj", "/scratch/data/.coverage")
        parsed = tomllib.loads(text)["tool"]["coverage"]
        self.assertEqual(parsed["run"]["source"], ["/proj/shuttle", "/proj/checks"])
        self.assertEqual(parsed["run"]["data_file"], "/scratch/data/.coverage")
        self.assertIs(parsed["run"]["parallel"], True)
        self.assertEqual(parsed["run"]["patch"], ["subprocess"])
        self.assertEqual(parsed["report"]["exclude_also"], ["# not tested:"])
        self.assertNotIn("ruff", tomllib.loads(text)["tool"])

    def test_a_path_with_quotes_and_backslashes_survives(self):
        text = report.coverage_config({}, 'a"b\\c', "/d")
        self.assertEqual(tomllib.loads(text)["tool"]["coverage"]["run"]["data_file"], "/d")

    def test_coverage_json_becomes_one_record_per_file_relative_to_the_root(self):
        data = {
            "files": {
                "/p/shuttle/b.py": {
                    "summary": {"num_statements": 4},
                    "missing_lines": [3, 4],
                    "excluded_lines": [9],
                },
                "/p/shuttle/a.py": {"summary": {"num_statements": 0}},
            }
        }
        self.assertEqual(
            report.normalize_coverage(data, "/p"),
            [F("shuttle/a.py", 0, (), ()), F("shuttle/b.py", 4, (3, 4), (9,))],
        )


class RenderTest(unittest.TestCase):
    def test_the_report_has_every_part_and_every_number_from_the_data(self):
        tests = (
            T("by_value.test_a.A.test_one", 0.5, "passed"),
            T("command.test_b.B.test_two", 1.25, "passed"),
            T("command.test_b.B.test_skip", 0.0, "skipped", "needs a tty"),
        )
        files = (F("shuttle/a.py", 10, (4, 5, 6, 9), ()), F("checks/n.py", 0, (), ()))
        markers = (report.Marker("shuttle/a.py", 12, "cannot be run here"),)
        text = report.render_report(
            facts(tests=tests, total_seconds=1.9, files=files, markers=markers)
        )
        for expected in (
            "Commit `abc123`; command `./checks/report.sh`; Python 3.12.1; coverage.py 7.13.0.",
            "- 3 run: 2 passed, 1 skipped, 0 failed, 0 errors.",
            "- Total time: 1.900 s",
            "- Peak memory: 4.0 MiB, the largest resident size any one process",
            "the test process itself 2.0 MiB",
            "command.test_b.B.test_skip: needs a tty",
            "   1.250 s  command.test_b.B.test_two",
            "by_value      1 tests     0.500 s",
            "command       2 tests     1.250 s",
            "boundary      0 tests     0.000 s",
            "shuttle/a.py",
            "4-6, 9",
            "total  ",
            "shuttle/a.py:12  cannot be run here",
            "It is not the total over all processes",
        ):
            self.assertIn(expected, text)
        row = next(line for line in text.splitlines() if line.startswith("shuttle/a.py "))
        self.assertRegex(row, r"shuttle/a\.py\s+10\s+4\s+60%\s+4-6, 9")

    def test_an_empty_suite_is_reported_as_such_without_failing(self):
        text = report.render_report(facts())
        self.assertIn("- 0 run: 0 passed, 0 skipped, 0 failed, 0 errors.", text)
        self.assertIn("None skipped.", text)
        self.assertIn("No tests ran.", text)
        self.assertIn("No line carries a `# not tested: <reason>` marker.", text)
        self.assertIn("by_value      0 tests     0.000 s", text)

    def test_failures_are_named(self):
        text = report.render_report(facts(failures=("a.b (failed)",)))
        self.assertIn("a.b (failed)", text)

    def test_no_name_or_reason_can_break_the_markdown(self):
        nasty = "x`\n```\n# injected\n|||<b>"
        tests = (T(f"command.{nasty}", 1.0, "skipped", nasty),)
        files = (F(nasty + ".py", 1, (1,), ()),)
        markers = (report.Marker(nasty + ".py", 3, nasty),)
        text = report.render_report(facts(tests=tests, files=files, markers=markers))
        outside, fences = outside_fences(text)
        self.assertGreaterEqual(fences, 4)
        self.assertFalse([line for line in outside if "injected" in line or "<b>" in line])
        self.assertNotIn("\n# injected", text)
        self.assertIn("\\n", text)  # the newline is shown as an escape

    def test_the_failure_line_is_one_line_saying_why(self):
        line = report.failure_line("RuntimeError: the run failed\nsecond\nlast line here")
        self.assertEqual(line.count("\n"), 0)
        self.assertTrue(line.startswith(report.COULD_NOT))
        self.assertIn("last line here", line)
        self.assertIn("unknown cause", report.failure_line(""))


if __name__ == "__main__":
    unittest.main()
