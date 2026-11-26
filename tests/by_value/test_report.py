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

    def test_text_in_a_string_is_not_a_marker_and_is_reported_as_an_excluded_line(self):
        # coverage matches source lines, so it excludes this line; the report must say so
        found, problems = report.find_markers("a.py", f'x = "{report.MARKER} y"\n')
        self.assertEqual(found, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("a.py line 1", problems[0])
        self.assertIn("outside a comment", problems[0])

    def test_a_docstring_line_holding_the_text_is_reported_by_its_own_line(self):
        source = f'"""Doc\nmentions {report.MARKER} here\n"""\n'
        _, problems = report.find_markers("a.py", source)
        self.assertEqual(len(problems), 1)
        self.assertIn("a.py line 2", problems[0])

    def test_a_real_marker_is_listed_and_raises_no_problem_so_excluded_and_listed_agree(self):
        found, problems = report.find_markers("a.py", f"x = 1  {report.MARKER} why\n")
        self.assertEqual(found, [report.Marker("a.py", 1, "why")])
        self.assertEqual(problems, [])

    def test_this_module_s_own_source_holds_the_marker_text_nowhere_outside_a_comment(self):
        with open(os.path.join(CHECKS, "report.py"), encoding="utf-8") as f:
            self.assertEqual(report.find_markers("checks/report.py", f.read()), ([], []))


class RowsAndCommitTest(unittest.TestCase):
    def test_the_rows_are_the_walked_files_whatever_coverage_found(self):
        measured = [F("shuttle/a.py", 3, (2,), ()), F("shuttle/stray_data.py", 9, (), ())]
        analysed = {"shuttle/sub/nopkg.py": F("shuttle/sub/nopkg.py", 4, (1, 2, 3, 4), ())}
        walked = ["shuttle/sub/nopkg.py", "shuttle/a.py", "shuttle/gone.py"]
        rows = report.merge_rows(walked, measured, analysed)
        self.assertEqual([r.path for r in rows], sorted(walked))
        by_path = {r.path: r for r in rows}
        self.assertEqual(by_path["shuttle/sub/nopkg.py"].missing, (1, 2, 3, 4))
        self.assertIsNone(by_path["shuttle/gone.py"].statements)

    def test_a_file_that_could_not_be_analysed_says_not_measured_and_adds_nothing_to_totals(self):
        text = report.render_report(
            facts(files=(F("shuttle/x.py", None, (), ()), F("shuttle/y.py", 2, (1,), ())))
        )
        row = next(x for x in text.splitlines() if x.startswith("shuttle/x.py"))
        self.assertIn("not measured", row)
        total = next(x for x in text.splitlines() if x.startswith("total"))
        self.assertRegex(total, r"total\s+2\s+1\s+50%")

    PR = {"event": "pull_request", "head": "a" * 40, "base": "b" * 40, "run": "c" * 40}

    def test_on_a_pull_request_the_head_is_named_and_the_merge_with_the_base_too(self):
        text = report.commit_text(self.PR, "d" * 40, False)
        self.assertTrue(text.startswith("a" * 40 + ", the head of the pull request"))
        self.assertIn("merge of it with the base " + "b" * 40, text)
        self.assertIn("merge commit " + "c" * 40, text)
        self.assertNotIn("d" * 40, text)

    def test_locally_it_is_head_and_says_when_the_tree_is_dirty(self):
        self.assertEqual(report.commit_text({}, "d" * 40, False), "d" * 40)
        self.assertEqual(
            report.commit_text({}, "d" * 40, True), "d" * 40 + " with uncommitted changes"
        )
        self.assertEqual(report.commit_text({}, "", False), "unknown (not a git checkout)")

    def test_odd_event_values_are_not_trusted(self):
        for bad in (
            {**self.PR, "head": "x`y"},
            {**self.PR, "base": ""},
            {**self.PR, "event": "push"},
        ):
            with self.subTest(bad=bad):
                self.assertEqual(report.commit_text(bad, "d" * 40, False), "d" * 40)

    def test_the_workflow_s_variables_become_the_event_facts(self):
        env = {
            "REPORT_EVENT_NAME": "pull_request",
            "REPORT_PR_HEAD_SHA": "1" * 40,
            "REPORT_PR_BASE_SHA": "2" * 40,
            "REPORT_RUN_SHA": "3" * 40,
            "PATH": "/x",
        }
        self.assertEqual(
            report.event_facts(env),
            {"event": "pull_request", "head": "1" * 40, "base": "2" * 40, "run": "3" * 40},
        )
        self.assertEqual(report.event_facts({}), {"event": "", "head": "", "base": "", "run": ""})

    def test_the_job_log_line_has_the_count_and_the_time(self):
        tests = (T("by_value.a", 1.0, "passed"),) * 3
        line = report.log_line(facts(tests=tests, total_seconds=12.3456))
        self.assertEqual(line, "report: 3 tests run in 12.346 s under coverage (Python 3.12.1)")

    def test_a_failed_step_is_named_with_the_tools_own_last_line(self):
        self.assertEqual(
            report.step_failure("the run", 1, "", "Traceback\n  x\nNo module named coverage\n"),
            "the run failed (exit 1): No module named coverage",
        )
        self.assertEqual(report.step_failure("json", 2, "", ""), "json failed (exit 2): no output")
        self.assertTrue(
            report.failure_line("the run failed (exit 1): No module named coverage").endswith(
                "No module named coverage; see the job log."
            )
        )

    def test_the_files_run_from_copies_are_named_under_the_table_only_when_present(self):
        text = report.render_report(facts(files=(F("checks/fixmode.py", 5, (1,), ()),)))
        self.assertIn("also run from copies placed in temporary trees", text)
        self.assertIn("`checks/fixmode.py`", text.split("copies placed")[1])
        self.assertNotIn(
            "copies placed", report.render_report(facts(files=(F("a.py", 1, (), ()),)))
        )

    def test_the_python_version_sits_with_the_totals_and_counts_are_said_to_differ(self):
        text = report.render_report(facts())
        self.assertIn("Totals are for Python 3.12.1; statement counts differ between Python", text)

    def test_marker_problems_are_a_visible_block_in_the_report(self):
        text = report.render_report(facts(marker_problems=("a.py line 3: holds the text",)))
        self.assertIn("**The excluded lines and the marker list do not agree:**", text)
        self.assertIn("a.py line 3: holds the text", text)


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
            "Commit: abc123. Command: `./checks/report.sh`. Python 3.12.1; coverage.py 7.13.0.",
            "- 3 run: 2 passed, 1 skipped, 0 failed, 0 errors.",
            "- Total time: 1.900 s",
            "- Peak memory: 4.0 MiB, the largest resident size any one process",
            "the test process itself 2.0 MiB",
            "command.test_b.B.test_skip: needs a tty",
            "   1.250 s  command.test_b.B.test_two",
            "by_value      1 tests     0.500 s",
            "command       2 tests     1.250 s",
            "boundary  none yet",
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
        self.assertIn("by_value  none yet", text)
        self.assertNotIn("0 tests", text)

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
