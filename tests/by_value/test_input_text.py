"""By value: the request record keeps the exact text the caller gave, and the input's hash is
over those same bytes, so the hash can be checked from the record alone."""

import hashlib
import importlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
scenes = importlib.import_module("rehearsal.scene")
flat = importlib.import_module("rehearsal.receipts").flat


def request_record(world):
    return json.loads(world.text_of(f"{scenes.RECORDS}/{scenes.REQUEST_ID}.request.json"))


def recorded_hash(world):
    return flat(scenes.outcome(world)["receipt"])["execution"]["input_hash"]


def given_text(**extra):
    """The document as the caller might write it: odd spacing, a non-ASCII character, CRLF."""
    text = json.dumps(scenes.document(**extra), indent=4, ensure_ascii=False)
    return text.replace("\n", "\r\n") + "\r\n"


class TheRequestRecordKeepsTheTextAsGiven(unittest.TestCase):
    def run_text(self, text):
        world = scenes.scene()
        world.put_file(scenes.DOCUMENT, text)
        code, _, err = scenes.run_in(world)
        self.assertEqual(code, 0, err)
        return world

    def test_the_stored_text_hashes_to_the_recorded_hash(self):
        world = self.run_text(given_text(note_for_the_caller="é"))
        stored = request_record(world)["input"]
        self.assertEqual(hashlib.sha256(stored.encode("utf-8")).hexdigest(), recorded_hash(world))

    def test_the_stored_text_is_exactly_the_text_given(self):
        text = given_text(thread="é ✓")
        world = self.run_text(text)
        self.assertEqual(request_record(world)["input"], text)

    def test_an_input_with_a_duplicate_key_is_stored_as_given(self):
        text = json.dumps(scenes.document())[:-1] + ', "thread": "second", "thread": "third"}'
        world = self.run_text(text)
        stored = request_record(world)["input"]
        self.assertEqual(stored, text)
        self.assertEqual(stored.count('"thread"'), 3)
        self.assertEqual(hashlib.sha256(stored.encode("utf-8")).hexdigest(), recorded_hash(world))

    def test_an_input_that_is_refused_is_stored_as_given_too(self):
        text = json.dumps(scenes.document(surprise=1), indent=2)
        world = self.run_text(text)
        self.assertEqual(request_record(world)["input"], text)
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), recorded_hash(world))


class InputThatIsNotValidTextStillRefusesAsBefore(unittest.TestCase):
    """Pins unchanged behaviour: bytes that are not UTF-8 are unreadable, and nothing is stored."""

    def test_such_bytes_are_unreadable_and_no_record_is_written(self):
        world = scenes.scene()
        world.put_file(scenes.DOCUMENT, json.dumps(scenes.document()).encode() + b"\xff")
        code, lines, err = scenes.run_in(world)
        self.assertNotEqual(code, 0)
        self.assertEqual(lines, ["none"])
        self.assertEqual(world.names_in(scenes.RECORDS), [])
        self.assertEqual(len(err.strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
