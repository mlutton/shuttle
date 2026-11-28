"""A program the box could not start, against a program that started and failed by itself, through
the real command in the real box.

The ending says the box could not start the program when bubblewrap never reports the program's
end (it reports it for every program it executed, whatever the exit code); no exit code is read.
Each uncovered case here passes the check before the launch (the check looks at the program file
only) and fails when the box executes the program.
"""

import importlib
import os
import shutil
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")
flat = importlib.import_module("rehearsal.receipts").flat

SHELL = shutil.which("sh") or "/bin/sh"


class TheBoxCouldNotStartTheProgram(real_run.RealRun):
    def a_program(self, folder, name, text):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def run_command(self, command, arguments=()):
        """The run of the command driver on `command`; the witness a program writes if it runs."""
        doc = self.document("unused")
        doc["executor"]["settings"] = {"command": command, "arguments": list(arguments)}
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err), (0, ""))
        return flat(self.outcome()["receipt"]), os.path.join(self.place, "witness.txt")

    def assert_not_started(self, receipt, witness):
        ending = receipt["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"]),
            ("could_not_start", "program_not_started", "launch"),
        )
        self.assertIn("reach.visible", ending["reason_text"])
        self.assertEqual(receipt["execution"]["exit_code"], "none")
        self.assertEqual(receipt["execution"]["signal"], "none")
        self.assertFalse(os.path.exists(witness))
        self.assertNotEqual(self.scope_state(), "active")

    def writes_witness(self, interpreter):
        return f"#!{interpreter}\necho ran > {os.path.join(self.place, 'witness.txt')}\n"

    def test_a_script_whose_interpreter_is_in_a_folder_the_box_does_not_show(self):
        hidden = os.path.join(self.root, "hidden")  # not listed, so not in the box
        os.mkdir(hidden)
        shutil.copy(SHELL, os.path.join(hidden, "sh"))
        script = self.a_program(
            self.support, "script", self.writes_witness(os.path.join(hidden, "sh"))
        )
        receipt, witness = self.run_command(script)
        self.assert_not_started(receipt, witness)
        self.assertIn(repr(script), receipt["ending"]["reason_text"])

    def test_a_script_whose_interpreter_is_not_there(self):
        script = self.a_program(
            self.support, "script", self.writes_witness("/nonexistent-folder/sh")
        )
        receipt, witness = self.run_command(script)
        self.assert_not_started(receipt, witness)

    def test_a_path_with_dot_dot_after_a_link_into_a_folder_the_box_does_not_show(self):
        hidden = os.path.join(self.root, "hidden")
        os.makedirs(os.path.join(hidden, "inner"))
        self.a_program(hidden, "program", self.writes_witness(SHELL))
        os.symlink(os.path.join(hidden, "inner"), os.path.join(self.support, "link"))
        # The check reads the path as text, as /support/program, which the box shows; the kernel
        # goes through the link to the hidden folder first, and the box has no such link target.
        receipt, witness = self.run_command(os.path.join(self.support, "link", "..", "program"))
        self.assert_not_started(receipt, witness)


class AProgramThatStartedAndEndedByItselfIsStillItsOwnExit(real_run.RealRun):
    """The same real runs, for programs the box did execute: whatever they exit with, 126 and 127
    included, it is their own exit, and its witness file is there."""

    def run_and_read(self, document, witness):
        got, lines, err = self.run_to_the_end(document)
        self.assertEqual((got, err, lines[-1]), (0, "", "ended_by_itself"))
        self.assertTrue(os.path.exists(witness))  # it ran: the witness is its own proof
        receipt = flat(self.outcome()["receipt"])
        ending = receipt["ending"]
        self.assertEqual(
            (ending["ending"], ending["reason"], ending["failed_step"], ending["reason_text"]),
            ("ended_by_itself", "none", "none", "none"),
        )
        return receipt["execution"]["exit_code"]

    # One test for each code: a run that writes into the place leaves it changed, and a place
    # with uncommitted changes is refused for the next run.

    def exits_with(self, code):
        witness = os.path.join(self.place, "witness.txt")
        script = self.script(
            "exits.py", f"import sys\nopen(sys.argv[1], 'w').close()\nsys.exit({code})\n"
        )
        return self.run_and_read(self.document(script, [witness]), witness)

    def test_a_program_that_exits_0_is_still_reported_as_itself(self):
        self.assertEqual(self.exits_with(0), 0)

    def test_a_program_that_exits_1_is_still_reported_as_itself(self):
        self.assertEqual(self.exits_with(1), 1)

    def test_a_program_that_exits_126_is_still_reported_as_itself(self):
        self.assertEqual(self.exits_with(126), 126)

    def test_a_program_that_exits_127_is_still_reported_as_itself(self):
        self.assertEqual(self.exits_with(127), 127)

    def shell_running(self, command):
        """A shell program that writes its witness, then runs `command`, which it cannot."""
        witness = os.path.join(self.place, "witness.txt")
        script = self.script("shell.sh", f'echo ran > "$1"\n{command}\n')
        document = self.document(script, [witness])
        document["executor"]["settings"] = {"command": SHELL, "arguments": [script, witness]}
        return self.run_and_read(document, witness)

    def test_a_shell_whose_own_command_is_missing_still_ends_with_its_own_127(self):
        self.assertEqual(self.shell_running("/nonexistent-command"), 127)

    def test_a_shell_whose_own_command_is_not_executable_still_ends_with_its_own_126(self):
        self.assertEqual(self.shell_running("/etc/passwd"), 126)
