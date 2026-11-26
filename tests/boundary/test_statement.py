"""The statement and the references, through the real command in the real boundary.

A small real script is the executor. It leaves a statement at the statement location, or tries to
change a reference, and the test asserts only what a caller can see: the files, the outcome
record, and what is left running. The shape check is a table in tests/by_value/test_statement.py;
the run on the simulated world is tests/by_value/test_kept_statement.py. None of these keeps time.
"""

import hashlib
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")

# argv 1 is the statement location, argv 2 the path of a file holding the bytes to leave there.
LEAVES_WHAT_IT_IS_GIVEN = """
import sys
with open(sys.argv[2], "rb") as source, open(sys.argv[1], "wb") as target:
    target.write(source.read())
"""

LEAVES_NOTHING = "pass\n"

# Each attempt on the reference (argv 1) is one line in the file at argv 2: "<name> refused" or
# "<name> GOT THROUGH".
TRIES_TO_CHANGE_THE_REFERENCE = """
import os, sys
reference, log = sys.argv[1], open(sys.argv[2], "w")

def attempt(name, action):
    try:
        action()
    except OSError:
        log.write(name + " refused\\n")
    else:
        log.write(name + " GOT THROUGH\\n")

def write(path, mode="w"):
    with open(path, mode) as f:
        f.write("changed")

attempt("overwrite", lambda: write(reference))
attempt("append", lambda: write(reference, "a"))
attempt("delete", lambda: os.unlink(reference))
attempt("rename it", lambda: os.rename(reference, reference + ".moved"))
attempt("rename over it", lambda: os.rename(sys.argv[2], reference))
attempt("make it a link", lambda: os.symlink("/", reference))
attempt("truncate", lambda: os.truncate(reference, 0))
attempt("change its mode", lambda: os.chmod(reference, 0o777))
"""

STATEMENT = {
    "claim": "done",
    "summary": "Did it.",
    "evidence": [{"claim": "it ran", "command": "true"}],
    "not_tested": [],
    "feedback": "none",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


class AStatementIsKeptAsWritten(real_run.RealRun):
    def run_leaving(self, data, request_id="r-1"):
        """Run a kind that expects a statement; the script leaves `data` at the location."""
        location = os.path.join(self.root, "statement-" + request_id)
        given = os.path.join(self.root, "given-" + request_id)
        with open(given, "wb") as f:
            f.write(data)
        script = self.script("leaves.py", LEAVES_WHAT_IT_IS_GIVEN)
        doc = self.document(script, [location, given], request_id=request_id)
        doc["kind"], doc["statement_location"] = "judge", location
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        return flat(self.outcome(request_id)["receipt"])["executor"]

    def kept(self, request_id="r-1"):
        with open(os.path.join(self.records, f"{request_id}.statement.kept"), "rb") as f:
            return f.read()

    def test_a_right_shaped_statement_is_kept_byte_for_byte_and_not_tidied_or_completed(self):
        # CRLF line ends, trailing spaces and no final newline: any tidying would change it.
        data = json.dumps(STATEMENT, indent=2).replace("\n", "  \r\n").encode()
        got = self.run_leaving(data)
        self.assertEqual(self.kept(), data)
        self.assertEqual(
            got,
            {
                "statement_state": "right_shape",
                "statement_hash": sha(data),
                "statement_location": os.path.join(self.records, "r-1.statement.kept"),
                "claim": "done",
            },
        )
        self.assertEqual(self.units_left(), [])

    def test_a_script_that_leaves_no_statement_shows_none(self):
        script = self.script("leaves-nothing.py", LEAVES_NOTHING)
        doc = self.document(script)
        doc["kind"] = "judge"
        doc["statement_location"] = os.path.join(self.root, "never-written")
        self.run_to_the_end(doc)
        got = flat(self.outcome()["receipt"])["executor"]
        self.assertEqual(
            got,
            {
                k: "none"
                for k in ("statement_state", "statement_hash", "statement_location", "claim")
            },
        )
        self.assertFalse(os.path.exists(os.path.join(self.records, "r-1.statement.kept")))

    def test_a_statement_of_the_wrong_shape_shows_wrong_shape_and_is_kept_as_written(self):
        data = b"I need to know which file you mean. Can you tell me?\n"
        got = self.run_leaving(data)
        self.assertEqual((got["statement_state"], got["claim"]), ("wrong_shape", "none"))
        self.assertEqual(got["statement_hash"], sha(data))
        self.assertEqual(self.kept(), data)

    def test_a_statement_with_a_claim_off_the_list_is_the_wrong_shape(self):
        data = json.dumps({**STATEMENT, "claim": "finished"}).encode()
        got = self.run_leaving(data)
        self.assertEqual((got["statement_state"], got["claim"]), ("wrong_shape", "none"))


class AReferenceCannotBeChangedByTheExecutor(real_run.RealRun):
    # Names a path can hold: a space, `$`, `%`, a newline, a leading dash, a backslash.
    NAME = "ref $HOME ${X} 100%\nline -dash \\back"

    def test_every_attempt_is_refused_and_the_reference_and_its_hash_are_unchanged(self):
        reference = os.path.join(self.root, self.NAME)
        with open(reference, "w") as f:
            f.write("the runbook")
        log = os.path.join(self.root, "log.txt")
        script = self.script("tries.py", TRIES_TO_CHANGE_THE_REFERENCE)
        doc = self.document(script, [reference, log])
        doc["references"] = [
            {
                "name": "runbook",
                "path": reference,
                "hash": sha(b"the runbook"),
                "size": 11,
                "hash_source": "caller",
            }
        ]
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(log) as f:
            attempts = f.read().splitlines()
        self.assertEqual(len(attempts), 8)
        self.assertEqual([a for a in attempts if not a.endswith(" refused")], [])
        with open(reference, "rb") as f:
            self.assertEqual(f.read(), b"the runbook")
        self.assertEqual(sorted(os.listdir(self.root)).count(self.NAME), 1)
        self.assertNotIn(self.NAME + ".moved", os.listdir(self.root))
        held = flat(self.outcome()["receipt"])["execution"]["reference_hashes"]
        self.assertEqual(held, {"runbook": sha(b"the runbook")})
