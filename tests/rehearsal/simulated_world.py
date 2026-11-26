"""A world held in memory, to pass in where the real operations would be.

`SimulatedWorld().operations` is an `Operations` (shuttle.core.shapes) whose functions act on
dictionaries and a clock that does not move. Nothing here touches the real disk, a real process,
the real boundary or real time.

It can fail any operation at any point, so a fault that would need a full disk, a process that
will not end or a signal at an awkward moment is a line in a test:

    world.will_raise("files.link", OSError("injected"))            # the first call raises
    world.will_raise("files.write_new", OSError("full"), nth=2)    # the second call raises
    world.will_stop_half_way("files.write_new")                    # half the text is there, then it raises
    world.will_stop_half_way("files.write_new", how="unflushed")   # all of it, never flushed, then it raises
    world.program("tool", hangs=True, survives_stop=True)          # a boundary that will not empty
    world.on_call("processes.poll", nth=3, do=lambda: world.deliver("SIGINT"))  # a signal, there

It is held to the real operations by the contract cases in contract.py.
"""

import datetime
import os
import signal

from shuttle.core.shapes import (
    BoundaryOperations,
    ClockOperations,
    EnvironmentOperations,
    FileOperations,
    IdentityOperations,
    Operations,
    ProcessOperations,
    SignalOperations,
)

HANDLED = ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT", "SIGUSR1", "SIGUSR2", "SIGALRM")
EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


class _Child:
    def __init__(self, argv, behaviour, unit):
        self.argv = list(argv)
        self.behaviour = behaviour
        self.unit = unit
        self.returncode = None
        self.report = ""


_GONE = {"LoadState": "not-found", "ActiveState": "inactive", "Result": "success"}
_STILL_THERE = {"LoadState": "loaded", "ActiveState": "active", "Result": "success"}
_TIMED_OUT = {"LoadState": "loaded", "ActiveState": "failed", "Result": "timeout"}
WAITS_BEFORE_GIVING_UP = 1000  # a wait that would never end is a failure of the test


def _shipped(name):
    """A file shipped with the package, as the real world holds it."""
    folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(folder, "shuttle", "data", name)
    with open(path, "rb") as f:
        return path, f.read()


class SimulatedWorld:
    def __init__(self, host="sim-host", environment=None):
        self.t = 0.0  # seconds on the simulated clock, which does not move
        self.host = host
        self.pid = 4242  # what the simulated process is numbered
        self.variables = dict(environment or {})
        self.folders = set()
        self.dangling = set()  # names that lead nowhere
        self.files = {}  # name -> bytearray; a linked name shares the bytearray
        self.programs = {}  # command -> behaviour
        self.started = []  # (argv, environment) of every start
        self.children = []  # every child started
        self.counts = {}  # operation -> number of calls so far
        self.log = []  # (operation, arguments, time) of every call, in order
        self._plan = []
        self._hooks = []
        self.units = {}  # unit name -> its properties; a unit not here is gone
        self._waits = 0
        self._reports = 0
        self._handlers = []
        self._ids = 0
        self.operations = Operations(
            files=FileOperations(
                read=self._read,
                exists=self._exists,
                write_new=self._write_new,
                link=self._link,
                remove=self._remove,
                usable_folder=self._usable_folder,
            ),
            processes=ProcessOperations(
                find_program=self._find_program,
                start=self._start,
                poll=self._poll,
                wait=self._wait_for_exit,
                open_report=self._open_report,
                read_report=self._read_report,
            ),
            boundary=BoundaryOperations(
                show=self._show, stop=self._stop, forget=self._forget, resolve=self._resolve
            ),
            clock=ClockOperations(now=self._now, timestamp=self._timestamp),
            signals=SignalOperations(install=self._install, name_of=self._name_of),
            environment=EnvironmentOperations(read_variable=self._read_variable),
            identity=IdentityOperations(
                host_name=self._host_name,
                new_id=self._new_id,
                process_number=self._process_number,
            ),
        )

    # ------------------------------------------------------------ setting the scene

    def make_folder(self, path):
        """The folder and every folder above it; returns the path."""
        above = path
        while above:
            self.folders.add(above)
            above = above.rpartition("/")[0]
        return path

    def put_file(self, path, text):
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        self.files[path] = bytearray(data)

    def put_shipped_data(self):
        """The data files shipped with the package, which a run reads (the kinds)."""
        for name in ("kinds_with_statement.txt", "kinds_without_statement.txt"):
            path, data = _shipped(name)
            self.files[path] = bytearray(data)

    def put_a_name_that_leads_nowhere(self, path):
        self.dangling.add(path)

    def text_of(self, path):
        return bytes(self.files[path]).decode("utf-8")

    def names_in(self, folder):
        prefix = folder + "/"
        return sorted(n[len(prefix) :] for n in self.files if n.startswith(prefix))

    def program(
        self,
        command,
        hangs=False,
        times_out=False,
        survives_stop=False,
        exit_code=0,
        creates=(),
        fails_to_start=False,
        report=None,
    ):
        """Say what starting `command` in the boundary makes: a child that exits at once with
        `exit_code`; or, with `hangs`, one that runs until the boundary is stopped; or, with
        `times_out`, one the boundary's timer ends (its scope fails with the result "timeout")
        the first time it is looked at. With `survives_stop` stopping the boundary does nothing.
        The child creates the named files as it starts. A child started in the boundary reports
        that it started, unless `fails_to_start` (the boundary's own tool exits with `exit_code`
        before the executor runs); `report` is the text a child writes to the report it was given."""
        self.programs[command] = {
            "hangs": hangs or times_out or survives_stop,
            "times_out": times_out,
            "survives_stop": survives_stop,
            "exit_code": exit_code,
            "creates": tuple(creates),
            "fails_to_start": fails_to_start,
            "report": report,
        }

    # ------------------------------------------------------------ making things fail

    def will_raise(self, operation, error, nth=1):
        """The `nth` call to `operation` (every call if None) raises `error` and does nothing."""
        self._plan.append((operation, nth, "raise", error))

    def will_stop_half_way(self, operation="files.write_new", nth=1, how="half"):
        """The `nth` call to a file write leaves part of the text under the name and raises
        OSError: how="half" leaves half of it, how="unflushed" all of it (written, never flushed)."""
        assert operation == "files.write_new" and how in ("half", "unflushed")
        self._plan.append((operation, nth, how, OSError(f"injected: stopped {how}")))

    def on_call(self, operation, do, nth=1):
        """Run `do` just before the `nth` call to `operation` (every call if None) acts."""
        self._hooks.append((operation, nth, do))

    def deliver(self, name):
        """A signal arrives now: the handler installed last is called with its name.

        Returns whether a handler caught it. False means the signal's default action would have
        applied to the real command (it would have died), which a test can assert never happens.
        """
        if self._handlers and name in HANDLED:  # the real handlers are for these signals only
            self._handlers[-1](name)
            return True
        return False

    def have_previous_handler(self, handler):
        """Something was installed before the run's own handler (for the contract's restore case)."""
        self._handlers.append(handler)

    def every_child_has_ended(self):
        return all(self._status(child) is not None for child in self.children)

    def calls(self, operation):
        return [(args, t) for op, args, t in self.log if op == operation]

    # ------------------------------------------------------------ the operations

    def _enter(self, operation, *arguments):
        number = self.counts[operation] = self.counts.get(operation, 0) + 1
        self.log.append((operation, arguments, self.t))
        for op, nth, do in list(self._hooks):
            if op == operation and nth in (None, number):
                do()
        for op, nth, kind, error in self._plan:
            if op == operation and nth in (None, number):
                if kind == "raise":
                    raise error
                return kind, error
        return None, None

    def _parent_exists(self, path):
        parent = path.rpartition("/")[0]
        return parent == "" or parent in self.folders

    def _read(self, path):
        self._enter("files.read", path)
        if path in self.files:
            return bytes(self.files[path])
        if path in self.folders:
            raise IsADirectoryError(path)
        raise FileNotFoundError(path)

    def _exists(self, path):
        self._enter("files.exists", path)
        return path in self.files or path in self.folders or path in self.dangling

    def _usable_folder(self, path):
        self._enter("files.usable_folder", path)
        return path in self.folders

    def _write_new(self, path, text):
        how, error = self._enter("files.write_new", path, text)
        if not self._parent_exists(path):
            raise FileNotFoundError(path)
        if path in self.files or path in self.folders or path in self.dangling:
            raise FileExistsError(path)
        self.files[path] = bytearray()
        data = text.encode("utf-8")  # a lone surrogate raises here, after the file is made
        if how == "half":
            self.files[path] += data[: len(data) // 2]
            raise error
        self.files[path] += data
        if how == "unflushed":
            raise error

    def _link(self, existing, new):
        self._enter("files.link", existing, new)
        if existing in self.folders:
            raise PermissionError(existing)
        if existing not in self.files or not self._parent_exists(new):
            raise FileNotFoundError(existing)
        if new in self.files or new in self.folders or new in self.dangling:
            raise FileExistsError(new)
        self.files[new] = self.files[existing]

    def _remove(self, path):
        self._enter("files.remove", path)
        if path in self.folders:
            raise IsADirectoryError(path)
        if path in self.dangling:
            self.dangling.remove(path)
            return
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]

    def _find_program(self, command):
        self._enter("processes.find_program", command)
        return command in self.programs

    def _open_report(self):
        self._enter("processes.open_report")
        self._reports += 1
        return 2 + self._reports

    def _start(self, argv, environment, report=None):
        self._enter("processes.start", list(argv), dict(environment))
        if any("\0" in part for part in argv):
            raise ValueError("embedded null byte")
        executor, unit = list(argv), None
        if (
            argv and argv[0] == "systemd-run"
        ):  # the boundary's command: its unit, then the executor's
            unit = next(p.split("=", 1)[1] for p in argv if p.startswith("--unit=")) + ".scope"
            after_bwrap = list(argv)[list(argv).index("bwrap") :]
            executor = after_bwrap[after_bwrap.index("--") + 1 :]
        if not executor or executor[0] not in self.programs:
            raise FileNotFoundError(executor[0] if executor else "")
        behaviour = self.programs[executor[0]]
        for name in behaviour["creates"]:
            self.files[name] = bytearray(b"1")
        self.started.append((list(argv), dict(environment)))
        child = _Child(executor, behaviour, unit)
        if not behaviour["hangs"]:
            child.returncode = behaviour["exit_code"]
        if report is not None:
            if behaviour["report"] is not None:
                child.report = behaviour["report"]
            elif not behaviour["fails_to_start"]:
                child.report = '{"child-pid": 2}\n'
        if unit:
            self.units[unit] = dict(_STILL_THERE)
        self.children.append(child)
        return child

    def _read_report(self, child):
        self._enter("processes.read_report", child.argv)
        return child.report

    def _status(self, child):
        return child.returncode

    def _poll(self, child):
        self._enter("processes.poll", child.argv)
        if child.returncode is None and child.behaviour["times_out"]:
            child.returncode = -signal.SIGTERM
            self.units[child.unit] = dict(_TIMED_OUT)
        return self._status(child)

    def _wait_for_exit(self, child, seconds):
        self._enter("processes.wait", child.argv, seconds)
        self._waits += 1
        assert self._waits < WAITS_BEFORE_GIVING_UP, "the run would wait forever"
        return self._status(child)

    def _show(self, unit, properties):
        self._enter("boundary.show", unit, tuple(properties))
        held = self.units.get(unit, _GONE)
        return {name: held[name] for name in properties if name in held}

    def _stop(self, unit):
        self._enter("boundary.stop", unit)
        for child in self.children:
            if child.unit == unit and not child.behaviour["survives_stop"]:
                if child.returncode is None:
                    child.returncode = -signal.SIGTERM
                if self.units.get(unit, _GONE)["ActiveState"] == "active":
                    self.units.pop(unit, None)

    def _forget(self, unit):
        self._enter("boundary.forget", unit)
        if self.units.get(unit, _GONE)["ActiveState"] == "failed":
            self.units.pop(unit, None)

    def _resolve(self, path):
        self._enter("boundary.resolve", path)
        return path

    def _now(self):
        self._enter("clock.now")
        return self.t

    def _timestamp(self):
        self._enter("clock.timestamp")
        return (EPOCH + datetime.timedelta(seconds=self.t)).isoformat(timespec="milliseconds")

    def _install(self, on_signal):
        self._enter("signals.install")
        self._handlers.append(on_signal)
        installed = on_signal

        def restore():
            if installed in self._handlers:
                self._handlers.remove(installed)

        return restore

    def _name_of(self, number):
        self._enter("signals.name_of", number)
        try:
            return signal.Signals(number).name
        except ValueError:
            return None

    def _read_variable(self, name):
        self._enter("environment.read_variable", name)
        return self.variables.get(name)

    def _host_name(self):
        self._enter("identity.host_name")
        return self.host

    def _process_number(self):
        self._enter("identity.process_number")
        return self.pid

    def _new_id(self):
        self._enter("identity.new_id")
        self._ids += 1
        return f"{self._ids:032x}"
