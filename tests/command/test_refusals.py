"""The command seam: refusals and the check form, through the real command as a child process.

The pure checks are tables in tests/by_value/test_refusals.py. Here each reaches the real command
by one input, and the real files show what was and was not written.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WRITES_WITNESS = "import sys\nopen(sys.argv[1], 'w').write('started')\n"
GATE_ANSWERS = "import sys\nsys.exit(int(sys.argv[1]))\n"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class RealCommand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.records = os.path.join(self.root, "records")
        os.mkdir(self.records)
        self.witness = os.path.join(self.root, "witness.txt")
        self.script = self.write("script.py", WRITES_WITNESS)
        self.gate_script = self.write("gate.py", GATE_ANSWERS)

    def write(self, name, text):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def document(self, **extra):
        doc = {
            "format_version": 1,
            "request_id": "req-1",
            "records_location": self.records,
            "thread": "t",
            "round": 1,
            "kind": "plain",
            "time_limit_seconds": 30,
            "executor": {
                "name": "command",
                "settings": {"command": sys.executable, "arguments": [self.script, self.witness]},
            },
        }
        doc.update(extra)
        return doc

    def gate(self, answer, name="quota"):
        return {
            "name": name,
            "command": sys.executable,
            "arguments": [self.gate_script, str(answer)],
            "limit_seconds": 20,
        }

    def command(self, form, doc, name="input.json"):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            json.dump(doc, f)
        done = subprocess.run(
            [sys.executable, "-m", "shuttle", form, path],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return done, done.stdout.splitlines()

    def outcome(self, request_id="req-1"):
        with open(os.path.join(self.records, f"{request_id}.outcome.json")) as f:
            return json.load(f)

    def ending(self, record):
        ending = record["receipt"]["ending"]
        return tuple(ending[k]["value"] for k in ("ending", "reason", "failed_step"))

    def snapshot(self):
        contents = {}
        for name in os.listdir(self.records):
            with open(os.path.join(self.records, name), "rb") as f:
                contents[name] = f.read()
        return contents


class Refusals(RealCommand):
    def test_each_input_check_refuses_by_one_input_and_the_executor_never_starts(self):
        taken = self.write("taken.json", "x")
        runbook = self.write("runbook.md", "contents")
        cases = (
            ("unknown_format_version", self.document(format_version=2)),
            ("unknown_field", self.document(surprise=1)),
            ("unknown_kind", self.document(kind="nonesuch")),
            (
                "instruction_hash_mismatch",
                self.document(instruction="do it", instruction_hash=sha("other")),
            ),
            (
                "reference_missing",
                self.document(references=[ref(os.path.join(self.root, "absent"), "x")]),
            ),
            ("reference_hash_mismatch", self.document(references=[ref(runbook, "different")])),
            ("statement_location_occupied", self.document(kind="judge", statement_location=taken)),
            ("reach_not_available", self.document(reach=["x"])),
            (
                "credential_like_value",
                self.document(environment=["K=sk-abcdefghijklmnopqrstuvwxyz"]),
            ),
            (
                "no_time_limit",
                {k: v for k, v in self.document().items() if k != "time_limit_seconds"},
            ),
        )
        for reason, doc in cases:
            with self.subTest(reason):
                for name in os.listdir(self.records):
                    os.unlink(os.path.join(self.records, name))
                done, lines = self.command("run", doc)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(lines[-1], "could_not_start")
                self.assertEqual(
                    self.ending(self.outcome()), ("could_not_start", reason, "input_check")
                )
                self.assertFalse(os.path.exists(self.witness))

    def test_a_matching_instruction_hash_and_reference_run(self):
        runbook = self.write("runbook.md", "contents")
        doc = self.document(
            instruction="do it",
            instruction_hash=sha("do it"),
            references=[ref(runbook, "contents")],
        )
        done, lines = self.command("run", doc)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertTrue(os.path.exists(self.witness))

    def test_a_gate_is_asked_before_the_executor_and_a_no_or_a_failure_is_refused_by_name(self):
        for answer, reason in ((1, "gate_said_no"), (2, "gate_failed")):
            with self.subTest(answer):
                for name in os.listdir(self.records):
                    os.unlink(os.path.join(self.records, name))
                done, lines = self.command("run", self.document(gates=[self.gate(answer)]))
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(self.ending(self.outcome()), ("could_not_start", reason, "gates"))
                reason_text = self.outcome()["receipt"]["ending"]["reason_text"]["value"]
                self.assertIn("quota", reason_text)
                self.assertFalse(os.path.exists(self.witness))

    def test_a_gate_that_says_yes_lets_the_executor_start(self):
        done, lines = self.command("run", self.document(gates=[self.gate(0)]))
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertTrue(os.path.exists(self.witness))

    def test_a_used_request_id_is_refused_whether_or_not_the_earlier_run_finished(self):
        self.command("run", self.document())
        first = self.snapshot()
        done, lines = self.command("run", self.document())
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines, ["req-1", "could_not_start"])
        self.assertEqual(self.snapshot(), first)
        os.unlink(
            os.path.join(self.records, "req-1.outcome.json")
        )  # an earlier run that never finished
        unfinished = self.snapshot()
        done, lines = self.command("run", self.document())
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines, ["req-1", "could_not_start"])
        self.assertEqual(self.snapshot(), unfinished)

    def test_an_absent_request_id_is_generated_and_printed_first(self):
        doc = self.document()
        del doc["request_id"]
        done, lines = self.command("run", doc)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(lines[0], "^[0-9a-f]{32}$")
        self.assertEqual(
            sorted(os.listdir(self.records)),
            sorted([f"{lines[0]}.request.json", f"{lines[0]}.outcome.json"]),
        )


class CheckForm(RealCommand):
    def test_a_passing_check_launches_nothing_writes_nothing_and_says_it_is_not_a_promise(self):
        done, lines = self.command("check", self.document(gates=[self.gate(0)]))
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(lines[0], "req-1")
        self.assertEqual(lines[1], "check: no refusal found")
        self.assertIn("not a promise", lines[-1])
        self.assertEqual(os.listdir(self.records), [])
        self.assertFalse(os.path.exists(self.witness))

    def test_a_refusal_is_the_shape_of_an_outcome_record_and_the_id_stays_free(self):
        done, lines = self.command("check", self.document(kind="nonesuch"))
        self.assertEqual(done.returncode, 0, done.stderr)
        record = json.loads(lines[1])
        self.assertEqual(sorted(record), ["header", "receipt"])
        self.assertEqual(self.ending(record), ("could_not_start", "unknown_kind", "input_check"))
        self.assertEqual(os.listdir(self.records), [])
        done, lines = self.command("run", self.document())  # the id was not spent
        self.assertEqual(lines[-1], "ended_by_itself")

    def test_an_absent_request_id_is_generated_printed_and_not_spent(self):
        doc = self.document()
        del doc["request_id"]
        done, lines = self.command("check", doc)
        self.assertRegex(lines[0], "^[0-9a-f]{32}$")
        self.assertEqual(os.listdir(self.records), [])

    def test_a_document_too_broken_to_form_a_header_is_one_line_and_exits_non_zero(self):
        done, lines = self.command("check", {"round": 1})
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines, ["none"])
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)


def ref(path, text):
    return {
        "name": "runbook",
        "path": path,
        "hash": sha(text),
        "size": len(text),
        "hash_source": "caller",
    }


if __name__ == "__main__":
    unittest.main()
