"""What a run keeps of the executor's own output, through the real command in the real boundary.

A small real script is the executor, and for the driver that has a final message a stand-in tool
(`run_a_stand_in_tool`, tests/rehearsal/real_run.py) is. The test asserts only what a caller can see:
the files in the records folder, their permissions, and the receipt. The names, the reading of a
failure and the run on the simulated world are in tests/by_value/test_kept_evidence.py.
"""

import hashlib
import importlib
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")

# Bytes that are not text and a last line with no end on standard output; bytes that are not text on
# standard error.
PRINTS_TO_BOTH = r"""
import os, sys
os.write(1, b"out \x00\xff\r\nno final newline")
os.write(2, b"err \x00\xfe warning\n")
"""

PRINTS_THEN_HANGS = (
    PRINTS_TO_BOTH
    + """
import time
time.sleep(600)
"""
)

# Puts a link to a file of the caller's where its standard output is written, and says what it did.
SWAPS_ITS_OUTPUT_FOR_A_LINK = r"""
import os, sys
path = os.readlink("/proc/self/fd/1")
os.unlink(path)
os.symlink(sys.argv[1], path)
sys.stderr.write("swapped\n")
"""

# The stand-in for a tool with a final message: events on standard output, the message in the file
# named after "-o", and a complaint on standard error.
STAND_IN_TOOL = r"""
import sys
arguments = sys.argv[1:]
sys.stdin.read()
sys.stdout.write('{"type":"thread.started","thread_id":"thread-1"}\n')
sys.stdout.flush()
sys.stderr.write("a made-up warning\n")
open(arguments[arguments.index("-o") + 1], "w").write("Made-up final message.")
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


class TheExecutorsOutputIsKept(real_run.RealRun):
    def kept(self, what, request_id="r-1"):
        with open(os.path.join(self.records, f"{request_id}.{what}.kept"), "rb") as f:
            return f.read()

    def execution(self, request_id="r-1"):
        return self.outcome(request_id)["receipt"]["execution"]

    def held(self, what, data, field):
        path = os.path.join(self.records, f"r-1.{what}.kept")
        self.assertEqual(
            self.execution()[field],
            {"state": "value", "value": {"kept_at": path, "hash": sha(data)}},
        )
        return path

    def test_standard_output_and_standard_error_are_kept_whole_for_the_owner_only(self):
        doc = self.document(self.script("prints.py", PRINTS_TO_BOTH))
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        out, error = b"out \x00\xff\r\nno final newline", b"err \x00\xfe warning\n"
        self.assertEqual(self.kept("standard-output"), out)
        self.assertEqual(self.kept("standard-error"), error)
        for what, data, field in (
            ("standard-output", out, "standard_output_kept"),
            ("standard-error", error, "standard_error_kept"),
        ):
            path = self.held(what, data, field)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(
            self.execution()["final_message_kept"], {"state": "none", "value": None}
        )  # a plain command has no final message

    def test_a_link_put_in_place_of_the_output_is_not_followed_and_nothing_of_it_is_kept(self):
        secret = os.path.join(self.root, "secret")
        with open(secret, "w") as f:
            f.write("not for the records")
        doc = self.document(self.script("swaps.py", SWAPS_ITS_OUTPUT_FOR_A_LINK), [secret])
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        self.assertEqual(
            self.execution()["standard_output_kept"], {"state": "cannot tell", "value": None}
        )
        self.assertFalse(os.path.exists(os.path.join(self.records, "r-1.standard-output.kept")))
        self.assertEqual(self.kept("standard-error"), b"swapped\n")

    def test_a_program_the_box_cannot_execute_ends_as_not_started_and_keeps_what_the_box_printed(
        self,
    ):
        script = os.path.join(self.support, "script")
        with open(script, "w") as f:
            f.write("#!/nonexistent-folder/sh\n")
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        doc = self.document("unused")
        doc["executor"]["settings"] = {"command": script, "arguments": []}
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
        receipt = self.outcome()["receipt"]
        self.assertEqual(receipt["ending"]["reason"]["value"], "program_not_started")
        complaint = self.kept("standard-error")
        self.assertNotEqual(complaint, b"")
        self.assertIn(script.encode(), complaint)  # the box names the program it could not run
        self.held("standard-error", complaint, "standard_error_kept")
        self.held("standard-output", self.kept("standard-output"), "standard_output_kept")
        self.assertEqual(self.execution()["final_message_kept"], {"state": "none", "value": None})

    def test_they_are_kept_when_the_time_limit_ends_the_run(self):
        doc = self.document(self.script("hangs.py", PRINTS_THEN_HANGS), limit=1)
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "time_limit"))
        self.assertEqual(self.kept("standard-output"), b"out \x00\xff\r\nno final newline")
        self.assertEqual(self.kept("standard-error"), b"err \x00\xfe warning\n")
        self.held("standard-output", self.kept("standard-output"), "standard_output_kept")

    def test_a_tool_with_a_final_message_has_its_event_stream_message_and_errors_kept(self):
        driver = real_run.tool_driver_names()[0]
        home = os.path.join(self.root, "home")
        login = real_run.table.DRIVERS[driver].login_path({"HOME": home})
        os.makedirs(os.path.dirname(login))
        for name, text in ((login, "a made-up stand-in, not a login\n"), ("config.toml", "\n")):
            with open(os.path.join(os.path.dirname(login), os.path.basename(name)), "w") as f:
                f.write(text)
        doc = self.document(self.script("unused.py", ""))
        doc["executor"] = {"name": driver, "settings": {"model": "example-model"}}
        doc["network"], doc["changes_to_place"] = "off", "allowed"
        code, lines, err = self.run_a_stand_in_tool(doc, STAND_IN_TOOL, {"HOME": home})
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        events = b'{"type":"thread.started","thread_id":"thread-1"}\n'
        self.assertEqual(self.kept("standard-output"), events)
        self.assertEqual(self.kept("standard-error"), b"a made-up warning\n")
        self.assertEqual(self.kept("final-message"), b"Made-up final message.")
        self.held("standard-output", events, "standard_output_kept")
        self.held("final-message", b"Made-up final message.", "final_message_kept")
