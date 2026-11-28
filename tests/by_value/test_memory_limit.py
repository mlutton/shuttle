"""By value: the memory cap, from the input document to the ending.

The document's optional `memory_limit_bytes` is checked as a number, then against the machine
(a trial scope, `try_memory_cap`), then goes to the scope as `MemoryMax` with no swap; the ending
`memory_limit` is decided only from the scope's own result on a scope that was given a cap. The
real runs are tests/boundary/test_memory_limit.py.
"""

import copy
import importlib
import io
import os
import sys
import unittest

from shuttle.core import boundary, fixed, refusals
from shuttle.core import decisions as core
from shuttle.shell import check_form

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

CAP = 64 * 1024 * 1024
CNS = "could_not_start"
GOOD = {
    "format_version": 1,
    "request_id": "req-1",
    "records_location": "/some/records",
    "thread": "t-1",
    "round": 2,
    "kind": "plain",
    "time_limit_seconds": 30,
    "executor": {"name": "command", "settings": {"command": "python3", "arguments": []}},
}
REACH: boundary.Reach = {
    "place": "/work/place",
    "area": "/scratch/area",
    "home": "/scratch/area/home",
    "tmp": "/scratch/area/tmp",
    "references": [],
    "visible": [],
    "git_folders": [],
    "place_writable": True,
    "resolver": None,
    "records": "/rec",
}


def ending_of(world):
    ending = flat(scenes.outcome(world)["receipt"])["ending"]
    return ending["ending"], ending["reason"], ending["failed_step"]


def checked(world):
    out, err = io.StringIO(), io.StringIO()
    code = check_form.check(scenes.DOCUMENT, out, err, world.operations)
    return code, out.getvalue().splitlines(), err.getvalue()


class TheCapIsAPositiveWholeNumberOfBytes(unittest.TestCase):
    def test_what_is_usable_and_what_is_not(self):
        for value, usable in (
            (1, True),
            (CAP, True),
            (2**62, True),
            (2**62 + 1, False),  # the scope reads 2**63 - 1 and more as no cap at all
            (2**63 - 1, False),
            (2**64 - 1, False),
            (10**400, False),
            (0, False),
            (-1, False),
            (True, False),
            (False, False),
            (64.0, False),
            (1.5, False),
            (float("inf"), False),
            (float("nan"), False),
            ("64", False),
            ("64M", False),
            (None, False),
            ([64], False),
            ({}, False),
        ):
            with self.subTest(value=value):
                self.assertEqual(boundary.usable_memory_limit(value), usable)

    def test_the_document_check_accepts_a_cap_and_a_document_without_one(self):
        for doc in (GOOD, {**GOOD, "memory_limit_bytes": CAP}, {**GOOD, "memory_limit_bytes": 1}):
            with self.subTest(doc.get("memory_limit_bytes")):
                self.assertIsNone(core.validate_document(doc)["refusal"])

    def test_a_cap_that_is_not_one_is_refused_as_a_missing_setting_with_a_line_that_names_it(self):
        for value in (0, -5, True, 64.0, "64", None, 2**62 + 1, 10**400, float("inf"), [1]):
            with self.subTest(value=repr(value)[:20]):
                got = core.validate_document({**copy.deepcopy(GOOD), "memory_limit_bytes": value})
                self.assertEqual(
                    got["refusal"], {"reason": "missing_setting", "step": "input_check"}
                )
                self.assertIn("memory_limit_bytes must be a whole number of bytes", got["problem"])
                self.assertIn("left out to run without a memory cap", got["problem"])

    def test_the_cap_is_a_field_the_document_takes(self):
        self.assertIn("memory_limit_bytes", core._DOCUMENT_FIELDS)


class ACapOnAMachineThatCannotHoldItIsRefused(unittest.TestCase):
    def test_the_check_by_value(self):
        for named, can, expected in (
            (False, False, None),  # no cap named: nothing to refuse, whatever the machine
            (False, True, None),
            (True, True, None),
            (True, False, "memory_cap_unavailable"),
        ):
            with self.subTest(named=named, machine_can_cap=can):
                got = refusals.check_memory_cap(named, can)
                self.assertEqual(got and got["reason"], expected)
                self.assertEqual(got and got["step"], "input_check" if expected else None)

    def test_the_line_says_the_machine_cannot_cap_a_user_scope_and_that_leaving_it_out_runs(self):
        got = refusals.check_memory_cap(True, False)
        assert got is not None
        self.assertIn("this machine cannot cap memory for a user scope", got["problem"])
        self.assertIn(
            "leave memory_limit_bytes out of the document to run without a memory cap",
            got["problem"],
        )
        self.assertIn(got["reason"], fixed.REASONS_BY_ENDING[CNS])

    def test_what_the_trial_must_read_back_for_the_machine_to_count_as_able(self):
        held = (str(boundary.TRIAL_MEMORY_BYTES), str(boundary.SWAP_WITH_A_CAP_BYTES))
        for trial, able in (
            (held, True),
            (None, False),  # the trial could not be made or read
            (("max", "max"), False),  # the files are there and nothing caps
            ((held[0], "max"), False),  # memory capped, swap not: going over only slows it
            (("max", held[1]), False),
            (("1", "0"), False),
            (("", ""), False),
        ):
            with self.subTest(trial=trial):
                self.assertEqual(boundary.memory_cap_held(trial), able)

    def test_the_run_and_the_check_refuse_with_one_line_before_anything_is_launched(self):
        for how in ("ignored", "unreadable"):
            with self.subTest(how):
                world = scenes.scene(scenes.document(memory_limit_bytes=CAP))
                world.memory_cap = how
                world.program("gate", exit_code=0)
                code, lines, err = scenes.run_in(world)
                self.assertEqual((code, err, lines[-1]), (0, "", CNS))
                self.assertEqual(ending_of(world), (CNS, "memory_cap_unavailable", "input_check"))
                self.assertEqual(world.started, [])  # nothing was launched, no gate either
                line = flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
                self.assertIn("cannot cap memory for a user scope", line)
                other = scenes.scene(scenes.document(memory_limit_bytes=CAP, request_id="c-1"))
                other.memory_cap = how
                code, shown, err = checked(other)
                self.assertEqual((code, err), (0, ""))
                self.assertIn("check: refused: memory_cap_unavailable", shown)
                self.assertEqual(other.started, [])
                self.assertIn(line, shown[1])

    def test_a_bad_value_is_refused_the_same_by_the_run_and_the_check_and_asks_no_machine(self):
        for value in (0, "64", 1.5, True):
            with self.subTest(value=value):
                world = scenes.scene(scenes.document(memory_limit_bytes=value))
                scenes.run_in(world)
                self.assertEqual(ending_of(world), (CNS, "missing_setting", "input_check"))
                line = flat(scenes.outcome(world)["receipt"])["ending"]["reason_text"]
                other = scenes.scene(scenes.document(memory_limit_bytes=value))
                _, shown, _ = checked(other)
                self.assertIn("check: refused: missing_setting", shown)
                self.assertIn(line, shown[1])
                for each in (world, other):
                    self.assertEqual(each.calls("boundary.try_memory_cap"), [])
                    self.assertEqual(each.started, [])

    def test_a_document_without_a_cap_never_asks_the_machine_and_runs_as_it_did(self):
        world = scenes.scene()
        world.memory_cap = "unreadable"  # a machine that could not cap is no matter
        scenes.run_in(world)
        self.assertEqual(ending_of(world), ("ended_by_itself", "none", "none"))
        self.assertEqual(world.calls("boundary.try_memory_cap"), [])
        _, shown, _ = checked(scenes.scene())
        self.assertIn("check: no refusal found", shown)

    def test_a_machine_that_can_cap_is_asked_once_a_run_with_the_trial_numbers(self):
        world = scenes.scene(scenes.document(memory_limit_bytes=CAP))
        scenes.run_in(world)
        self.assertEqual(
            world.calls("boundary.try_memory_cap"),
            [((boundary.TRIAL_MEMORY_BYTES, boundary.SWAP_WITH_A_CAP_BYTES), 0.0)],
        )


class TheCapGoesToTheScope(unittest.TestCase):
    def argv(self, limit):
        return boundary.launch_argv("n", 1, ["t"], [], REACH, 3, limit)

    def test_a_cap_is_memory_and_swap_together_and_is_a_property_of_the_scope(self):
        argv = self.argv(CAP)
        before_the_box = argv[: argv.index("--")]
        self.assertEqual(before_the_box[-4:], ["-p", f"MemoryMax={CAP}", "-p", "MemorySwapMax=0"])
        self.assertNotIn("MemoryMax", " ".join(argv[argv.index("--") :]))

    def test_no_cap_leaves_the_command_as_it_was(self):
        plain = boundary.launch_argv("n", 1, ["t"], [], REACH, 3)
        self.assertEqual(self.argv(None), plain)
        self.assertFalse(any("Memory" in part for part in plain))

    def test_a_gate_and_the_freeze_scope_carry_no_cap(self):
        for argv in (boundary.gate_argv("g", 1, ["x"], 3), boundary.scoped_argv("f", 1, ["x"])):
            self.assertFalse(any("Memory" in part for part in argv))

    def test_a_run_starts_its_scope_with_the_cap_the_document_names(self):
        world = scenes.scene(scenes.document(memory_limit_bytes=CAP))
        scenes.run_in(world)
        argv, _ = world.started[-1]
        self.assertIn(f"MemoryMax={CAP}", argv)
        self.assertIn("MemorySwapMax=0", argv)

    def test_a_run_without_a_cap_starts_its_scope_without_one(self):
        world = scenes.scene()
        scenes.run_in(world)
        argv, _ = world.started[-1]
        self.assertFalse(any("Memory" in part for part in argv))


class WhatEndedTheScopeDecidesTheEnding(unittest.TestCase):
    """The scope's own result is the evidence; bubblewrap's report is the same whether the cap
    ended the program or the program was never run."""

    def run_it(self, doc=None, **program):
        world = scenes.scene(doc or scenes.document(memory_limit_bytes=CAP), **program)
        code, lines, err = scenes.run_in(world)
        self.assertEqual((code, err), (0, ""))
        return world

    def test_a_cap_whose_scope_was_oom_killed_ends_as_memory_limit_with_nothing_left_behind(self):
        world = self.run_it(oom_kills=True)
        self.assertEqual(ending_of(world), ("memory_limit", "memory_limit", "none"))
        receipt = scenes.outcome(world)["receipt"]
        self.assertEqual(core.check_receipt(receipt), [])
        saw = flat(receipt)
        self.assertIs(saw["ending"]["everything_stopped"], True)
        self.assertEqual(world.units, {})  # the scope is stopped, seen empty and forgotten
        self.assertEqual(len(world.calls("boundary.forget")), 1)
        self.assertEqual([n for n in world.folders if n.startswith("/tmp/shuttle-run-area-")], [])
        self.assertEqual(saw["execution"]["teardown_failure"], "none")
        self.assertEqual(
            (saw["execution"]["exit_code"], saw["execution"]["signal"]), ("none", "cannot tell")
        )

    def test_the_closing_freeze_and_the_place_are_the_same_as_for_a_time_limit(self):
        got = []
        for program in ({"oom_kills": True}, {"times_out": True}):
            made = {"creates": (f"{scenes.PLACE}/new.txt",)}  # the program writes in the place
            world = scenes.scene(scenes.document(memory_limit_bytes=CAP), **program, **made)
            scenes.run_in(world)
            saw = flat(scenes.outcome(world)["receipt"])["execution"]
            got.append(
                (
                    saw["files_added"],
                    saw["files_changed"],
                    saw["files_deleted"],
                    saw["changed_nothing"],
                    len(world.calls("git.freeze")),
                )
            )
        self.assertEqual(got[0], got[1])
        self.assertEqual(got[0][0], 1)

    def test_a_cap_whose_program_was_never_reported_running_ends_as_program_not_started(self):
        world = self.run_it(cannot_exec=True)
        self.assertEqual(ending_of(world), (CNS, "program_not_started", "launch"))
        saw = flat(scenes.outcome(world)["receipt"])["execution"]
        self.assertEqual((saw["exit_code"], saw["signal"]), ("none", "none"))

    def test_a_cap_whose_scope_hit_the_time_limit_ends_as_time_limit(self):
        world = self.run_it(times_out=True)
        self.assertEqual(ending_of(world), ("time_limit", "time_limit", "none"))

    def test_a_cap_that_the_program_stayed_under_ends_as_the_programs_own_exit(self):
        for code in (0, 3):
            with self.subTest(code=code):
                world = self.run_it(exit_code=code)
                self.assertEqual(ending_of(world), ("ended_by_itself", "none", "none"))
                saw = flat(scenes.outcome(world)["receipt"])["execution"]
                self.assertEqual(saw["exit_code"], code)

    def test_a_scope_ended_by_the_machines_memory_with_no_cap_ends_as_it_does_at_the_base(self):
        world = self.run_it(scenes.document(), oom_kills=True)
        self.assertEqual(ending_of(world), ("ended_by_itself", "none", "none"))

    def test_the_same_program_with_and_without_a_cap_differs_only_by_the_cap(self):
        capped = self.run_it(oom_kills=True)
        bare = self.run_it(scenes.document(), oom_kills=True)
        reports = [world.children[-1].report for world in (capped, bare)]
        self.assertEqual(reports[0], reports[1])
        self.assertNotEqual(ending_of(capped), ending_of(bare))
