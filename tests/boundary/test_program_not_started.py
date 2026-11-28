"""A program the box could not start, against a program that started and failed by itself, through
the real command in the real box.

The ending says the box was started and the program never reported running when bubblewrap
reports the executor forked and never reports the program's end (it reports it for every program
it executed, whatever the exit code); no exit code is read. That covers a program the box could
not execute and a box bubblewrap failed to make after the fork.
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


class TheBoxFailingAfterTheForkIsNotBlamedOnTheProgram(real_run.RealRun):
    def test_a_listed_folder_gone_before_the_launch_says_what_was_seen_and_both_things_to_look_at(
        self,
    ):
        doomed = os.path.join(self.root, "doomed")
        os.mkdir(doomed)
        witness = os.path.join(self.place, "witness.txt")
        script = self.script("fine.py", "import sys\nopen(sys.argv[1], 'w').close()\n")
        doc = self.document(script, [witness])
        doc["reach"]["visible"].append(doomed)
        # The gate runs after the input check and before the launch: a real race, no hook.
        doc["gates"] = [
            {
                "name": "remove",
                "command": real_run.INTERPRETER,
                "arguments": ["-c", f"import os; os.rmdir({doomed!r})"],
                "limit_seconds": 60,
            }
        ]
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "could_not_start"))
        ending = flat(self.outcome()["receipt"])["ending"]
        self.assertEqual(
            (ending["reason"], ending["failed_step"]), ("program_not_started", "launch")
        )
        line = ending["reason_text"]
        self.assertNotIn("was made", line)  # the box was the thing that failed
        self.assertIn("could not be made", line)
        self.assertIn("the program", line)
        self.assertFalse(os.path.exists(witness))


class AFileTheShellRunsInPlaceOfTheKernelIsNotToldApart(real_run.RealRun):
    """`execvp` hands a file the kernel will not execute to /bin/sh, so it is executed, as the
    shell, and ends as its own exit; this pins that as it is, not as a wish."""

    def test_an_elf_for_another_architecture_ends_as_the_programs_own_exit_not_told_apart(self):
        with open("/usr/bin/true", "rb") as f:
            data = bytearray(f.read())
        self.assertEqual(bytes(data[:4]), b"\x7fELF")
        data[18:20] = b"\x28\x00"  # e_machine: ARM
        path = os.path.join(self.support, "other-architecture")
        with open(path, "wb") as f:
            f.write(data)
        os.chmod(path, 0o755)
        doc = self.document("unused")
        doc["executor"]["settings"] = {"command": path, "arguments": []}
        code, lines, err = self.run_to_the_end(doc)
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        receipt = flat(self.outcome()["receipt"])
        self.assertEqual(receipt["ending"]["reason"], "none")
        self.assertIsInstance(receipt["execution"]["exit_code"], int)  # the shell's, whatever it is


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
