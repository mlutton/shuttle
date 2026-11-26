"""A world held in memory, to pass in where the real operations would be.

`SimulatedWorld().operations` is an `Operations` (shuttle.core.shapes) whose functions act on
dictionaries and a clock that moves only when something waits. Nothing here touches the real
disk, a real process or real time.

It can fail any operation at any point, so a fault that would need a full disk, a process that
will not end or a signal at an awkward moment is a line in a test:

    world.will_raise("files.link", OSError("injected"))            # the first call raises
    world.will_raise("files.write_new", OSError("full"), nth=2)    # the second call raises
    world.will_stop_half_way("files.write_new")                    # half the text is there, then it raises
    world.will_stop_half_way("files.write_new", how="unflushed")   # all of it, never flushed, then it raises
    world.program("tool", obeys=())                                # a process that will not end
    world.on_call("processes.poll", nth=3, do=lambda: world.deliver("SIGINT"))  # a signal, there

It is held to the real operations by the contract cases in contract.py.
"""

import datetime
import signal

from shuttle.core.shapes import (
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
    def __init__(self, argv, behaviour, started_at):
        self.argv = list(argv)
        self.behaviour = behaviour
        self.started_at = started_at
        self.returncode = None


class SimulatedWorld:
    def __init__(self, host="sim-host", environment=None):
        self.t = 0.0  # seconds on the simulated clock
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
        self._events = []  # (time, function) run when the clock reaches them
        self._handlers = []
        self._ids = 0
        self.operations = Operations(
            files=FileOperations(
                read=self._read,
                exists=self._exists,
                write_new=self._write_new,
                link=self._link,
                remove=self._remove,
            ),
            processes=ProcessOperations(
                find_program=self._find_program,
                start=self._start,
                poll=self._poll,
                ask_to_end=self._ask_to_end,
                kill=self._kill,
            ),
            clock=ClockOperations(now=self._now, timestamp=self._timestamp, wait=self._wait),
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

    def put_a_name_that_leads_nowhere(self, path):
        self.dangling.add(path)

    def text_of(self, path):
        return bytes(self.files[path]).decode("utf-8")

    def names_in(self, folder):
        prefix = folder + "/"
        return sorted(n[len(prefix) :] for n in self.files if n.startswith(prefix))

    def program(
        self, command, exits_after=None, exit_code=0, obeys=("ask_to_end", "kill"), creates=()
    ):
        """Say what starting `command` makes: a child that exits by itself `exits_after` seconds
        after it starts (never, if None) with `exit_code`, ends when asked or killed only if
        `obeys` says so, and creates the named files as it starts."""
        self.programs[command] = {
            "exits_after": exits_after,
            "exit_code": exit_code,
            "obeys": tuple(obeys),
            "creates": tuple(creates),
        }

    def at(self, seconds, do):
        """Run `do` when the clock reaches `seconds` (while something waits)."""
        self._events.append((seconds, do))
        self._events.sort(key=lambda pair: pair[0])

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

    def _start(self, argv, environment):
        self._enter("processes.start", list(argv), dict(environment))
        if any("\0" in part for part in argv):
            raise ValueError("embedded null byte")
        if not argv or argv[0] not in self.programs:
            raise FileNotFoundError(argv[0] if argv else "")
        behaviour = self.programs[argv[0]]
        for name in behaviour["creates"]:
            self.files[name] = bytearray(b"1")
        self.started.append((list(argv), dict(environment)))
        child = _Child(argv, behaviour, self.t)
        self.children.append(child)
        return child

    def _status(self, child):
        due = child.behaviour["exits_after"]
        if child.returncode is None and due is not None and self.t >= child.started_at + due:
            child.returncode = child.behaviour["exit_code"]
        return child.returncode

    def _poll(self, child):
        self._enter("processes.poll", child.argv)
        return self._status(child)

    def _request(self, operation, child, request, number):
        self._enter(operation, child.argv)
        if self._status(child) is None and request in child.behaviour["obeys"]:
            child.returncode = -number

    def _ask_to_end(self, child):
        self._request("processes.ask_to_end", child, "ask_to_end", signal.SIGTERM)

    def _kill(self, child):
        self._request("processes.kill", child, "kill", signal.SIGKILL)

    def _now(self):
        self._enter("clock.now")
        return self.t

    def _timestamp(self):
        self._enter("clock.timestamp")
        return (EPOCH + datetime.timedelta(seconds=self.t)).isoformat(timespec="milliseconds")

    def _wait(self, seconds):
        self._enter("clock.wait", seconds)
        if seconds < 0:
            raise ValueError("sleep length must be non-negative")
        self.t += seconds
        while self._events and self._events[0][0] <= self.t:
            self._events.pop(0)[1]()

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
