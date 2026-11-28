"""The command seam: refusals and the check form, through the real command as a child process.

The pure checks are tables in tests/by_value/test_refusals.py. Here each reaches the real command
by one input, and the real files show what was and was not written.
"""

import hashlib
import importlib
import itertools
import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_place = importlib.import_module("rehearsal.real_place")
real_run = importlib.import_module("rehearsal.real_run")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WRITES_WITNESS = "import sys\nopen(sys.argv[1], 'w').write('started')\n"
MADE_UP_CREDENTIAL = (
    "madeup0123456789madeup0123456789xyz"  # no vendor prefix; long enough to look like a token
)
GATE_ANSWERS = "import sys\nsys.exit(int(sys.argv[1]))\n"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class RealCommand(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.temporary = os.path.join(self.root, "temporary")
        os.mkdir(self.temporary)
        self.records = os.path.join(self.root, "records")
        os.mkdir(self.records)
        self.place = os.path.join(self.root, "place")
        real_place.make_checkout(self.place)
        # The executor writes its witness in the place and reads its script from a folder listed
        # as visible (see tests/rehearsal/real_run.py).
        self.witness = os.path.join(self.place, "witness.txt")
        self.support = os.path.join(self.root, "support")
        os.mkdir(self.support)
        self.script = self.write("script.py", WRITES_WITNESS, self.support)
        self.gate_script = self.write("gate.py", GATE_ANSWERS)

    def write(self, name, text, folder=None):
        path = os.path.join(folder or self.root, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def document(self, **extra):
        doc = {
            "format_version": 1,
            "request_id": "req-1",
            "records_location": self.records,
            "place": self.place,
            "thread": "t",
            "round": 1,
            "kind": "plain",
            "time_limit_seconds": 30,
            "reach": {"visible": [self.support, *real_run.INTERPRETER_FOLDERS]},
            "executor": {
                "name": "command",
                "settings": {
                    "command": real_run.INTERPRETER,
                    "arguments": [self.script, self.witness],
                },
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

    def with_own_temporary(self, env=None):
        """`env` (the test's own environment when None) with a temporary folder of this test's
        own, so no run makes or removes anything in the machine's."""
        return {**(os.environ if env is None else env), "TMPDIR": self.temporary}

    def command(self, form, doc, name="input.json", env=None):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            json.dump(doc, f)
        done = subprocess.run(
            [sys.executable, "-m", "shuttle", form, path],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
            env=self.with_own_temporary(env),
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
            (
                "reference_missing",  # a folder: it has no hash yet, so it is refused as missing
                self.document(references=[{**ref(self.root, "x"), "path": self.root}]),
            ),
            (
                "unknown_field",  # a kind that expects no statement, given a location
                self.document(statement_location=os.path.join(self.root, "free")),
            ),
            ("reach_not_valid", self.document(reach=["x"])),
            ("visible_not_absolute", self.document(reach={"visible": ["x"]})),
            (
                "visible_missing",
                self.document(reach={"visible": [os.path.join(self.root, "absent")]}),
            ),
            ("visible_not_a_folder", self.document(reach={"visible": [runbook]})),
            ("visible_overlaps_the_records", self.document(reach={"visible": [self.records]})),
            ("visible_overlaps_the_records", self.document(reach={"visible": [self.root]})),
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

    def reach_cases(self):
        runbook = self.write("runbook.md", "contents")
        return (
            ("reach_not_valid", {"reach": ["x"]}),
            ("unknown_field", {"reach": {"read": [self.support]}}),
            ("visible_not_absolute", {"reach": {"visible": ["x"]}}),
            ("visible_missing", {"reach": {"visible": [os.path.join(self.root, "absent")]}}),
            ("visible_not_a_folder", {"reach": {"visible": [runbook]}}),
            ("visible_overlaps_the_records", {"reach": {"visible": [self.records]}}),
            ("visible_overlaps_the_records", {"reach": {"visible": [self.root]}}),
        )

    def test_the_check_form_refuses_a_reach_as_a_run_does_with_the_same_reason_and_line(self):
        for reason, extra in self.reach_cases():
            with self.subTest(reason, **{k: str(v) for k, v in extra.items()}):
                for name in os.listdir(self.records):
                    os.unlink(os.path.join(self.records, name))
                checked, check_lines = self.command("check", self.document(**extra))
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertEqual(check_lines[-2], f"check: refused: {reason}")
                self.assertEqual(os.listdir(self.records), [])  # the check wrote nothing
                ran, _ = self.command("run", self.document(**extra))
                line = self.outcome()["receipt"]["ending"]["reason_text"]["value"]
                self.assertEqual(
                    self.ending(self.outcome()), ("could_not_start", reason, "input_check")
                )
                printed = json.loads(check_lines[1])["receipt"]["ending"]["reason_text"]["value"]
                self.assertEqual(printed, line)  # the check prints the record a run would write
                self.assertFalse(os.path.exists(self.witness))

    def test_the_box_s_own_folders_the_runtime_folder_and_the_home_folder_are_refused_by_both(self):
        """The account's real folders, whatever the caller's environment names."""
        home = pwd.getpwuid(os.getuid()).pw_dir
        runtime = f"/run/user/{os.getuid()}"
        if not (os.path.isdir(home) and os.path.isdir(runtime)):
            self.skipTest("this account has no home folder or runtime folder to list")
        if os.path.realpath(self.records).startswith(os.path.realpath(home) + os.sep):
            self.skipTest(
                "the test's records are under the home folder, which would be named first"
            )
        misnamed = os.path.join(self.root, "a-misnamed-folder")
        os.mkdir(misnamed)
        environments = (
            ("naming other folders", {**os.environ, "HOME": misnamed, "XDG_RUNTIME_DIR": misnamed}),
            (
                "unset",
                {k: v for k, v in os.environ.items() if k not in ("HOME", "XDG_RUNTIME_DIR")},
            ),
        )
        cases = (
            ("visible_overlaps_the_box", "/proc"),
            ("visible_overlaps_the_runtime_folder", runtime),
            ("visible_overlaps_the_home_folder", home),
        )
        for (label, env), (reason, path) in itertools.product(environments, cases):
            with self.subTest(label, reason=reason):
                for name in os.listdir(self.records):
                    os.unlink(os.path.join(self.records, name))
                doc = self.document(reach={"visible": [path]})
                checked, check_lines = self.command("check", doc, env=env)
                self.assertEqual(check_lines[-2], f"check: refused: {reason}")
                self.command("run", doc, env=env)
                self.assertEqual(
                    self.ending(self.outcome()), ("could_not_start", reason, "input_check")
                )
                self.assertFalse(os.path.exists(self.witness))

    def test_a_reach_listing_folders_that_are_there_is_accepted_by_the_check_and_the_run(self):
        doc = self.document()
        doc["reach"]["visible"].append(self.root + "/support")
        checked, check_lines = self.command("check", doc)
        self.assertEqual(check_lines[-2], "check: no refusal found")
        done, lines = self.command("run", doc)
        self.assertEqual(lines[-1], "ended_by_itself")

    def a_program_in(self, folder):
        os.makedirs(folder, exist_ok=True)
        path = self.write("the-program", f"#!{real_run.INTERPRETER}\n{WRITES_WITNESS}", folder)
        os.chmod(path, 0o755)
        return path

    def document_naming(self, program):
        doc = self.document()
        doc["executor"]["settings"] = {"command": program, "arguments": [self.witness]}
        return doc

    def refused_by_both(self, doc, folder):
        for name in os.listdir(self.records):
            os.unlink(os.path.join(self.records, name))
        checked, check_lines = self.command("check", doc)
        self.assertEqual(check_lines[-2], "check: refused: program_not_visible")
        self.assertEqual(os.listdir(self.records), [])
        self.command("run", doc)
        self.assertEqual(
            self.ending(self.outcome()),
            ("could_not_start", "program_not_visible", "executor_driver_check"),
        )
        line = self.outcome()["receipt"]["ending"]["reason_text"]["value"]
        self.assertIn(repr(folder), line)
        self.assertIn("reach.visible", line)
        self.assertEqual(
            json.loads(check_lines[1])["receipt"]["ending"]["reason_text"]["value"], line
        )
        self.assertFalse(os.path.exists(self.witness))

    def test_a_program_in_a_hidden_folder_is_refused_by_the_check_and_the_run_naming_the_folder(
        self,
    ):
        hidden = os.path.join(self.root, "hidden")
        self.refused_by_both(self.document_naming(self.a_program_in(hidden)), hidden)

    def test_a_link_in_a_shown_folder_to_a_hidden_file_is_refused_naming_the_folder_of_the_file(
        self,
    ):
        hidden = os.path.join(self.root, "hidden")
        real = self.a_program_in(hidden)
        link = os.path.join(self.support, "linked-program")
        os.symlink(real, link)
        self.refused_by_both(self.document_naming(link), os.path.realpath(hidden))

    def test_a_link_in_a_hidden_folder_is_refused_even_to_a_shown_file(self):
        shown = self.a_program_in(self.support)
        hidden = os.path.join(self.root, "hidden")
        os.mkdir(hidden)
        link = os.path.join(hidden, "linked-program")
        os.symlink(shown, link)
        self.refused_by_both(self.document_naming(link), os.path.realpath(hidden))

    def program_behind_a_link(self):
        installed = os.path.join(self.root, "inst", "1.2", "bin")
        real = self.a_program_in(installed)
        os.symlink("1.2", os.path.join(self.root, "inst", "latest"))
        through = os.path.join(self.root, "inst", "latest", "bin")
        env = {**os.environ, "PATH": through + os.pathsep + os.environ["PATH"]}
        doc = self.document_naming("the-program")
        return doc, env, through, real, installed

    def test_a_program_found_through_a_link_in_its_folder_is_refused_and_the_line_works_listed(
        self,
    ):
        doc, env, through, real, _ = self.program_behind_a_link()
        doc["reach"]["visible"].append(through)  # resolves to the folder the box does show
        checked, check_lines = self.command("check", doc, env=env)
        self.assertEqual(check_lines[-2], "check: refused: program_not_visible")
        line = json.loads(check_lines[1])["receipt"]["ending"]["reason_text"]["value"]
        self.assertNotIn("list '", line)  # nothing to list: the listing is there
        named = re.search(r"name '([^']*)' as the command", line)
        self.assertEqual(named.group(1), real)
        doc["executor"]["settings"]["command"] = named.group(1)  # what the line says to do
        checked, check_lines = self.command("check", doc, env=env)
        self.assertEqual(check_lines[-2], "check: no refusal found")
        done, lines = self.command("run", doc, env=env)
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertTrue(os.path.exists(self.witness))

    def test_a_program_found_through_a_link_in_its_folder_is_refused_and_the_line_works_unlisted(
        self,
    ):
        doc, env, _, real, installed = self.program_behind_a_link()
        checked, check_lines = self.command("check", doc, env=env)
        line = json.loads(check_lines[1])["receipt"]["ending"]["reason_text"]["value"]
        self.assertEqual(check_lines[-2], "check: refused: program_not_visible")
        named = re.search(r"name '([^']*)' as the command", line)
        folder = re.search(r"list '([^']*)' under reach.visible", line)
        self.assertEqual((named.group(1), folder.group(1)), (real, installed))
        doc["executor"]["settings"]["command"] = named.group(1)
        doc["reach"]["visible"].append(folder.group(1))
        checked, check_lines = self.command("check", doc, env=env)
        self.assertEqual(check_lines[-2], "check: no refusal found")
        done, lines = self.command("run", doc, env=env)
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertTrue(os.path.exists(self.witness))

    def test_a_command_with_two_leading_slashes_is_the_same_file_as_with_one(self):
        doc = self.document()
        doc["executor"]["settings"] = {
            "command": "//bin/sh",
            "arguments": ["-c", f'echo ran > "{self.witness}"'],
        }
        checked, check_lines = self.command("check", doc)
        self.assertEqual(check_lines[-2], "check: no refusal found")
        done, lines = self.command("run", doc)
        self.assertEqual(lines[-1], "ended_by_itself")
        self.assertTrue(os.path.exists(self.witness))

    def test_a_program_in_a_folder_the_listing_refuses_is_told_to_move_not_to_list(self):
        folder = os.path.join(
            self.records, "bin"
        )  # the records folder is hidden whatever is listed
        doc = self.document_naming(self.a_program_in(folder))
        checked, check_lines = self.command("check", doc)
        line = json.loads(check_lines[1])["receipt"]["ending"]["reason_text"]["value"]
        self.assertEqual(check_lines[-2], "check: refused: program_not_visible")
        self.assertIn("cannot be listed", line)
        self.assertNotIn("list '", line)
        doc["reach"]["visible"].append(folder)  # what listing it would get, for the record
        checked, check_lines = self.command("check", doc)
        self.assertEqual(check_lines[-2], "check: refused: visible_overlaps_the_records")

    def test_a_program_the_box_shows_is_accepted_by_the_check(self):
        program = self.a_program_in(self.support)  # a visible folder
        _, check_lines = self.command("check", self.document_naming(program))
        self.assertEqual(check_lines[-2], "check: no refusal found")
        program = self.a_program_in(os.path.join(self.root, "reference-folder"))  # a reference
        doc = self.document_naming(program)
        with open(program) as f:
            doc["references"] = [ref(program, f.read())]
        _, check_lines = self.command("check", doc)
        self.assertEqual(check_lines[-2], "check: no refusal found")

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

    def test_a_credential_like_environment_value_is_refused_before_the_id_is_claimed_and_kept_nowhere(
        self,
    ):
        value = MADE_UP_CREDENTIAL
        doc = self.document(environment=[f"TOKEN={value}"])
        done, lines = self.command("run", doc)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(lines, ["none"])
        self.assertIn("credential", done.stderr)
        self.assertEqual(os.listdir(self.records), [])  # no request record, no outcome record
        for stream in (done.stdout, done.stderr):
            self.assertNotIn(value, stream)
        for folder, _, names in os.walk(self.records):
            for name in names:
                with open(os.path.join(folder, name)) as f:
                    self.assertNotIn(value, f.read())
        self.assertFalse(os.path.exists(self.witness))
        fixed, lines = self.command("run", self.document())  # the id was not spent
        self.assertEqual(lines[-1], "ended_by_itself")

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
            sorted(
                [
                    f"{lines[0]}.request.json",
                    f"{lines[0]}.outcome.json",
                    f"{lines[0]}.standard-output.kept",
                    f"{lines[0]}.standard-error.kept",
                ]
            ),
        )


class CheckForm(RealCommand):
    def test_a_passing_check_launches_no_executor_writes_nothing_and_says_it_is_not_a_promise(self):
        done, lines = self.command("check", self.document(gates=[self.gate(0)]))
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(lines[0], "req-1")
        self.assertEqual(lines[1], "check: no refusal found")
        self.assertIn("not a promise", lines[-1])
        self.assertEqual(os.listdir(self.records), [])
        self.assertFalse(os.path.exists(self.witness))

    def test_the_check_still_reports_a_credential_like_value_and_prints_no_value(self):
        done, lines = self.command(
            "check", self.document(environment=[f"TOKEN={MADE_UP_CREDENTIAL}"])
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(lines[-2], "check: refused: credential_like_value")
        self.assertNotIn(MADE_UP_CREDENTIAL, done.stdout + done.stderr)
        self.assertEqual(os.listdir(self.records), [])

    def test_a_refusal_is_the_shape_of_an_outcome_record_and_the_id_stays_free(self):
        done, lines = self.command("check", self.document(kind="nonesuch"))
        self.assertEqual(done.returncode, 0, done.stderr)
        record = json.loads(lines[1])
        self.assertEqual(sorted(record), ["header", "receipt"])
        self.assertEqual(self.ending(record), ("could_not_start", "unknown_kind", "input_check"))
        self.assertEqual(os.listdir(self.records), [])
        done, lines = self.command("run", self.document())  # the id was not spent
        self.assertEqual(lines[-1], "ended_by_itself")

    def test_the_check_and_the_run_give_the_same_verdict_on_a_records_location_that_cannot_take_a_record(
        self,
    ):
        a_file = self.write("not-a-folder", "x")
        read_only = os.path.join(self.root, "read-only")
        os.mkdir(read_only)
        os.chmod(read_only, 0o500)
        self.addCleanup(os.chmod, read_only, 0o700)
        cases = [("absent", os.path.join(self.root, "absent")), ("a file", a_file)]
        if not os.access(read_only, os.W_OK):  # a superuser can write anywhere
            cases.append(("read-only", read_only))
        for label, location in cases:
            with self.subTest(label):
                doc = self.document(records_location=location)
                checked, check_lines = self.command("check", doc)
                ran, run_lines = self.command("run", doc)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertEqual(check_lines[-2], "check: refused: records_location_unusable")
                self.assertEqual(
                    self.ending(json.loads(check_lines[1])),
                    ("could_not_start", "records_location_unusable", "id_claim"),
                )
                self.assertNotEqual(ran.returncode, 0)  # the run's own words for the same refusal
                self.assertEqual(run_lines, ["req-1", "could_not_start"])
                problem = json.loads(check_lines[1])["receipt"]["ending"]["reason_text"]["value"]
                self.assertIn(problem.split(" (")[0], ran.stderr)
                self.assertFalse(os.path.exists(self.witness))

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
