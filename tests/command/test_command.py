"""The command seam: the real command, run as a child process.

Each test makes its own temporary root holding the records location and the
small scripts. Nothing outside it is read or written.
"""

import importlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from shuttle.core import fixed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
            "thread": "thread-1",
            "round": 1,
            "kind": "plain",
            "time_limit_seconds": 30,
            "executor": {
                "name": "command",
                "settings": {
                    "command": sys.executable,
                    "arguments": [
                        self.script,
                        self.witness,
                        os.path.join(self.records, f"{request_id}.request.json"),
                        str(exit_code),
                    ],
                },
            },
        }
        doc.update(extra)
        return doc

    def run_command(self, doc, name="input.json", argv=None, env=None):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            if isinstance(doc, str):
                f.write(doc)
            else:
                json.dump(doc, f)
        done = subprocess.run(
            [sys.executable, "-m", "shuttle"] + (argv if argv is not None else ["run", path]),
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
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
        self.assertEqual(
            lines, ["req-1", os.path.join(self.records, "req-1.outcome.json"), "ended_by_itself"]
        )
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
        self.assertEqual(request["header"]["thread"], "thread-1")
        self.assertEqual(request["header"]["round"], 1)
        self.assertEqual(request["header"]["kind"], "plain")
        self.assertEqual(request["header"]["parent_session"], "none")
        self.assertEqual(request["header"]["asked_by"], "none")

    def test_the_outcome_record_holds_every_receipt_field_in_four_groups(self):
        self.run_command(self.document())
        outcome = self.read("req-1.outcome.json")
        self.assertEqual(outcome["header"]["record_type"], "outcome")
        self.assertEqual(outcome["header"]["request_id"], "req-1")
        self.assertEqual(outcome["header"]["record_version"], fixed.RECORD_VERSION)
        for field, value in (
            ("thread", "thread-1"),
            ("round", 1),
            ("kind", "plain"),
            ("parent_session", "none"),
            ("asked_by", "none"),
            ("executor_name", "command"),
        ):
            self.assertEqual(outcome["header"][field], value, field)
        raw = outcome["receipt"]
        self.assertEqual(
            sorted(raw),
            sorted(
                [
                    "ending",
                    "execution",
                    "executor_driver",
                    "executor",
                ]
            ),
        )
        for group, names in fixed.RECEIPT_GROUPS.items():
            self.assertEqual(sorted(raw[group]), sorted(names), group)
            for name in names:
                held = raw[group][name]
                self.assertEqual(sorted(held), ["state", "value"], f"{group}.{name}")
                self.assertIn(held["state"], fixed.STATES, f"{group}.{name}")
        receipt = flat(raw)
        ending = receipt["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("ended_by_itself", "none", "none"),
        )
        saw = receipt["execution"]
        self.assertEqual(saw["exit_code"], 0)
        self.assertEqual(saw["signal"], "none")
        self.assertEqual(len(saw["input_hash"]), 64)
        self.assertEqual(receipt["executor_driver"]["executor_driver_name"], "command")
        self.assertEqual(saw["observed_runtime"], "not built")

    def test_what_is_a_stand_in_says_not_built_and_what_a_plain_command_cannot_say_is_cannot_tell(
        self,
    ):
        self.run_command(self.document())
        receipt = self.read("req-1.outcome.json")["receipt"]
        for group, field in [
            ("execution", "fingerprint_before"),
            ("execution", "fingerprint_after"),
            ("execution", "changed_nothing"),
            ("execution", "delivered"),
            ("execution", "teardown_failure"),
            ("execution", "peak_memory_bytes"),
            ("ending", "everything_stopped"),
            ("executor", "claim"),
        ]:
            self.assertEqual(receipt[group][field], {"state": "not built", "value": None}, field)
        # Both states in one receipt: the command driver cannot look at its tool's own commits.
        driver = receipt["executor_driver"]
        self.assertEqual(driver["tool_made_own_commits"], {"state": "cannot tell", "value": None})
        states = {held["state"] for group in receipt.values() for held in group.values()}
        self.assertIn("not built", states)
        self.assertIn("cannot tell", states)

    def test_the_exit_code_of_the_script_is_recorded_and_does_not_change_the_ending(self):
        done, lines = self.run_command(self.document(exit_code=7))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-1], "ended_by_itself")
        receipt = flat(self.read("req-1.outcome.json")["receipt"])
        self.assertEqual(receipt["execution"]["exit_code"], 7)
        self.assertEqual(receipt["ending"]["ending"], "ended_by_itself")

    def test_a_second_run_with_the_same_request_id_is_refused_and_leaves_the_first_records_untouched(
        self,
    ):
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
        self.assertEqual(
            lines, ["req-1", os.path.join(self.records, "req-1.outcome.json"), "could_not_start"]
        )
        ending = flat(self.read("req-1.outcome.json")["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "unknown_field", "input_check"),
        )
        self.assertIn("surprise", ending["reason_text"])
        self.assertFalse(os.path.exists(self.witness), "the script must not run")
        self.assertTrue(os.path.exists(os.path.join(self.records, "req-1.request.json")))

    def deep_nesting(self):
        return "[" * 1500 + "]" * 1500

    def this_python_cannot_write_the_nesting(self):
        """One cheap probe at the depth the tests use; no search over larger depths."""
        try:
            json.dumps({"a": json.loads(self.deep_nesting())}, indent=2)
        except RecursionError:
            return True
        return False

    def test_a_request_record_cut_short_by_a_file_size_limit_leaves_no_record_and_the_id_works_afterwards(
        self,
    ):
        import resource

        text = json.dumps(self.document())[:-1] + ', "note": "%s"}' % ("x" * 200000)

        def limit():
            return resource.setrlimit(resource.RLIMIT_FSIZE, (100000, 100000))

        path = os.path.join(self.root, "big.json")
        with open(path, "w") as f:
            f.write(text.replace('"note"', '"surprise"'))
        done = subprocess.run(
            [sys.executable, "-m", "shuttle", "run", path],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            preexec_fn=limit,
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(done.stdout.splitlines()[-1], "could_not_start")
        self.assertIn("NOT spent", done.stderr)
        self.assertEqual(
            os.listdir(self.records), [], "a record cut short must leave nothing behind"
        )
        path = os.path.join(self.root, "fixed.json")
        with open(path, "w") as f:
            json.dump(self.document(), f)
        done = subprocess.run(
            [sys.executable, "-m", "shuttle", "run", path],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            preexec_fn=limit,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            sorted(os.listdir(self.records)), ["req-1.outcome.json", "req-1.request.json"]
        )

    def test_a_document_whose_request_record_cannot_be_built_leaves_no_record_and_the_id_works_afterwards(
        self,
    ):
        if not self.this_python_cannot_write_the_nesting():
            self.skipTest("this Python writes this nesting; the next test covers what happens then")
        text = json.dumps(self.document())[:-1] + f', "surprise": {self.deep_nesting()}}}'
        done, lines = self.run_command(text)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines[-1], "could_not_start")
        self.assertEqual(len(done.stderr.strip().splitlines()), 1)
        self.assertIn("NOT spent", done.stderr)
        self.assertEqual(os.listdir(self.records), [], "neither record may exist")
        done, lines = self.run_command(self.document())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertEqual(self.read("req-1.request.json")["header"]["request_id"], "req-1")
        self.assertEqual(self.read("req-1.outcome.json")["header"]["request_id"], "req-1")

    def test_a_document_nested_deeper_than_old_pythons_could_write_gets_both_records_written_and_parseable(
        self,
    ):
        if self.this_python_cannot_write_the_nesting():
            self.skipTest(
                "this Python cannot write this nesting; the previous test covers what happens then"
            )
        text = json.dumps(self.document())[:-1] + f', "surprise": {self.deep_nesting()}}}'
        done, lines = self.run_command(text)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            lines[-1], "could_not_start"
        )  # the unknown field "surprise" is refused, and recorded
        request = self.read("req-1.request.json")
        self.assertEqual(request["input"]["surprise"], json.loads(self.deep_nesting()))
        self.assertEqual(
            flat(self.read("req-1.outcome.json")["receipt"])["ending"]["reason"],
            "unknown_field",
        )
        self.assertEqual(
            sorted(os.listdir(self.records)), ["req-1.outcome.json", "req-1.request.json"]
        )

    def test_two_commands_started_together_with_one_request_id_exactly_one_claims_it_and_its_records_are_whole(
        self,
    ):
        """Pins behaviour that held before the change too; a race cannot be made to fail on demand."""
        paths = []
        for n in range(2):
            path = os.path.join(self.root, f"in{n}.json")
            with open(path, "w") as f:
                json.dump(self.document(exit_code=n), f)
            paths.append(path)
        children = [
            subprocess.Popen(
                [sys.executable, "-m", "shuttle", "run", p],
                cwd=REPO,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for p in paths
        ]
        results = [(c.communicate(timeout=60), c.returncode) for c in children]
        codes = sorted(code for _, code in results)
        self.assertEqual(codes, [0, 1])
        loser = next(out_err for out_err, code in results if code == 1)
        self.assertIn("already used", loser[1])
        self.assertEqual(
            sorted(os.listdir(self.records)), ["req-1.outcome.json", "req-1.request.json"]
        )
        self.assertEqual(self.read("req-1.request.json")["header"]["request_id"], "req-1")
        self.assertEqual(
            flat(self.read("req-1.outcome.json")["receipt"])["ending"]["ending"],
            "ended_by_itself",
        )

    def test_a_tool_that_is_not_installed_could_not_start_at_the_executor_driver_check(self):
        doc = self.document()
        doc["executor"]["settings"]["command"] = os.path.join(self.root, "no-such-tool")
        done, lines = self.run_command(doc)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-1], "could_not_start")
        ending = flat(self.read("req-1.outcome.json")["receipt"])["ending"]
        self.assertEqual(
            (ending["reason"], ending["failed_step"]),
            ("tool_not_installed", "executor_driver_check"),
        )

    def spawn(self, doc, name="input.json", env=None):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            json.dump(doc, f)
        return subprocess.Popen(
            [sys.executable, "-m", "shuttle", "run", path],
            cwd=REPO,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def wait_for_file(self, path, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return
            time.sleep(0.05)
        self.fail(f"{path} never appeared")

    def assert_process_gone(self, pid):
        end = time.time() + 5
        while time.time() < end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail(f"process {pid} is still running")

    def sleeper(self):
        with open(self.script, "w") as f:
            f.write(
                "import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
            )

    def sleeping_document(self, **extra):
        self.sleeper()
        pid_file = os.path.join(self.root, "pid.txt")
        doc = self.document(**extra)
        doc["executor"]["settings"]["arguments"] = [self.script, pid_file]
        return doc, pid_file

    def test_a_terminate_sent_to_the_real_command_ends_the_script_and_still_writes_the_outcome_record(
        self,
    ):
        """The one real-process signal test; the other signals and the order of events are by value in test_waiting.py."""
        doc, pid_file = self.sleeping_document()
        proc = self.spawn(doc)
        self.wait_for_file(pid_file)
        with open(pid_file) as f:
            script_pid = int(f.read())
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, stderr)
        self.assertEqual(stdout.splitlines()[-1], "stopped_from_outside")
        ending = flat(self.read("req-1.outcome.json")["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("stopped_from_outside", "signal", "none"),
        )
        self.assert_process_gone(script_pid)

    def test_a_document_without_a_time_limit_is_refused_with_no_time_limit(self):
        doc = self.document()
        del doc["time_limit_seconds"]
        done, lines = self.run_command(doc)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-1], "could_not_start")
        ending = flat(self.read("req-1.outcome.json")["receipt"])["ending"]
        self.assertEqual(
            (ending["reason"], ending["failed_step"]), ("no_time_limit", "input_check")
        )

    def test_a_null_character_in_an_argument_is_a_failed_launch_and_the_record_is_still_written(
        self,
    ):
        doc = self.document()
        doc["executor"]["settings"]["arguments"].append("a\u0000b")
        done, lines = self.run_command(doc)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        self.assertEqual(lines[-1], "could_not_start")
        ending = flat(self.read("req-1.outcome.json")["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "launch_failed", "launch"),
        )

    def test_format_version_must_be_an_integer_that_is_not_a_boolean(self):
        for bad in (True, 1.0, "1", 2):
            with self.subTest(bad):
                for name in os.listdir(self.records):
                    os.remove(os.path.join(self.records, name))
                done, lines = self.run_command(self.document(format_version=bad))
                self.assertEqual(lines[-1], "could_not_start")
                ending = flat(self.read("req-1.outcome.json")["receipt"])["ending"]
                self.assertEqual(
                    (ending["reason"], ending["failed_step"]),
                    ("unknown_format_version", "input_check"),
                )
                self.assertFalse(os.path.exists(self.witness))

    def test_an_outcome_file_already_present_means_the_request_id_is_used(self):
        outcome = os.path.join(self.records, "req-1.outcome.json")
        with open(outcome, "w") as f:
            f.write("earlier run")
        done, lines = self.run_command(self.document())
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines, ["req-1", "could_not_start"])
        self.assertEqual(sorted(os.listdir(self.records)), ["req-1.outcome.json"])
        with open(outcome) as f:
            self.assertEqual(f.read(), "earlier run")
        self.assertFalse(os.path.exists(self.witness), "the script must not run")

    def test_a_records_location_that_cannot_be_used_prints_the_refusal_and_could_not_start(self):
        for name, place in (
            ("missing", os.path.join(self.root, "absent")),
            ("a file", self.script),
        ):
            with self.subTest(name):
                doc = self.document()
                doc["records_location"] = place
                done, lines = self.run_command(doc)
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(lines, ["req-1", "could_not_start"])
                self.assertEqual(len(done.stderr.strip().splitlines()), 1)
                self.assertIn("records_location", done.stderr)
                self.assertFalse(os.path.exists(self.witness))

    def environment_script(self):
        with open(self.script, "w") as f:
            f.write("import json, os, sys\njson.dump(sorted(os.environ), open(sys.argv[1], 'w'))\n")

    def test_the_executor_gets_path_and_the_named_variables_and_no_values_are_recorded(self):
        self.environment_script()
        env = dict(
            os.environ, SHUTTLE_TEST_NAMED="named-value-123", SHUTTLE_TEST_OTHER="other-value-456"
        )
        doc = self.document(environment=["SHUTTLE_TEST_NAMED"])
        doc["executor"]["settings"]["arguments"] = [self.script, self.witness]
        done, lines = self.run_command(doc, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(self.witness) as f:
            seen = json.load(f)
        self.assertIn("PATH", seen)
        self.assertIn("SHUTTLE_TEST_NAMED", seen)
        self.assertNotIn("SHUTTLE_TEST_OTHER", seen)
        self.assertNotIn("HOME", seen)
        for name in os.listdir(self.records):
            with open(os.path.join(self.records, name)) as f:
                text = f.read()
            self.assertNotIn("named-value-123", text)
            self.assertNotIn("other-value-456", text)

    def test_a_named_variable_the_caller_does_not_have_is_refused(self):
        env = {k: v for k, v in os.environ.items() if k != "SHUTTLE_TEST_ABSENT"}
        done, lines = self.run_command(self.document(environment=["SHUTTLE_TEST_ABSENT"]), env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-1], "could_not_start")
        ending = flat(self.read("req-1.outcome.json")["receipt"])["ending"]
        self.assertEqual(
            (ending["reason"], ending["failed_step"]), ("missing_setting", "executor_driver_check")
        )
        self.assertFalse(os.path.exists(self.witness))

    def test_a_document_too_broken_to_form_a_header_spends_no_id_and_writes_nothing(self):
        for name, text in [
            ("not json", "{nope"),
            ("no request id", json.dumps({"format_version": 1})),
        ]:
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
        if os.geteuid() == 0:
            self.skipTest("a read-only folder does not stop the superuser")
        with open(self.script, "w") as f:
            f.write(
                "import os, sys\nos.chmod(sys.argv[1], 0o500)\n"
            )  # the script makes the records folder read-only
        self.addCleanup(os.chmod, self.records, 0o700)
        doc = self.document()
        doc["executor"]["settings"]["arguments"] = [self.script, self.records]
        done, lines = self.run_command(doc)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines[0], "req-1")
        self.assertEqual(lines[-1], "ended_by_itself")
        printed = flat(json.loads("\n".join(lines[1:-1])))
        self.assertEqual(printed["ending"]["ending"], "ended_by_itself")
        self.assertIn("not written", done.stderr)
        self.assertEqual(os.listdir(self.records), ["req-1.request.json"])


if __name__ == "__main__":
    unittest.main()
