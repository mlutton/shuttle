"""By value, through the whole run on the simulated world: what each refusal leaves behind.

The pure checks are tested as tables in test_refusals.py; here each one is reached by one input
through `run`, and the run's order is looked at: gates before the executor, the request id used
once, kinds read from the shipped files, the check form touching nothing.
"""

import hashlib
import importlib
import io
import json
import os
import sys
import unittest

from shuttle.core import decisions as core
from shuttle.shell import check_form, kinds

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

CNS = "could_not_start"
GATE = {"name": "quota", "command": "gate", "arguments": [], "limit_seconds": 5}


def ran(world):
    """The programs that were run, in order, each as it was named inside its scope."""
    return [child.argv[0] for child in world.children]


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def ending_of(world):
    ending = flat(scenes.outcome(world)["receipt"])["ending"]
    return ending["ending"], ending["reason"], ending["failed_step"]


class RefusalCase(unittest.TestCase):
    def run_it(self, doc, prepare=None, gate=None):
        world = scenes.scene(doc)
        if gate is not None:
            world.program("gate", **gate)
        if prepare:
            prepare(world)
        code, lines, err = scenes.run_in(world)
        return world, code, lines, err

    def assertRefused(self, doc, reason, step, prepare=None, gate=None):
        world, code, lines, err = self.run_it(doc, prepare, gate)
        self.assertEqual(code, 0, err)
        self.assertEqual(ending_of(world), (CNS, reason, step))
        self.assertEqual(lines[-1], CNS)
        self.assertEqual(core.check_receipt(scenes.outcome(world)["receipt"]), [])
        self.assertNotIn("tool", ran(world), "the executor started")
        return world


class Refusals(RefusalCase):
    def test_each_input_check_is_reached_by_one_input_and_reads_back_with_its_step(self):
        d = scenes.document
        cases = (
            ("unknown_format_version", d(format_version=2)),
            ("unknown_field", d(surprise=1)),
            ("unknown_kind", d(kind="nonesuch")),
            ("instruction_hash_mismatch", d(instruction="do it", instruction_hash=sha("other"))),
            ("reference_missing", d(references=[ref("/refs/absent", "x")])),
            ("reference_hash_mismatch", d(references=[ref("/refs/runbook", "different")])),
            (
                "statement_location_occupied",
                d(kind="judge", statement_location="/out/statement.json"),
            ),
            (
                "statement_location_in_records",
                d(kind="judge", statement_location="/records/inj-1.outcome.json"),
            ),
            (
                "statement_location_in_records",
                d(kind="judge", statement_location="/records/other.txt"),
            ),
            ("missing_setting", d(kind="judge")),
            ("reach_not_valid", d(reach=["/opt"])),
            ("unknown_field", d(reach={"read": ["/opt"]})),
            ("visible_not_absolute", d(reach={"visible": ["opt"]})),
            ("visible_missing", d(reach={"visible": ["/opt/absent"]})),
            ("visible_not_a_folder", d(reach={"visible": ["/refs/runbook"]})),
            ("visible_overlaps_the_records", d(reach={"visible": ["/records"]})),
            ("no_time_limit", {k: v for k, v in d().items() if k != "time_limit_seconds"}),
            ("unknown_executor", {**d(), "executor": {"name": "nonesuch", "settings": {}}}),
            (
                "unknown_setting",
                {
                    **d(),
                    "executor": {
                        "name": "command",
                        "settings": {"command": "tool", "arguments": [], "x": 1},
                    },
                },
            ),
            ("tool_not_installed", d(command="absent-tool")),
        )
        for reason, doc in cases:
            with self.subTest(reason):
                step = "executor_driver_check" if reason == "tool_not_installed" else "input_check"
                self.assertRefused(doc, reason, step, prepare=put_reference_and_statement)

    def test_a_credential_like_value_is_refused_before_the_claim_and_leaves_nothing_behind(self):
        value = "madeup0123456789madeup0123456789xyz"
        doc = scenes.document(environment=[f"TOKEN={value}"])
        world, code, lines, err = self.run_it(doc)
        self.assertEqual((code, lines), (1, ["none"]))
        self.assertIn("credential", err)
        self.assertNotIn(value, err)
        self.assertEqual(world.names_in(doc["records_location"]), [])
        self.assertEqual(world.started, [])

    def test_a_matching_instruction_hash_and_reference_are_accepted(self):
        doc = scenes.document(
            instruction="do it",
            instruction_hash=sha("do it"),
            references=[ref("/refs/runbook", "contents")],
        )
        world, code, _, err = self.run_it(doc, put_reference_and_statement)
        self.assertEqual(code, 0, err)
        self.assertEqual(ending_of(world), ("ended_by_itself", "none", "none"))

    def test_the_problem_line_names_what_was_found(self):
        world = self.assertRefused(scenes.document(kind="nonesuch"), "unknown_kind", "input_check")
        text = flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
        self.assertIn("nonesuch", text)

    def test_the_kinds_come_from_the_two_shipped_files_and_fail_closed_when_they_are_gone(self):
        world = scenes.scene()
        self.assertEqual(kinds.read_kinds(world.operations)["plain"], False)
        self.assertEqual(kinds.read_kinds(world.operations)["judge"], True)
        del world.files[kinds.WITHOUT_STATEMENT]
        code, lines, _ = scenes.run_in(world)
        self.assertEqual(code, 0)
        self.assertEqual(ending_of(world), (CNS, "unknown_kind", "input_check"))

    def test_a_kind_that_expects_a_statement_runs_when_its_location_is_free(self):
        doc = scenes.document(kind="judge", statement_location="/out/statement.json")
        world, code, _, err = self.run_it(doc)
        self.assertEqual(code, 0, err)
        self.assertEqual(ending_of(world)[0], "ended_by_itself")


def ref(path, text):
    return {
        "name": "runbook",
        "path": path,
        "hash": sha(text),
        "size": len(text),
        "hash_source": "caller",
    }


def put_reference_and_statement(world):
    world.put_file("/refs/runbook", "contents")
    world.put_file("/out/statement.json", "taken")


class Gates(RefusalCase):
    def test_a_gate_that_says_no_refuses_with_its_name_and_answer_and_the_executor_never_starts(
        self,
    ):
        doc = scenes.document(gates=[GATE])
        world = self.assertRefused(doc, "gate_said_no", "gates", gate={"exit_code": 1})
        text = flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
        self.assertIn("quota", text)
        self.assertIn("no", text)

    def test_a_gate_that_fails_refuses_with_its_name_and_answer(self):
        for label, program in (
            ("another exit code", {"exit_code": 3}),
            ("passes its limit", {"times_out": True}),
            (
                "passes its limit and ignores being asked to end",
                {"times_out": True, "survives_stop": True},
            ),
        ):
            with self.subTest(label):
                doc = scenes.document(gates=[dict(GATE, limit_seconds=1)])
                world = self.assertRefused(doc, "gate_failed", "gates", gate=program)
                self.assertIn(
                    "failed", flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
                )
                self.assertTrue(world.every_child_has_ended())

    def test_a_gate_that_cannot_start_fails(self):
        doc = scenes.document(gates=[dict(GATE, command="no-such-gate")])
        self.assertRefused(doc, "gate_failed", "gates")

    def test_gates_run_in_order_before_the_executor_and_all_say_yes(self):
        doc = scenes.document(gates=[GATE, dict(GATE, name="disk")])
        world, code, _, err = self.run_it(doc, gate={"exit_code": 0})
        self.assertEqual(code, 0, err)
        self.assertEqual(ran(world), ["gate", "gate", "tool"])
        self.assertEqual(ending_of(world)[0], "ended_by_itself")

    def test_the_first_gate_that_does_not_say_yes_stops_the_rest(self):
        doc = scenes.document(gates=[GATE, dict(GATE, name="disk")])
        world, _, _, _ = self.run_it(doc, gate={"exit_code": 1})
        self.assertEqual(len(world.started), 1)

    def test_a_gate_is_given_the_path_and_nothing_else(self):
        doc = scenes.document(gates=[GATE])
        world, _, _, _ = self.run_it(doc, gate={})
        self.assertEqual(list(world.started[0][1]), ["PATH"])

    def test_a_failure_in_the_operation_that_starts_a_gate_is_a_failed_gate(self):
        world = scenes.scene(scenes.document(gates=[GATE]))
        world.program("gate")
        world.will_raise("processes.start", OSError("injected"))
        scenes.run_in(world)
        self.assertEqual(ending_of(world), (CNS, "gate_failed", "gates"))


class TheRequestIdIsUsedOnce(unittest.TestCase):
    def test_an_id_used_by_a_finished_run_is_refused_and_the_earlier_records_are_untouched(self):
        world = scenes.scene()
        scenes.run_in(world)
        before = {n: bytes(b) for n, b in world.files.items() if n.startswith(scenes.RECORDS)}
        code, lines, err = scenes.run_in(world)
        self.assertNotEqual(code, 0)
        self.assertEqual(lines, ["inj-1", CNS])
        self.assertIn("already used", err)
        self.assertEqual(
            before, {n: bytes(b) for n, b in world.files.items() if n.startswith(scenes.RECORDS)}
        )

    def test_an_id_used_by_a_run_that_never_finished_is_refused_too(self):
        world = scenes.scene()
        world.put_file(f"{scenes.RECORDS}/inj-1.request.json", "{}")
        code, lines, _ = scenes.run_in(world)
        self.assertNotEqual(code, 0)
        self.assertEqual(lines, ["inj-1", CNS])
        self.assertEqual(world.names_in(scenes.RECORDS), ["inj-1.request.json"])
        self.assertEqual(world.started, [])


class AnAbsentRequestIdIsGenerated(unittest.TestCase):
    def test_a_run_prints_the_generated_id_first_and_writes_the_records_under_it(self):
        doc = {k: v for k, v in scenes.document().items() if k != "request_id"}
        world = scenes.scene(doc)
        code, lines, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        self.assertRegex(lines[0], "^[0-9a-f]{32}$")
        self.assertEqual(
            world.names_in(scenes.RECORDS),
            sorted([f"{lines[0]}.request.json", f"{lines[0]}.outcome.json"]),
        )


class TheCheckForm(unittest.TestCase):
    def check(self, world):
        out, err = io.StringIO(), io.StringIO()
        code = check_form.check(scenes.DOCUMENT, out, err, world.operations)
        return code, out.getvalue().splitlines(), err.getvalue()

    def assertTouchedNothing(self, world, before):
        self.assertEqual(world.counts.get("files.write_new", 0), 0)
        self.assertEqual(world.counts.get("files.link", 0), 0)
        self.assertEqual(before, dict(world.files))
        self.assertTrue(world.every_child_has_ended())

    def test_a_passing_check_prints_the_id_and_says_passing_is_not_a_promise_and_changes_nothing(
        self,
    ):
        world = scenes.scene()
        before = {n: bytes(b) for n, b in world.files.items()}
        code, lines, err = self.check(world)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(lines[0], "inj-1")
        self.assertEqual(lines[1], "check: no refusal found")
        self.assertIn("not a promise", lines[-1])
        self.assertEqual(world.started, [])
        self.assertEqual(before, {n: bytes(b) for n, b in world.files.items()})
        self.assertTouchedNothing(world, world.files)

    def test_a_refusal_is_printed_in_the_shape_of_an_outcome_record(self):
        world = scenes.scene(scenes.document(kind="nonesuch"))
        code, lines, _ = self.check(world)
        self.assertEqual(code, 0)
        record = json.loads(lines[1])
        self.assertEqual(sorted(record), ["header", "receipt"])
        self.assertEqual(record["header"]["record_type"], "outcome")
        self.assertEqual(core.check_receipt(record["receipt"]), [])
        self.assertEqual(
            tuple(
                flat(record["receipt"])["ending"][k] for k in ("ending", "reason", "failed_step")
            ),
            (CNS, "unknown_kind", "input_check"),
        )
        self.assertEqual(lines[2], "check: refused: unknown_kind")
        self.assertIn("not a promise", lines[-1])
        self.assertNotIn("inj-1.request.json", world.names_in(scenes.RECORDS))

    def with_folders(self, doc, home="/home/me"):
        world = scenes.scene(doc)
        world.account_home, world.runtime = home, "/run/user/1000"
        for folder in (
            "/run",
            "/run/user",
            "/run/user/1000",
            "/home",
            home,
            f"{home}/tools",
            "/tmp",
        ):
            world.make_folder(folder)
        return world

    def test_a_listed_folder_that_is_or_holds_the_runtime_folder_the_home_folder_or_tmp_is_refused(
        self,
    ):
        for reason, path in (
            ("visible_overlaps_the_runtime_folder", "/run"),
            ("visible_overlaps_the_home_folder", "/home"),
            ("visible_overlaps_the_home_folder", "/home/me"),
            ("visible_overlaps_the_box", "/tmp"),
        ):
            with self.subTest(reason, path=path):
                world = self.with_folders(scenes.document(reach={"visible": [path]}))
                _, lines, _ = self.check(world)
                self.assertEqual(lines[-2], f"check: refused: {reason}")

    def test_the_runtime_and_home_refusals_hold_whatever_the_callers_environment_says(self):
        misnamed = (
            ("unset", {}),
            ("naming other folders", {"HOME": "/elsewhere", "XDG_RUNTIME_DIR": "/elsewhere"}),
            ("empty", {"HOME": "", "XDG_RUNTIME_DIR": ""}),
        )
        for label, variables in misnamed:
            for reason, path in (
                ("visible_overlaps_the_runtime_folder", "/run/user/1000"),
                ("visible_overlaps_the_home_folder", "/home/me"),
            ):
                with self.subTest(label, reason=reason):
                    world = self.with_folders(scenes.document(reach={"visible": [path]}))
                    world.variables.clear()
                    world.variables.update(variables)
                    world.make_folder("/elsewhere")
                    _, lines, _ = self.check(world)
                    self.assertEqual(lines[-2], f"check: refused: {reason}")

    def test_an_account_with_no_home_folder_refuses_nothing_for_it(self):
        world = self.with_folders(scenes.document(reach={"visible": ["/home/me"]}))
        world.account_home = None
        _, lines, _ = self.check(world)
        self.assertEqual(lines[-2], "check: no refusal found")

    def test_a_folder_inside_the_home_folder_is_accepted(self):
        world = self.with_folders(scenes.document(reach={"visible": ["/home/me/tools"]}))
        _, lines, _ = self.check(world)
        self.assertEqual(lines[-2], "check: no refusal found")

    def test_every_check_is_run_and_every_problem_is_listed(self):
        doc = scenes.document(
            kind="nonesuch", command="absent-tool", reach={"visible": ["nowhere"]}
        )
        world = scenes.scene(doc)
        _, lines, _ = self.check(world)
        text = flat(json.loads(lines[1])["receipt"])["ending"]["reason_text"]
        for word in ("nonesuch", "absent-tool", "nowhere"):
            self.assertIn(word, text)

    def test_gates_are_asked_and_the_executor_is_not_started(self):
        world = scenes.scene(scenes.document(gates=[GATE]))
        world.program("gate", exit_code=1)
        _, lines, _ = self.check(world)
        self.assertEqual(ran(world), ["gate"])
        self.assertEqual(lines[2], "check: refused: gate_said_no")

    def test_a_used_request_id_is_reported_and_nothing_is_claimed(self):
        world = scenes.scene()
        scenes.run_in(world)
        before = {n: bytes(b) for n, b in world.files.items()}
        _, lines, _ = self.check(world)
        self.assertEqual(lines[2], "check: refused: request_id_used")
        self.assertEqual(before, {n: bytes(b) for n, b in world.files.items()})

    def test_an_absent_request_id_is_generated_and_printed_and_spends_nothing(self):
        doc = {k: v for k, v in scenes.document().items() if k != "request_id"}
        world = scenes.scene(doc)
        _, lines, _ = self.check(world)
        self.assertRegex(lines[0], "^[0-9a-f]{32}$")
        self.assertEqual(world.names_in(scenes.RECORDS), [])

    def test_a_document_too_broken_to_form_a_header_is_one_line_and_exit_non_zero(self):
        world = scenes.scene({"round": 1})
        code, lines, err = self.check(world)
        self.assertNotEqual(code, 0)
        self.assertEqual(lines, ["none"])
        self.assertEqual(len(err.strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
