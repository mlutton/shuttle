"""A tool that prints a large event stream is handled in bounded memory, through the real command.

The program that stands in for the tool is written and run by `run_a_stand_in_tool`
(tests/rehearsal/real_run.py), whose docstring holds the guard. The login and settings file it is given are made-up
text. The stream is hand-made in the shape of the tool's own, with made-up counts: many small
events, one line longer than any line is read, and a last turn that gives the usage.

The harness holds the command and everything it starts to its file-size and address-space limits
(tests/rehearsal/real_run.py), so a regression is a failed assertion in seconds. The check that
nothing grows with the stream is the peak size of the processes this test waited for: a command
that read the whole stream into memory, a dictionary per line, passes `PEAK_KILOBYTES` on the
stream below.
"""

import importlib
import os
import resource
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")

SMALL_EVENTS = 120_000
ONE_LONG_LINE = 2 << 20  # longer than the longest line the command reads
PEAK_KILOBYTES = 100 * 1024  # the most the command and what it starts may peak at

STAND_IN = """
import sys
arguments = sys.argv[1:]
sys.stdin.read()
out = sys.stdout
out.write('{{"type":"thread.started","thread_id":"thread-big"}}\\n')
for number in range({small}):
    out.write('{{"type":"item.completed","item":{{"id":"item_%d","type":"agent_message","text":"x"}}}}\\n' % number)
out.write('{{"type":"item.completed","item":{{"type":"command_execution","aggregated_output":"' + "y" * {long} + '"}}}}\\n')
out.write('{{"type":"turn.completed","usage":{{"input_tokens":7,"cached_input_tokens":3,"output_tokens":2}}}}\\n')
out.flush()
open(arguments[arguments.index("-o") + 1], "w").write("Done.")
"""


class AToolThatPrintsALargeStream(real_run.RealRun):
    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.root, "home")
        # The stand-in is the tool's.
        self.driver = real_run.tool_driver_names()[0]
        self.stand_in = STAND_IN.format(small=SMALL_EVENTS, long=ONE_LONG_LINE)

    def document_for_the_tool(self):
        doc = self.document(self.script("unused.py", ""))
        doc["executor"] = {"name": self.driver, "settings": {"model": "example-model"}}
        doc["network"], doc["changes_to_place"] = "off", "allowed"
        return doc

    def make_the_callers_tool_home(self, home):
        """A made-up login and settings file where the driver says the login is."""
        login = real_run.table.DRIVERS[self.driver].login_path({"HOME": home})
        folder = os.path.dirname(login)
        os.makedirs(folder, exist_ok=True)
        for name, text in ((login, "a made-up stand-in, not a login\n"), ("config.toml", "\n")):
            with open(os.path.join(folder, os.path.basename(name)), "w") as f:
                f.write(text)

    def test_the_run_ends_with_its_record_the_counts_are_read_and_memory_does_not_follow_the_stream(
        self,
    ):
        self.make_the_callers_tool_home(self.home)
        doc = self.document_for_the_tool()
        code, lines, err = self.run_a_stand_in_tool(doc, self.stand_in, {"HOME": self.home})
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        receipt = flat(self.outcome()["receipt"])
        group = receipt["executor_driver"]
        self.assertEqual(
            (group["tokens_in"], group["tokens_out"], group["tokens_cached"]), (7, 2, 3)
        )
        self.assertEqual(group["activity"], SMALL_EVENTS + 1)  # the long line is counted, not held
        self.assertEqual(group["session_id"], "thread-big")
        peak_kilobytes = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        self.assertLess(peak_kilobytes, PEAK_KILOBYTES)

    def test_a_program_that_would_resolve_outside_the_tests_stand_in_is_refused_and_nothing_starts(
        self,
    ):
        self.make_the_callers_tool_home(self.home)
        doc = self.document_for_the_tool()
        program = real_run.table.DRIVERS[self.driver].program(doc["executor"]["settings"])
        elsewhere, marker = os.path.join(self.root, "elsewhere"), os.path.join(self.root, "started")
        os.mkdir(elsewhere)
        decoy = os.path.join(elsewhere, program)
        with open(decoy, "w") as f:
            f.write(f"#!{sys.executable}\nopen({marker!r}, 'w').write('started')\n")
        os.chmod(decoy, 0o755)
        with self.assertRaises(AssertionError):
            self.run_a_stand_in_tool(doc, self.stand_in, {"HOME": self.home}, path_first=elsewhere)
        self.assertEqual(os.listdir(self.records), [])  # no request was claimed: nothing ran
        self.assertFalse(os.path.exists(marker))
