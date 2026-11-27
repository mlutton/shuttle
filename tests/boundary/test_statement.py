"""The statement and the references, through the real command in the real boundary.

A small real script is the executor. It leaves a statement at the path inside the run area that
its notice gives it (it is never told the document's statement location), or tries to change a
reference, and the test asserts only what a caller can see: the files, the outcome
record, and what is left running. The shape check is a table in tests/by_value/test_statement.py;
the run on the simulated world is tests/by_value/test_kept_statement.py. None of these keeps time.
"""

import hashlib
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
locations_table = importlib.import_module("hostile.statement_locations_table")
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")

# What every script below does first: finds, in the notice on its standard input, the path it is
# told to write its statement at.
FINDS_ITS_PATH = """
import re, sys
inner = re.search("exact path: (.+)", sys.stdin.read()).group(1)
"""

# argv 1 is the path of a file holding the bytes to leave at the statement path.
LEAVES_WHAT_IT_IS_GIVEN = (
    FINDS_ITS_PATH
    + """
with open(sys.argv[1], "rb") as source, open(inner, "wb") as target:
    target.write(source.read())
"""
)

# argv 1 is the document's statement location, which it is not told: it writes there
# and not at its own path, as a script that guessed would.
WRITES_AT_THE_DOCUMENTS_LOCATION = (
    FINDS_ITS_PATH
    + """
with open(sys.argv[1], "w") as target:
    target.write("not at the path it was told")
"""
)

# argv 1 is a file to write everything the executor was given into: its arguments, its whole
# environment, its working directory and its standard input.
RECORDS_EVERYTHING_IT_WAS_GIVEN = """
import json, os, sys
with open(sys.argv[1], "w") as f:
    json.dump({"argv": sys.argv, "environ": dict(os.environ), "cwd": os.getcwd(),
               "stdin": sys.stdin.read()}, f)
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
        """Run a kind that expects a statement; the script leaves `data` at its path in the run area."""
        location = os.path.join(self.root, "statement-" + request_id)
        given = os.path.join(self.root, "given-" + request_id)
        with open(given, "wb") as f:
            f.write(data)
        script = self.script("leaves.py", LEAVES_WHAT_IT_IS_GIVEN)
        doc = self.document(script, [given], request_id=request_id)
        self.expecting_a_statement(doc, location)
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
        with open(
            os.path.join(self.root, "statement-r-1"), "rb"
        ) as f:  # at the document's location
            self.assertEqual(f.read(), data)
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
        self.expecting_a_statement(doc, os.path.join(self.root, "never-written"))
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
        self.assertFalse(os.path.exists(os.path.join(self.root, "never-written")))

    def test_a_script_that_writes_at_the_documents_location_and_not_in_the_run_area_shows_none(
        self,
    ):
        location = os.path.join(self.root, "statement-r-1")
        script = self.script("writes-there.py", WRITES_AT_THE_DOCUMENTS_LOCATION)
        doc = self.document(script, [location])
        self.expecting_a_statement(doc, location)
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        got = flat(self.outcome()["receipt"])["executor"]
        self.assertEqual(
            got,
            {
                k: "none"
                for k in ("statement_state", "statement_hash", "statement_location", "claim")
            },
        )
        self.assertFalse(os.path.exists(os.path.join(self.records, "r-1.statement.kept")))

    def test_the_documents_statement_location_is_nowhere_in_what_the_executor_is_given(self):
        location = os.path.join(self.root, "statement-r-1")
        record = os.path.join(self.root, "everything-it-was-given")
        script = self.script("records.py", RECORDS_EVERYTHING_IT_WAS_GIVEN)
        doc = self.document(script, [record])
        self.expecting_a_statement(doc, location)
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(record) as f:
            seen = json.load(f)
        self.assertIn("exact path: ", seen["stdin"])  # it was told where, and it is not that
        for what in ("argv", "environ", "cwd", "stdin"):
            self.assertNotIn(location, json.dumps(seen[what]), what)
        self.assertNotIn(os.path.basename(location), json.dumps(seen))

    def test_a_location_taken_at_the_start_is_still_refused(self):
        location = os.path.join(self.root, "statement-r-1")
        with open(location, "w") as f:
            f.write("taken")
        script = self.script("never-runs.py", LEAVES_NOTHING)
        doc = self.expecting_a_statement(self.document(script), location)
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
        ending = flat(self.outcome()["receipt"])["ending"]
        self.assertEqual(ending["reason"], "statement_location_occupied")

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


# argv 1 is a file that is not a statement; argv 2 the row's line, which sees `location` (the path
# the notice gave) and `given`.
LEAVES_WHAT_IS_NOT_A_FILE = (
    FINDS_ITS_PATH
    + """
import os
location, given = inner, sys.argv[1]
exec(sys.argv[2])
"""
)


class WhatIsNotARegularFileIsNotAStatement(real_run.RealRun):
    def test_every_such_thing_ends_the_run_keeps_nothing_and_reads_wrong_shape(self):
        for index, row in enumerate(locations_table.LOCATIONS):
            with self.subTest(row["label"]):
                request_id = f"loc-{index}"
                location = os.path.join(self.root, f"statement-{index}")
                given = os.path.join(self.root, f"given-{index}")
                with open(given, "wb") as f:
                    f.write(b"-----BEGIN PRIVATE KEY-----\n")
                script = self.script(f"leaves-{index}.py", LEAVES_WHAT_IS_NOT_A_FILE)
                doc = self.document(script, [given, row["leaves"]], request_id=request_id)
                self.expecting_a_statement(doc, location)
                # `communicate` has a limit, so a run that waits on the thing fails, not hangs.
                code, lines, err = self.run_to_the_end(doc)
                self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
                got = flat(self.outcome(request_id)["receipt"])["executor"]
                self.assertEqual(
                    got,
                    {
                        "statement_state": "wrong_shape",
                        "statement_hash": "none",
                        "statement_location": "none",
                        "claim": "none",
                    },
                )
                self.assertEqual(
                    [n for n in os.listdir(self.records) if n.endswith(".statement.kept")], []
                )
                self.assertFalse(os.path.lexists(doc["statement_location"]))
                self.assertEqual([u for u in self.units_left() if request_id in u], [])


# argv 1 is the file holding the statement, argv 2 the records folder, argv 3 a folder with a
# folder `inner` in it, argv 4 the row's line, argv 5 the request id. It leaves its statement where the notice says, then
# learns the document's location from the request record and
# changes the folders above it.
SWAPS_THE_FOLDERS_ABOVE_THE_LOCATION = (
    FINDS_ITS_PATH
    + """
import json, os
with open(sys.argv[1], "rb") as source, open(inner, "wb") as target:
    target.write(source.read())
with open(os.path.join(sys.argv[2], sys.argv[5] + ".request.json")) as f:
    location = json.loads(json.load(f)["input"])["statement_location"]
parent = os.path.dirname(location)
grandparent = os.path.dirname(parent)
victim = sys.argv[3]
exec(sys.argv[4])
"""
)


class AStatementIsNeverCopiedThroughAFolderTheExecutorSwapped(real_run.RealRun):
    def test_every_swap_keeps_the_statement_and_writes_nothing_where_the_folders_now_lead(self):
        for index, row in enumerate(locations_table.PARENTS):
            with self.subTest(row["label"]):
                request_id = f"swap-{index}"
                base = os.path.join(self.root, f"swap-{index}")
                location = os.path.join(base, "outer", "inner", "statement.json")
                os.makedirs(os.path.dirname(location))
                victim = os.path.join(base, "victim")
                os.makedirs(os.path.join(victim, "inner"))
                data = json.dumps(STATEMENT).encode()
                given = os.path.join(base, "given")
                with open(given, "wb") as f:
                    f.write(data)
                script = self.script(f"swaps-{index}.py", SWAPS_THE_FOLDERS_ABOVE_THE_LOCATION)
                doc = self.document(
                    script,
                    [given, self.records, victim, row["swaps"], request_id],
                    request_id=request_id,
                )
                self.expecting_a_statement(doc, location)
                code, lines, err = self.run_to_the_end(doc)
                self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
                got = flat(self.outcome(request_id)["receipt"])["executor"]
                self.assertEqual(got["statement_state"], "right_shape")
                with open(os.path.join(self.records, request_id + ".statement.kept"), "rb") as f:
                    self.assertEqual(f.read(), data)
                written = [
                    os.path.join(folder, name)
                    for folder, _, names in os.walk(victim)
                    for name in names
                ]
                self.assertEqual(written, [])
                self.assertEqual(self.units_left(), [])


class ALocationInTheRecordsFolderIsRefused(real_run.RealRun):
    def test_no_spelling_of_a_path_in_the_records_folder_is_accepted_and_the_record_stands(self):
        link = os.path.join(self.root, "records-link")
        os.symlink(self.records, link)
        cases = (
            ("the outcome record's own name", os.path.join(self.records, "r-1.outcome.json")),
            ("another name in the folder", os.path.join(self.records, "other.txt")),
            ("a name in a folder not there yet", os.path.join(self.records, "sub", "s.json")),
            ("through a link to the folder", os.path.join(link, "via-link.json")),
            ("through ..", os.path.join(self.records, "..", "records", "via-dots.json")),
            ("the folder itself", self.records),
        )
        for index, (label, location) in enumerate(cases):
            with self.subTest(label):
                request_id = f"rec-{index}"
                script = self.script(f"never-{index}.py", LEAVES_NOTHING)
                doc = self.expecting_a_statement(
                    self.document(script, request_id=request_id), location
                )
                code, lines, err = self.run_to_the_end(doc)
                self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
                ending = flat(self.outcome(request_id)["receipt"])["ending"]
                self.assertEqual(
                    (ending["reason"], ending["failed_step"]),
                    ("statement_location_in_records", "input_check"),
                )
                self.assertEqual(
                    ending["reason_text"],
                    f"statement_location {location!r} is in the records folder, where Shuttle "
                    "writes only its own records; name a path outside the records folder",
                )
        self.assertEqual(
            sorted(os.listdir(self.records)),
            sorted(f"rec-{i}.{k}.json" for i in range(len(cases)) for k in ("outcome", "request")),
        )


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


class AReferenceThatIsNotAFileCannotMakeTheCheckWait(real_run.RealRun):
    def reference(self, path):
        return {"name": "r", "path": path, "hash": sha(b"x"), "size": 1, "hash_source": "caller"}

    def run_with(self, path, request_id):
        doc = self.document(self.script("noop.py", LEAVES_NOTHING), request_id=request_id)
        doc["references"] = [self.reference(path)]
        code, lines, err = self.run_to_the_end(doc)  # `communicate` has a limit: a wait fails
        return code, err, lines[-1], flat(self.outcome(request_id)["receipt"])

    def test_a_pipe_and_a_link_to_a_device_are_refused_as_missing_and_end_at_once(self):
        pipe = self.pipe("pipe")
        device = os.path.join(self.root, "zero")
        os.symlink("/dev/zero", device)
        for index, path in enumerate((pipe, device)):
            with self.subTest(path):
                code, err, last, receipt = self.run_with(path, f"ref-{index}")
                self.assertEqual((code, err, last), (0, "", "could_not_start"))
                self.assertEqual(receipt["ending"]["reason"], "reference_missing")

    def test_a_link_to_a_regular_file_is_followed_as_before(self):
        target, link = os.path.join(self.root, "target"), os.path.join(self.root, "link")
        with open(target, "wb") as f:
            f.write(b"x")
        os.symlink(target, link)
        code, err, last, receipt = self.run_with(link, "ref-link")
        self.assertEqual((code, err, last), (0, "", "ended_by_itself"))
        self.assertEqual(receipt["execution"]["reference_hashes"], {"r": sha(b"x")})
