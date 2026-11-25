"""The command seam: the real command, run as a child process.

Each test makes its own temporary root holding the records location and the
small scripts. Nothing outside it is read or written.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from shuttle import fixed

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENDS_BY_ITSELF = """
import os, sys
witness, request_record, code = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(witness, "w") as f:
    f.write("request record existed at start: %s" % os.path.exists(request_record))
sys.exit(code)
"""


class CommandSeam(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.records = os.path.join(self.root, "records")
        os.mkdir(self.records)
        self.script = os.path.join(self.root, "script.py")
        with open(self.script, "w") as f:
            f.write(ENDS_BY_ITSELF)
        self.witness = os.path.join(self.root, "witness.txt")

    def document(self, request_id="req-1", exit_code=0, **extra):
        doc = {
            "format_version": 1,
            "request_id": request_id,
            "records_location": self.records,
            "executor": {
                "driver": "command",
                "settings": {
                    "command": sys.executable,
                    "arguments": [self.script, self.witness,
                                  os.path.join(self.records, "%s.request.json" % request_id), str(exit_code)],
                },
            },
        }
        doc.update(extra)
        return doc

    def run_command(self, doc, name="input.json", argv=None):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            if isinstance(doc, str):
                f.write(doc)
            else:
                json.dump(doc, f)
        done = subprocess.run(
            [sys.executable, "-m", "shuttle"] + (argv if argv is not None else ["run", path]),
            cwd=REPO, capture_output=True, text=True, timeout=60)
        return done, done.stdout.splitlines()

    def snapshot(self):
        contents = {}
        for name in os.listdir(self.records):
            with open(os.path.join(self.records, name), "rb") as f:
                contents[name] = f.read()
        return contents

    def read(self, name):
        with open(os.path.join(self.records, name)) as f:
            return json.load(f)

    def test_a_script_that_ends_by_itself_prints_id_then_path_then_ending_and_exits_zero(self):
        done, lines = self.run_command(self.document())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines, ["req-1", os.path.join(self.records, "req-1.outcome.json"), "ended_by_itself"])
        self.assertEqual(done.stderr, "")

    def test_the_request_record_exists_before_the_script_starts(self):
        done, _ = self.run_command(self.document())
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(self.witness) as f:
            self.assertEqual(f.read(), "request record existed at start: True")
        request = self.read("req-1.request.json")
        self.assertEqual(request["header"]["record_type"], "request")
        self.assertEqual(request["header"]["request_id"], "req-1")
        self.assertEqual(request["input"], self.document())

    def test_the_outcome_record_holds_every_receipt_field_in_four_groups(self):
        self.run_command(self.document())
        outcome = self.read("req-1.outcome.json")
        self.assertEqual(outcome["header"]["record_type"], "outcome")
        self.assertEqual(outcome["header"]["request_id"], "req-1")
        self.assertEqual(outcome["header"]["format_version"], 1)
        receipt = outcome["receipt"]
        self.assertEqual(sorted(receipt), sorted([
            "the_ending", "what_execution_saw", "what_the_driver_observed", "what_the_executor_said"]))
        for group, names in fixed.RECEIPT_GROUPS.items():
            self.assertEqual(sorted(receipt[group]), sorted(names), group)
            for name in names:
                value = receipt[group][name]
                self.assertNotIn(value, (None, "", [], {}), "%s.%s" % (group, name))
        ending = receipt["the_ending"]
        self.assertEqual((ending["ending"], ending["reason"], ending["failed_step"]),
                         ("ended_by_itself", "none", "none"))
        saw = receipt["what_execution_saw"]
        self.assertEqual(saw["exit_code"], 0)
        self.assertEqual(saw["signal"], "none")
        self.assertEqual(len(saw["input_hash"]), 64)
        self.assertEqual(receipt["what_the_driver_observed"]["driver_name"], "command")

    def test_what_is_a_stand_in_says_cannot_tell(self):
        self.run_command(self.document())
        receipt = self.read("req-1.outcome.json")["receipt"]
        for group, field in [
            ("what_execution_saw", "fingerprint_before"),
            ("what_execution_saw", "fingerprint_after"),
            ("what_execution_saw", "changed_nothing"),
            ("what_execution_saw", "delivered"),
            ("what_execution_saw", "teardown_failure"),
            ("what_execution_saw", "peak_memory"),
            ("the_ending", "everything_stopped"),
            ("what_the_executor_said", "claim"),
        ]:
            self.assertEqual(receipt[group][field], "cannot tell", field)

    def test_the_exit_code_of_the_script_is_recorded_and_does_not_change_the_ending(self):
        done, lines = self.run_command(self.document(exit_code=7))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-1], "ended_by_itself")
        receipt = self.read("req-1.outcome.json")["receipt"]
        self.assertEqual(receipt["what_execution_saw"]["exit_code"], 7)
        self.assertEqual(receipt["the_ending"]["ending"], "ended_by_itself")

    def test_a_second_run_with_the_same_request_id_is_refused_and_leaves_the_first_records_untouched(self):
        self.run_command(self.document())
        before = self.snapshot()
        os.remove(self.witness)
        done, lines = self.run_command(self.document(exit_code=9), name="second.json")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines, ["req-1", "could_not_start"])
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)
        self.assertIn("req-1", done.stderr)
        after = self.snapshot()
        self.assertEqual(after, before)
        self.assertFalse(os.path.exists(self.witness), "the script must not run")

    def test_a_document_with_an_unknown_field_is_refused_and_recorded(self):
        done, lines = self.run_command(self.document(surprise=True))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines, ["req-1", os.path.join(self.records, "req-1.outcome.json"), "could_not_start"])
        ending = self.read("req-1.outcome.json")["receipt"]["the_ending"]
        self.assertEqual((ending["ending"], ending["reason"], ending["failed_step"]),
                         ("could_not_start", "unknown_field", "input_check"))
        self.assertIn("surprise", ending["reason_text"])
        self.assertFalse(os.path.exists(self.witness), "the script must not run")
        self.assertTrue(os.path.exists(os.path.join(self.records, "req-1.request.json")))

    def test_a_tool_that_is_not_installed_could_not_start_at_the_driver_check(self):
        doc = self.document()
        doc["executor"]["settings"]["command"] = os.path.join(self.root, "no-such-tool")
        done, lines = self.run_command(doc)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-1], "could_not_start")
        ending = self.read("req-1.outcome.json")["receipt"]["the_ending"]
        self.assertEqual((ending["reason"], ending["failed_step"]), ("tool_not_installed", "driver_check"))

    def test_a_document_too_broken_to_form_a_header_spends_no_id_and_writes_nothing(self):
        for name, text in [("not json", "{nope"), ("no request id", json.dumps({"format_version": 1}))]:
            with self.subTest(name):
                done, lines = self.run_command(text)
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(lines, ["none"])
                self.assertEqual(len(done.stderr.strip().splitlines()), 1)
                self.assertEqual(os.listdir(self.records), [])

    def test_a_missing_document_is_refused_in_one_line(self):
        done, lines = self.run_command(None, argv=["run", os.path.join(self.root, "absent.json")])
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines, ["none"])
        self.assertEqual(os.listdir(self.records), [])

    def test_the_other_three_forms_print_a_one_line_refusal(self):
        for form in ("check", "stop", "status"):
            with self.subTest(form):
                done, lines = self.run_command(None, argv=[form, "x"])
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(lines, [])
                self.assertEqual(len(done.stderr.strip().splitlines()), 1)
                self.assertIn(form, done.stderr)

    def test_a_failed_outcome_write_prints_the_receipt_then_the_ending_and_exits_non_zero(self):
        os.mkdir(os.path.join(self.records, "req-1.outcome.json"))  # something is in the way
        done, lines = self.run_command(self.document())
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines[0], "req-1")
        self.assertEqual(lines[-1], "ended_by_itself")
        printed = json.loads("\n".join(lines[1:-1]))
        self.assertEqual(printed["the_ending"]["ending"], "ended_by_itself")
        self.assertIn("not written", done.stderr)


if __name__ == "__main__":
    unittest.main()
