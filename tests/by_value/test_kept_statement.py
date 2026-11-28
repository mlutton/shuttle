"""By value, through the whole run on the simulated world: the statement kept, its state and
claim in the receipt, the references' hashes, and what the executor may not write.

The statement's shape is a table in test_statement.py; here the run is looked at: what is kept,
and what the receipt says of it. The real command and the real boundary are in
tests/command/test_statement.py.
"""

import hashlib
import importlib
import json
import os
import sys
import unittest

from shuttle.core import decisions as core
from shuttle.core import run_area
from shuttle.shell import statement_schema

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat

LOCATION = "/out/statement.json"
# Where the executor writes: inside the first run area the simulated world makes.
INNER = run_area.statement_path("/tmp/shuttle-run-area-" + f"{1:032x}")
KEPT = "/records/inj-1.statement.kept"
STATEMENT = {
    "claim": "done",
    "summary": "Did it.",
    "evidence": [{"claim": "it works", "command": "make test"}],
    "not_tested": [],
    "feedback": "none",
}
# Written the way a script might: CRLF, trailing spaces, no final newline. Tidying would change it.
UNTIDY = json.dumps(STATEMENT, indent=3).replace("\n", "  \r\n")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def pairs(world):
    return scenes.outcome(world)["receipt"]["executor"]


def writes(world, text):
    """The script leaves `text` at its statement path in the run area as it starts."""
    world.make_folder("/out")
    world.on_call("processes.start", lambda: world.put_file(INNER, text))


def document(**extra):
    return scenes.document(kind="judge", statement_location=LOCATION, **extra)


class TheKeptStatement(unittest.TestCase):
    def run_with(self, text, doc=None):
        world = scenes.scene(doc or document())
        world.make_folder("/out")
        if text is not None:
            writes(world, text)
        code, _, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        return world

    def test_a_right_shaped_statement_is_kept_exactly_and_its_claim_is_copied_unchanged(self):
        world = self.run_with(UNTIDY)
        self.assertEqual(world.text_of(KEPT), UNTIDY)  # byte for byte: not tidied, not completed
        self.assertEqual(world.text_of(LOCATION), UNTIDY)  # the copy at the document's location
        got = pairs(world)
        self.assertEqual(got["statement_state"], {"state": "value", "value": "right_shape"})
        self.assertEqual(got["statement_hash"], {"state": "value", "value": sha(UNTIDY)})
        self.assertEqual(got["statement_location"], {"state": "value", "value": KEPT})
        self.assertEqual(got["claim"], {"state": "value", "value": "done"})
        self.assertEqual(core.check_receipt(scenes.outcome(world)["receipt"]), [])

    def test_every_claim_word_comes_through_as_written(self):
        for word in ("done", "partly_done", "blocked", "not_done"):
            with self.subTest(word):
                world = self.run_with(json.dumps({**STATEMENT, "claim": word}))
                self.assertEqual(pairs(world)["claim"], {"state": "value", "value": word})

    def test_a_script_that_leaves_no_statement_shows_none_in_every_field(self):
        world = self.run_with(None)
        for field in ("statement_state", "statement_hash", "statement_location", "claim"):
            self.assertEqual(pairs(world)[field], {"state": "none", "value": None}, field)
        self.assertEqual(world.names_in("/records"), ["inj-1.outcome.json", "inj-1.request.json"])

    def test_a_statement_of_the_wrong_shape_shows_wrong_shape_is_kept_and_has_no_claim(self):
        text = json.dumps({**STATEMENT, "claim": "finished"})
        world = self.run_with(text)
        got = pairs(world)
        self.assertEqual(got["statement_state"], {"state": "value", "value": "wrong_shape"})
        self.assertEqual(got["statement_hash"], {"state": "value", "value": sha(text)})
        self.assertEqual(got["statement_location"], {"state": "value", "value": KEPT})
        self.assertEqual(got["claim"], {"state": "none", "value": None})
        self.assertEqual(world.text_of(KEPT), text)

    def test_a_question_instead_of_a_statement_is_wrong_shape_and_the_run_still_ends_by_itself(
        self,
    ):
        world = self.run_with("Which file did you mean?")
        self.assertEqual(pairs(world)["statement_state"]["value"], "wrong_shape")
        ending = flat(scenes.outcome(world)["receipt"])["ending"]
        self.assertEqual(ending["ending"], "ended_by_itself")

    def test_a_folder_at_the_location_is_wrong_shape_with_nothing_to_hash_or_keep(self):
        world = scenes.scene(document())
        world.make_folder("/out")
        world.on_call("processes.start", lambda: world.make_folder(INNER))
        scenes.run_in(world)
        got = pairs(world)
        self.assertEqual(got["statement_state"], {"state": "value", "value": "wrong_shape"})
        for field in ("statement_hash", "statement_location", "claim"):
            self.assertEqual(got[field], {"state": "none", "value": None}, field)

    def test_a_link_a_pipe_or_a_device_at_the_location_is_wrong_shape_and_nothing_is_kept(self):
        things = {
            "a link to a file": lambda w: (
                w.put_file("/out/other", "secret"),
                w.put_link(INNER, "/out/other"),
            ),
            "a link to a missing name": lambda w: w.put_link(INNER, "/out/absent"),
            "a named pipe": lambda w: w.put_pipe(INNER),
            "a link to a device": lambda w: (
                w.put_device("/dev/zero"),
                w.put_link(INNER, "/dev/zero"),
            ),
        }
        for label, leave in things.items():
            with self.subTest(label):
                world = scenes.scene(document())
                world.make_folder("/out")
                world.on_call("processes.start", lambda w=world, f=leave: f(w))
                scenes.run_in(world)
                got = pairs(world)
                self.assertEqual(got["statement_state"], {"state": "value", "value": "wrong_shape"})
                for field in ("statement_hash", "statement_location", "claim"):
                    self.assertEqual(got[field], {"state": "none", "value": None}, field)
                self.assertNotIn(KEPT, world.files)

    def test_the_kept_copy_is_made_from_the_run_area_and_then_copied_to_the_location(self):
        world = self.run_with(UNTIDY)
        self.assertEqual(world.calls("files.copy"), [((INNER, KEPT), 0.0), ((KEPT, LOCATION), 0.0)])
        self.assertEqual([a for a, _ in world.calls("files.hash")], [(KEPT,)])
        self.assertNotIn(INNER, world.files)  # the run area, and the original with it, is removed

    def test_a_statement_written_at_the_documents_location_and_not_in_the_run_area_is_none(self):
        world = scenes.scene(document())
        world.make_folder("/out")
        world.on_call("processes.start", lambda: world.put_file(LOCATION, UNTIDY))
        scenes.run_in(world)
        for field in ("statement_state", "statement_hash", "statement_location", "claim"):
            self.assertEqual(pairs(world)[field], {"state": "none", "value": None}, field)
        self.assertNotIn(KEPT, world.files)
        self.assertEqual(world.calls("files.copy"), [])

    def test_a_name_taken_at_the_location_during_the_run_is_left_and_the_kept_copy_stands(self):
        world = scenes.scene(document())
        world.make_folder("/out")
        world.on_call("processes.start", lambda: world.put_file(INNER, UNTIDY))
        world.on_call("processes.start", lambda: world.put_file(LOCATION, "the executor's"))
        scenes.run_in(world)
        self.assertEqual(pairs(world)["statement_state"]["value"], "right_shape")
        self.assertEqual(world.text_of(KEPT), UNTIDY)
        self.assertEqual(world.text_of(LOCATION), "the executor's")

    def test_when_it_cannot_be_kept_the_four_fields_cannot_tell_and_the_ending_stands(self):
        world = scenes.scene(document())
        writes(world, UNTIDY)
        world.will_raise("files.copy", OSError("injected"))
        scenes.run_in(world)
        for field in ("statement_state", "statement_hash", "statement_location", "claim"):
            self.assertEqual(pairs(world)[field], {"state": "cannot tell", "value": None}, field)
        ending = flat(scenes.outcome(world)["receipt"])["ending"]
        self.assertEqual(ending["ending"], "ended_by_itself")
        self.assertFalse(world.files.get(KEPT))

    def test_when_the_schema_cannot_be_read_the_state_and_claim_cannot_tell_but_the_file_is_kept(
        self,
    ):
        world = scenes.scene(document())
        writes(world, UNTIDY)
        # gone after the executor started: the notice was built from it, the judging cannot be
        world.on_call("processes.start", lambda: world.files.pop(statement_schema.SCHEMA_FILE))
        scenes.run_in(world)
        got = pairs(world)
        self.assertEqual(got["statement_state"], {"state": "cannot tell", "value": None})
        self.assertEqual(got["claim"], {"state": "cannot tell", "value": None})
        self.assertEqual(got["statement_hash"], {"state": "value", "value": sha(UNTIDY)})
        self.assertEqual(world.text_of(KEPT), UNTIDY)

    def test_a_run_that_never_launched_says_none_and_keeps_nothing(self):
        world = scenes.scene(document(references=[{**REF, "hash": sha("different")}]))
        writes(world, UNTIDY)
        scenes.run_in(world)
        self.assertEqual(pairs(world)["statement_state"], {"state": "none", "value": None})
        self.assertFalse(world.calls("files.copy"))


REF = {
    "name": "runbook",
    "path": "/refs/runbook",
    "hash": sha("contents"),
    "size": 8,
    "hash_source": "caller",
}


class TheStatementLocationOfAKindThatExpectsNone(unittest.TestCase):
    def test_a_location_given_to_such_a_kind_is_refused_at_the_input_check(self):
        world = scenes.scene(scenes.document(statement_location=LOCATION))
        code, lines, err = scenes.run_in(world)
        self.assertEqual((code, lines[-1]), (0, "could_not_start"), err)
        ending = flat(scenes.outcome(world)["receipt"])["ending"]
        self.assertEqual(
            (ending["reason"], ending["failed_step"]), ("unknown_field", "input_check")
        )
        self.assertIn("expects no statement", ending["reason_text"])
        self.assertEqual(world.started, [])


class TheReferences(unittest.TestCase):
    def scene_with(self, references, **files):
        world = scenes.scene(scenes.document(references=references))
        for path, text in files.items():
            world.put_file(path, text)
        return world

    def test_the_receipt_holds_the_hash_of_each_reference_by_name(self):
        other = {**REF, "name": "notes", "path": "/refs/notes", "hash": sha("n"), "size": 1}
        world = self.scene_with([REF, other])
        world.put_file("/refs/runbook", "contents")
        world.put_file("/refs/notes", "n")
        scenes.run_in(world)
        held = scenes.outcome(world)["receipt"]["execution"]["reference_hashes"]
        self.assertEqual(
            held, {"state": "value", "value": {"runbook": sha("contents"), "notes": sha("n")}}
        )

    def test_a_run_with_no_references_says_none(self):
        world = scenes.scene()
        scenes.run_in(world)
        held = scenes.outcome(world)["receipt"]["execution"]["reference_hashes"]
        self.assertEqual(held, {"state": "none", "value": None})

    def test_a_refused_reference_leaves_no_hash_in_the_receipt(self):
        world = self.scene_with([REF])
        world.put_file("/refs/runbook", "changed!")
        scenes.run_in(world)
        held = scenes.outcome(world)["receipt"]["execution"]["reference_hashes"]
        self.assertEqual(held, {"state": "none", "value": None})

    def test_a_reference_that_is_a_folder_is_refused_as_missing_and_says_it_is_a_folder(self):
        world = self.scene_with([{**REF, "path": "/refs/folder"}])
        world.make_folder("/refs/folder")
        scenes.run_in(world)
        ending = flat(scenes.outcome(world)["receipt"])["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "reference_missing", "input_check"),
        )
        self.assertIn("is a folder", ending["reason_text"])
        self.assertEqual(world.started, [])

    def bound_read_only(self, world):
        argv = world.started[0][0]
        return [(argv[i + 1], argv[i + 2]) for i, part in enumerate(argv) if part == "--ro-bind"]

    def test_every_reference_is_bound_read_only_in_the_boundary_whatever_its_name(self):
        names = ("a b", "$HOME", "${X}", "100%", "line\nbreak", "-dash", "back\\slash", "tab\t")
        references = [
            {**REF, "name": f"r{n}", "path": f"/refs/{name}"} for n, name in enumerate(names)
        ]
        world = self.scene_with(references, **{f"/refs/{name}": "contents" for name in names})
        scenes.run_in(world)
        bound = self.bound_read_only(world)
        for name in names:
            path = f"/refs/{name}".replace("$", "$$")  # the scope tool turns each "$$" back
            self.assertIn((path, path), bound, name)
        self.assertNotIn("/records", world.started[0][0])  # the records are not in the box at all

    def test_the_references_and_the_places_git_folder_are_the_only_paths_added_to_the_read_only_system_ones(
        self,
    ):
        world = self.scene_with([REF], **{"/refs/runbook": "contents"})
        scenes.run_in(world)
        self.assertEqual(
            self.bound_read_only(world),
            [
                ("/usr", "/usr"),
                ("/etc", "/etc"),
                ("/refs/runbook", "/refs/runbook"),
                ("/place/.git", "/place/.git"),  # the place's git folder, read-only
            ],
        )
