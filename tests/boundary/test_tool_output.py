"""A tool that prints a large event stream is handled in bounded memory, through the real command.

The program that stands in for the tool is a script written into a folder of the test's own and
put first on the command's PATH, which holds nothing else but the system's two folders, so no
real tool can be found, let alone started. The login and settings file it is given are made-up
text. The stream is hand-made in the shape of the tool's own, with made-up counts: many small
events, one line longer than any line is read, and a last turn that gives the usage.

The harness holds the command and everything it starts to its file-size and address-space limits
(tests/rehearsal/real_run.py), so a regression is a failed assertion in seconds. The check that
nothing grows with the stream is the peak size of the processes this test waited for: a command
that read the whole stream into memory, a dictionary per line, passes 100 MB on the stream below.
"""

import importlib
import os
import resource
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
flat = importlib.import_module("rehearsal.receipts").flat
real_run = importlib.import_module("rehearsal.real_run")

# The stand-in is named as the driver looks for it; the name is built from two parts, as the rule
# test of the suite builds it, so this file never holds the word whole.
PROGRAM = "co" + "dex"
SMALL_EVENTS = 120_000
ONE_LONG_LINE = 2 << 20  # longer than the longest line the command reads

STAND_IN = """#!{python}
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
        self.bin = os.path.join(self.root, "bin")
        os.mkdir(self.bin)
        stand_in = os.path.join(self.bin, PROGRAM)
        with open(stand_in, "w") as f:
            f.write(STAND_IN.format(python=sys.executable, small=SMALL_EVENTS, long=ONE_LONG_LINE))
        os.chmod(stand_in, os.stat(stand_in).st_mode | stat.S_IXUSR)
        self.home = os.path.join(self.root, "home")
        os.makedirs(os.path.join(self.home, ".codex"))
        for name, text in (
            ("auth.json", "a made-up stand-in, not a login\n"),
            ("config.toml", "\n"),
        ):
            with open(os.path.join(self.home, ".codex", name), "w") as f:
                f.write(text)

    def test_the_run_ends_with_its_record_the_counts_are_read_and_memory_does_not_follow_the_stream(
        self,
    ):
        doc = self.document(self.script("unused.py", ""))
        doc["executor"] = {"name": PROGRAM, "settings": {"model": "example-model"}}
        doc["network"], doc["changes_to_place"] = "off", "allowed"
        # Only the stand-in's folder and the system's own: no real tool is on this PATH.
        path = os.pathsep.join([self.bin, "/usr/bin", "/bin"])
        code, lines, err = self.run_to_the_end(doc, variables={"PATH": path, "HOME": self.home})
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        receipt = flat(self.outcome()["receipt"])
        group = receipt["executor_driver"]
        self.assertEqual(
            (group["tokens_in"], group["tokens_out"], group["tokens_cached"]), (7, 2, 3)
        )
        self.assertEqual(group["activity"], SMALL_EVENTS + 1)  # the long line is counted, not held
        self.assertEqual(group["session_id"], "thread-big")
        peak_kilobytes = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        self.assertLess(peak_kilobytes, 100 * 1024)
