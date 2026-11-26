"""The cases every set of operations is held to: the real one and the simulated one.

`ContractCases` is a mixin. A test class that mixes it in with unittest.TestCase sets
`self.world` (an Operations) and `self.harness` (what a case needs that is not an operation:
a fresh folder, a listing of it, a program to start, a signal to send). The real half is
tests/command/test_world_contract.py (a temporary folder, real short-lived child processes);
the simulated half is tests/by_value/test_world_contract.py. Both must pass every case: a
case the simulated world cannot honestly model is a finding to report, not a case to drop.
Where a case is not here for that reason, UNMODELLED says so.

Each case's name says the invariant. The waits are on the operations' own clock, bounded, and
end as soon as what is waited for has happened.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAMES = importlib.import_module("hostile.names_table").NAMES

# What the simulated world cannot honestly do, so no case exists for it (reported in the
# pull request): it runs no program, so it cannot show which environment a child sees, what
# a real child prints or writes, or that a real child's exit status is the program's own.
UNMODELLED = (
    "the environment a started child really sees",
    "what a started child really does beyond the behaviour declared for it",
)

HOLDABLE_NAMES = [row for row in NAMES if row["holdable"] and not row["path"]]
HANDLED_SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP")
TEXT = "line one\nline two \u00e9 \u2713\n"


def until(world, done, seconds=5.0):
    """Wait on the world's own clock until done() is true; False if the time ran out. Bounded
    by the number of waits too, so a clock that never moves ends the wait instead of hanging it."""
    end = world.clock.now() + seconds
    for _ in range(int(seconds / 0.01) + 1):
        if done():
            return True
        if world.clock.now() >= end:
            return False
        world.clock.wait(0.01)
    return done()


class ContractCases:
    # ------------------------------------------------------------------ files

    def fresh(self, name="a-file"):
        return f"{self.harness.folder()}/{name}"

    def test_a_text_put_in_place_reads_back_whole_as_utf_8(self):
        path = self.fresh()
        self.world.files.write_new(path, TEXT)
        self.assertEqual(self.world.files.read(path), TEXT.encode("utf-8"))

    def test_a_new_file_that_is_not_there_yet_is_not_there_and_then_is(self):
        path = self.fresh()
        self.assertFalse(self.world.files.exists(path))
        self.world.files.write_new(path, "x")
        self.assertTrue(self.world.files.exists(path))
        self.world.files.remove(path)
        self.assertFalse(self.world.files.exists(path))

    def test_writing_a_new_file_over_a_name_that_is_there_raises_file_exists_and_changes_nothing(
        self,
    ):
        path = self.fresh()
        self.world.files.write_new(path, "first")
        with self.assertRaises(FileExistsError):
            self.world.files.write_new(path, "second")
        self.assertEqual(self.world.files.read(path), b"first")

    def test_writing_a_new_file_in_a_folder_that_is_not_there_raises_and_makes_nothing(self):
        folder = self.harness.folder()
        with self.assertRaises(OSError):
            self.world.files.write_new(f"{folder}/absent/file", "x")
        self.assertEqual(self.harness.names_in(folder), [])

    def test_a_text_that_cannot_be_encoded_raises_a_value_error(self):
        with self.assertRaises(ValueError):
            self.world.files.write_new(self.fresh(), "lone surrogate \ud800")

    def test_a_linked_name_reads_the_same_and_outlives_the_removal_of_the_first(self):
        first, second = self.fresh("first"), self.fresh("second")
        self.world.files.write_new(first, TEXT)
        self.world.files.link(first, second)
        self.assertEqual(self.world.files.read(second), TEXT.encode("utf-8"))
        self.world.files.remove(first)
        self.assertFalse(self.world.files.exists(first))
        self.assertEqual(self.world.files.read(second), TEXT.encode("utf-8"))

    def test_linking_onto_a_name_that_is_there_raises_file_exists_and_changes_neither(self):
        first, second = self.fresh("first"), self.fresh("second")
        self.world.files.write_new(first, "one")
        self.world.files.write_new(second, "two")
        with self.assertRaises(FileExistsError):
            self.world.files.link(first, second)
        self.assertEqual(self.world.files.read(first), b"one")
        self.assertEqual(self.world.files.read(second), b"two")

    def test_linking_from_a_name_that_is_not_there_raises_and_makes_nothing(self):
        folder = self.harness.folder()
        with self.assertRaises(OSError):
            self.world.files.link(f"{folder}/absent", f"{folder}/new")
        self.assertEqual(self.harness.names_in(folder), [])

    def test_removing_a_name_that_is_not_there_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.world.files.remove(self.fresh("absent"))

    def test_reading_a_name_that_is_not_there_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.world.files.read(self.fresh("absent"))

    def test_reading_a_folder_raises_an_os_error(self):
        with self.assertRaises(OSError):
            self.world.files.read(self.harness.folder())

    def test_a_record_put_in_place_under_every_name_the_filesystem_will_hold_reads_back_whole(self):
        # tests/hostile/names_table.py: the rows that are one name (not a path of several parts)
        folder = self.harness.folder()
        for row in HOLDABLE_NAMES:
            with self.subTest(label=row["label"]):
                path = f"{folder}/{row['name']}"
                alias = f"{folder}/linked-{len(self.harness.names_in(folder))}"
                self.world.files.write_new(path, TEXT)
                self.assertTrue(self.world.files.exists(path))
                self.assertEqual(self.world.files.read(path), TEXT.encode("utf-8"))
                self.assertIn(row["name"], self.harness.names_in(folder))
                self.world.files.link(path, alias)
                self.world.files.remove(path)
                self.assertEqual(self.world.files.read(alias), TEXT.encode("utf-8"))
                self.world.files.remove(alias)
                self.assertNotIn(row["name"], self.harness.names_in(folder))

    # -------------------------------------------------------------- processes

    def start(self, kind, **extra):
        argv = self.harness.argv(kind, **extra)
        process = self.world.processes.start(argv, self.harness.environment())
        self.addCleanup(self.stop, process)
        return process

    def stop(self, process):
        self.world.processes.kill(process)
        until(self.world, lambda: self.world.processes.poll(process) is not None)

    def ended(self, process):
        return until(self.world, lambda: self.world.processes.poll(process) is not None)

    def test_a_program_that_can_be_found_is_found_and_one_that_cannot_is_not(self):
        self.assertTrue(self.world.processes.find_program(self.harness.argv("exits_at_once")[0]))
        self.assertFalse(self.world.processes.find_program(self.harness.argv("not_a_program")[0]))
        self.assertFalse(self.world.processes.find_program("a\0b"))

    def test_a_program_that_exits_by_itself_ends_with_its_exit_status_and_keeps_it(self):
        for kind, status in (("exits_at_once", 0), ("exits_with_three", 3)):
            with self.subTest(kind):
                process = self.start(kind)
                self.assertTrue(self.ended(process))
                self.assertEqual(self.world.processes.poll(process), status)
                self.assertEqual(self.world.processes.poll(process), status)

    def test_starting_a_program_that_cannot_be_found_raises_an_os_error(self):
        with self.assertRaises(OSError):
            self.world.processes.start(
                self.harness.argv("not_a_program"), self.harness.environment()
            )

    def test_starting_a_program_with_an_argument_holding_a_null_character_raises_a_value_error(
        self,
    ):
        argv = [*self.harness.argv("exits_at_once"), "a\0b"]
        with self.assertRaises(ValueError):
            self.world.processes.start(argv, self.harness.environment())

    def test_a_running_program_polls_none_and_ends_with_the_ask_by_the_terminate_signal(self):
        process = self.start("sleeps")
        self.assertIsNone(self.world.processes.poll(process))
        self.world.processes.ask_to_end(process)
        self.assertTrue(self.ended(process))
        self.assertEqual(self.world.processes.poll(process), -15)

    def test_a_program_that_ignores_the_ask_is_still_there_until_it_is_killed(self):
        ready = self.fresh("ready")
        process = self.start("ignores_the_ask", ready=ready)
        self.assertTrue(until(self.world, lambda: self.world.files.exists(ready)))
        self.world.processes.ask_to_end(process)
        self.assertFalse(
            until(self.world, lambda: self.world.processes.poll(process) is not None, 0.1)
        )
        self.world.processes.kill(process)
        self.assertTrue(self.ended(process))
        self.assertEqual(self.world.processes.poll(process), -9)

    def test_asking_or_killing_a_program_that_has_ended_changes_nothing(self):
        process = self.start("exits_with_three")
        self.assertTrue(self.ended(process))
        self.world.processes.ask_to_end(process)
        self.world.processes.kill(process)
        self.assertEqual(self.world.processes.poll(process), 3)

    # ------------------------------------------------------------------ clock

    def test_the_clock_only_goes_forward_and_waiting_moves_it_by_at_least_the_wait(self):
        before = self.world.clock.now()
        self.world.clock.wait(0.02)
        after = self.world.clock.now()
        self.assertGreaterEqual(after - before, 0.02 - 0.001)
        self.assertGreaterEqual(self.world.clock.now(), after)

    def test_a_timestamp_is_utc_iso_with_milliseconds(self):
        self.assertRegex(
            self.world.clock.timestamp(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$"
        )

    def test_a_later_timestamp_is_not_before_an_earlier_one(self):
        first = self.world.clock.timestamp()
        self.world.clock.wait(0.01)
        self.assertGreaterEqual(self.world.clock.timestamp(), first)

    # ---------------------------------------------------------------- signals

    def test_each_signal_calls_the_handler_with_its_name_and_the_undo_gives_the_old_handler_back(
        self,
    ):
        for name in HANDLED_SIGNALS:
            with self.subTest(name):
                earlier, mine = [], []
                self.harness.have_previous_handler(earlier.append)
                restore = self.world.signals.install(mine.append)
                self.harness.send(name)
                self.assertEqual((mine, earlier), ([name], []))
                restore()
                self.harness.send(name)
                self.assertEqual((mine, earlier), ([name], [name]))

    def test_a_signal_number_has_its_name_or_none(self):
        self.assertEqual(self.world.signals.name_of(15), "SIGTERM")
        self.assertEqual(self.world.signals.name_of(9), "SIGKILL")
        self.assertEqual(self.world.signals.name_of(2), "SIGINT")
        self.assertIsNone(self.world.signals.name_of(99999))

    # ------------------------------------------------- environment and identity

    def test_a_variable_that_is_set_reads_back_exactly_one_that_is_empty_reads_empty_and_one_that_is_not_set_reads_none(
        self,
    ):
        self.harness.set_variable("SHUTTLE_CONTRACT_SET", "a value = with \u00e9")
        self.harness.set_variable("SHUTTLE_CONTRACT_EMPTY", "")
        read = self.world.environment.read_variable
        self.assertEqual(read("SHUTTLE_CONTRACT_SET"), "a value = with \u00e9")
        self.assertEqual(read("SHUTTLE_CONTRACT_EMPTY"), "")
        self.assertIsNone(read("SHUTTLE_CONTRACT_NOT_SET"))

    def test_the_host_name_is_some_text(self):
        name = self.world.identity.host_name()
        self.assertIsInstance(name, str)
        self.assertTrue(name)

    def test_new_ids_are_letters_and_digits_only_and_never_the_same_twice(self):
        ids = [self.world.identity.new_id() for _ in range(50)]
        self.assertTrue(all(isinstance(i, str) and i.isascii() and i.isalnum() for i in ids))
        self.assertEqual(len(set(ids)), 50)
