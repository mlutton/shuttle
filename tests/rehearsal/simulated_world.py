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
import hashlib
import os
import signal

from shuttle.core import boundary
from shuttle.core import place as place_decisions
from shuttle.core.shapes import (
    BoundaryOperations,
    ClockOperations,
    EnvironmentOperations,
    FileOperations,
    FreezeAnswer,
    GitOperations,
    IdentityOperations,
    NotARegularFile,
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
        self.input = b""  # what it was given on its standard input


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
        self.account_home = "/home/sim-user"  # the account's home folder; None for no home
        self.runtime = "/run/user/1000"  # the user's runtime folder, whatever the variables say
        self.variables = dict(environment or {})
        self.folders = set()
        self.dangling = set()  # names that lead nowhere
        self.links = {}  # name -> the name it leads to (which may be missing)
        self.special = set()  # names of named pipes, devices and sockets: not regular files
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
        self._temporary = 0
        self.read_only = set()  # names the owner may not write
        self.the_freeze = None  # None, "fails" (git ends with an error) or "times_out" (the limit)
        self.refs = {}  # reference -> commit, as the freeze made them
        self.commits = {}  # commit -> {"files": name to bytes, "parent": commit or None}
        self.places = {}  # place -> {"head": commit, "committed": {name: bytes}, "nested": [names]}
        self.operations = Operations(
            files=FileOperations(
                read=self._read,
                read_lines=self._read_lines,
                exists=self._exists,
                write_new=self._write_new,
                link=self._link,
                copy=self._copy,
                hash=self._hash,
                remove=self._remove,
                usable_folder=self._usable_folder,
                is_folder=self._is_folder,
                make_temporary_folder=self._make_temporary_folder,
                make_folders=self._make_folders,
                copy_path=self._copy_path,
                make_writable=self._make_writable,
                remove_tree=self._remove_tree,
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
                home_folder=self._home_folder,
                runtime_folder=self._runtime_folder,
            ),
            git=GitOperations(
                look_at_place=self._look_at_place,
                git_folders=self._git_folders,
                freeze=self._freeze,
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
        for name in (
            "kinds_with_statement.txt",
            "kinds_without_statement.txt",
            "statement_schema.json",
        ):
            path, data = _shipped(name)
            self.files[path] = bytearray(data)

    def make_place(self, path, files=None, nested=()):
        """A linked working copy at `path` whose commit holds `files` (name to text or bytes),
        all of them in the folder as committed. `nested` names folders that hold a repository."""
        self.make_folder(path)
        committed = {}
        for name, text in (files or {}).items():
            data = text if isinstance(text, bytes) else text.encode("utf-8")
            self.files[f"{path}/{name}"] = bytearray(data)
            self.make_folder(f"{path}/{name}".rpartition("/")[0])
            committed[name] = data
        head = self._commit(committed, None)
        self.places[path] = {
            "head": head,
            "committed": committed,
            "nested": list(nested),
            "filtered": [],
        }
        return head

    def _commit(self, files, parent):
        """Make a commit of `files` (name to bytes) and keep what it holds."""
        commit = hashlib.sha1(repr((parent, sorted(files.items()))).encode()).hexdigest()
        self.commits[commit] = {"files": dict(files), "parent": parent}
        return commit

    def commit_everything(self, path):
        """The place's own history moves: its files as they are now are committed on its branch."""
        held = self.places[path]
        held["committed"] = self._in_place(path)
        held["head"] = self._commit(held["committed"], held["head"])
        return held["head"]

    def put_a_name_that_leads_nowhere(self, path):
        self.dangling.add(path)

    def put_link(self, path, leads_to):
        self.links[path] = leads_to

    def put_pipe(self, path):
        self.special.add(path)

    def put_device(self, path):
        self.special.add(path)

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
        output="",
        writes=None,
        cannot_exec=False,
    ):
        """Say what starting `command` in the boundary makes: a child that exits at once with
        `exit_code`; or, with `hangs`, one that runs until the boundary is stopped; or, with
        `times_out`, one the boundary's timer ends (its scope fails with the result "timeout")
        the first time it is looked at. With `survives_stop` stopping the boundary does nothing.
        The child creates the named files as it starts. A child started in the boundary reports
        that it started, unless `fails_to_start` (the boundary's own tool exits with `exit_code`
        before the executor runs). With `cannot_exec` the box is made and reports the executor forked,
        then the program cannot be executed: the boundary's tool ends with status 1 and never
        reports an end (the real bubblewrap's way). A child that exits
        reports its end with `exit_code`. `cannot_exec` refuses a non-zero
        `exit_code`, `hangs`, `times_out` and `survives_stop`: such a program never runs. `report` is the text a child writes to the report it was given.
        `output` is the text it writes to its standard output when that is a file it was given
        (`output_to`); `writes` maps names to the text of files it makes as it starts."""
        assert not cannot_exec or (exit_code == 0 and not (hangs or times_out or survives_stop)), (
            "cannot_exec says nothing else: the program never runs, so no exit code and no hang"
        )
        self.programs[command] = {
            "hangs": hangs or times_out or survives_stop,
            "times_out": times_out,
            "survives_stop": survives_stop,
            "exit_code": exit_code,
            "creates": tuple(creates),
            "fails_to_start": fails_to_start,
            "cannot_exec": cannot_exec,
            "report": report,
            "output": output,
            "writes": dict(writes or {}),
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

    def _look(self, path, follow):
        """What the name holds, as the real world looks: "file", "folder", "special" (a pipe, a
        device, a socket) or "link" (when not following); FileNotFoundError when nothing is
        there, or a followed link leads nowhere."""
        for _ in range(40):
            if path in self.dangling:
                if follow:
                    break
                return "link", path
            if path in self.links:
                if not follow:
                    return "link", path
                path = self.links[path]
                continue
            if path in self.files:
                return "file", path
            if path in self.folders:
                return "folder", path
            if path in self.special:
                return "special", path
            break
        raise FileNotFoundError(path)

    def _regular(self, path, follow):
        """The name of the regular file behind `path`; what the real world raises otherwise."""
        kind, name = self._look(path, follow)
        if kind == "folder":
            raise IsADirectoryError(path)
        if kind != "file":
            raise NotARegularFile(path)
        return name

    def _read(self, path):
        self._enter("files.read", path)
        return bytes(self.files[self._regular(path, True)])

    def _read_lines(self, path, limit):
        self._enter("files.read_lines", path, limit)
        data = bytes(self.files[self._regular(path, True)])
        lines = data.split(b"\n")
        if lines[-1] == b"":
            lines.pop()  # the file ended with a line end, or is empty
        return iter([(line[:limit], len(line) > limit) for line in lines])

    def _exists(self, path):
        self._enter("files.exists", path)
        return self._taken(path)

    def _taken(self, path):
        return (
            path in self.files
            or path in self.folders
            or path in self.dangling
            or path in self.links
            or path in self.special
        )

    def _is_folder(self, path):
        self._enter("files.is_folder", path)
        return path in self.folders or self.links.get(path) in self.folders

    def _usable_folder(self, path):
        self._enter("files.usable_folder", path)
        return path in self.folders

    def _write_new(self, path, text):
        how, error = self._enter("files.write_new", path, text)
        if not self._parent_exists(path):
            raise FileNotFoundError(path)
        if self._taken(path):
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
        if self._taken(new):
            raise FileExistsError(new)
        self.files[new] = self.files[existing]

    def _copy(self, existing, new):
        self._enter("files.copy", existing, new)
        source = self._regular(existing, False)
        if not self._parent_exists(new):
            raise FileNotFoundError(existing)
        if self._taken(new):
            raise FileExistsError(new)
        self.files[new] = bytearray(self.files[source])  # its own bytes, not a shared name

    def _hash(self, path):
        self._enter("files.hash", path)
        return hashlib.sha256(bytes(self.files[self._regular(path, True)])).hexdigest()

    def _remove(self, path):
        self._enter("files.remove", path)
        if path in self.folders:
            raise IsADirectoryError(path)
        for names in (self.dangling, self.special):
            if path in names:
                names.remove(path)
                return
        if path in self.links:
            del self.links[path]
            return
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]

    def _make_temporary_folder(self, prefix):
        self._enter("files.make_temporary_folder", prefix)
        self._temporary += 1
        return self.make_folder(f"/tmp/{prefix}{self._temporary:06d}")

    def _make_folders(self, path):
        self._enter("files.make_folders", path)
        if path in self.files or path in self.links or path in self.special:
            raise FileExistsError(path)
        self.make_folder(path)

    def _below(self, path):
        """Every name held strictly below a folder, of any kind."""
        prefix = path + "/"
        held = [*self.files, *self.folders, *self.links, *self.dangling, *self.special]
        return sorted({name for name in held if name.startswith(prefix)})

    def _copy_path(self, existing, new, left_out):
        self._enter("files.copy_path", existing, new, tuple(left_out))
        kind, _ = self._look(existing, False)
        if kind == "link" or kind == "special":
            raise NotARegularFile(existing)
        if not self._parent_exists(new):
            raise FileNotFoundError(existing)
        if self._taken(new):
            raise FileExistsError(new)
        if kind == "file":
            self.files[new] = bytearray(self.files[existing])
            return
        left = [f"{existing}/{name}" for name in left_out]
        self.folders.add(new)
        for name in self._below(existing):
            if any(name == gone or name.startswith(gone + "/") for gone in left):
                continue
            target = new + name[len(existing) :]
            if name in self.files:
                self.files[target] = bytearray(self.files[name])
            elif name in self.folders:
                self.folders.add(target)

    def _make_writable(self, path):
        self._enter("files.make_writable", path)
        kind, _ = self._look(path, False)
        if kind == "link":
            raise NotARegularFile(path)
        self.read_only -= {path, *self._below(path)}

    def _remove_tree(self, path):
        self._enter("files.remove_tree", path)
        kind, _ = self._look(path, False)
        if kind != "folder":
            raise NotADirectoryError(path)
        for name in [*self._below(path), path]:
            self.files.pop(name, None)
            self.folders.discard(name)
            self.links.pop(name, None)
            self.dangling.discard(name)
            self.special.discard(name)

    def _find_program(self, command):
        self._enter("processes.find_program", command)
        if command not in self.programs:
            return None
        return command if command.startswith("/") else f"/usr/bin/{command}"

    def _open_report(self):
        self._enter("processes.open_report")
        self._reports += 1
        return 2 + self._reports

    def _what_runs(self, argv):
        """(the program and its arguments, the scope's unit or None, whether it is a gate)."""
        if not argv or argv[0] != "systemd-run":
            return list(argv), None, False
        unit = next(p.split("=", 1)[1] for p in argv if p.startswith("--unit=")) + ".scope"
        # the scope tool turns each "$$" back into "$" before it starts the command
        inside = [p.replace("$$", "$") for p in list(argv)[list(argv).index("--") + 1 :]]
        if inside[:3] == ["sh", "-c", boundary.GATE_SCRIPT]:  # sh, its report descriptor, the gate
            return inside[5:], unit, True
        if inside[:1] == ["bwrap"]:  # the box, then the executor
            return inside[inside.index("--") + 1 :], unit, False
        return inside, unit, False

    def _check_output_name(self, output_to):
        if output_to is not None:
            if self._taken(output_to):
                raise FileExistsError(output_to)
            if not self._parent_exists(output_to):
                raise FileNotFoundError(output_to)

    def _make_files(self, behaviour, output_to):
        """What a child leaves as it starts: the files it creates and its standard output."""
        for name in behaviour["creates"]:
            self.files[name] = bytearray(b"1")
        for name, text in behaviour["writes"].items():
            self.files[name] = bytearray(text.encode("utf-8"))
        if output_to is not None:
            self.files[output_to] = bytearray(behaviour["output"].encode("utf-8"))

    def _start(self, argv, environment, report=None, input_from=None, output_to=None):
        self._enter("processes.start", list(argv), dict(environment), input_from)
        given = b"" if input_from is None else self.files[self._regular(input_from, True)]
        self._check_output_name(output_to)
        if any("\0" in part for part in argv):
            raise ValueError("embedded null byte")
        executor, unit, gate = self._what_runs(argv)
        if not executor or executor[0] not in self.programs:
            raise FileNotFoundError(executor[0] if executor else "")
        behaviour = self.programs[executor[0]]
        self._make_files(behaviour, output_to)
        self.started.append((list(argv), dict(environment)))
        child = _Child(executor, behaviour, unit)
        child.input = bytes(given)
        if not behaviour["hangs"]:
            child.returncode = 1 if behaviour["cannot_exec"] else behaviour["exit_code"]
        if report is not None:
            if gate:
                child.report = "" if behaviour["fails_to_start"] else boundary.GATE_STARTED + "\n"
            elif behaviour["report"] is not None:
                child.report = behaviour["report"]
            elif not behaviour["fails_to_start"]:
                child.report = '{"child-pid": 2}\n'
                if not behaviour["hangs"] and not behaviour["cannot_exec"]:
                    child.report += f'{{"exit-code": {behaviour["exit_code"]}}}\n'
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
        return self._status_after_the_timer(child)

    def _status_after_the_timer(self, child):
        if child.returncode is None and child.behaviour["times_out"]:
            child.returncode = -signal.SIGTERM
            self.units[child.unit] = dict(_TIMED_OUT)
        return self._status(child)

    def _wait_for_exit(self, child, seconds):
        self._enter("processes.wait", child.argv, seconds)
        self._waits += 1
        assert self._waits < WAITS_BEFORE_GIVING_UP, "the run would wait forever"
        return self._status_after_the_timer(child)

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
        for _ in range(40):
            if path not in self.links:
                break
            path = self.links[path]
        return path

    def _in_place(self, place):
        """The files of a place as they are now: name to bytes."""
        prefix = place + "/"
        return {
            name[len(prefix) :]: bytes(data)
            for name, data in self.files.items()
            if name.startswith(prefix)
        }

    def _look_at_place(self, place, environment):
        self._enter("git.look_at_place", place, dict(environment))
        nothing = {
            "is_checkout": False,
            "head": None,
            "unclean": [],
            "nested": [],
            "filtered": [],
        }
        if place not in self.folders:
            return {"exists": False, **nothing}
        held = self.places.get(place)
        if held is None:
            return {"exists": True, **nothing}
        if held.get("filtered"):
            return {
                **nothing,
                "exists": True,
                "is_checkout": True,
                "head": held["head"],
                "filtered": sorted(held["filtered"]),
            }
        now, committed = self._in_place(place), held["committed"]
        unclean = sorted(
            name for name in {*now, *committed} if now.get(name) != committed.get(name)
        )
        return {
            "exists": True,
            "is_checkout": True,
            "head": held["head"],
            "unclean": unclean,
            "nested": [  # a repository inside another is not entered
                name
                for name in held["nested"]
                if not any(name.startswith(other + "/") for other in held["nested"])
            ],
            "filtered": [],
        }

    def _git_folders(self, place, environment):
        self._enter("git.git_folders", place, dict(environment))
        held = self.places.get(place)
        if held is None:
            return []
        return list(held.get("git_folders", [f"{place}/.git"]))

    def _freeze(self, command, environment):
        """Run the freeze's command: the scope's tool around the freeze script. The files of the
        place now are what is frozen; what the real script prints is printed."""
        self._enter("git.freeze", list(command), dict(environment))
        if not command or command[0] != "systemd-run":
            raise FileNotFoundError(command[0] if command else "")
        unit = next(p.split("=", 1)[1] for p in command if p.startswith("--unit=")) + ".scope"
        inside = [p.replace("$$", "$") for p in list(command)[list(command).index("--") + 1 :]]
        assert inside[:3] == ["sh", "-c", place_decisions.FREEZE_SCRIPT], inside
        place, opening = inside[4], inside[5]
        if self.the_freeze == "times_out":
            self.units[unit] = dict(_TIMED_OUT)
            return FreezeAnswer(-signal.SIGTERM, b"")
        held, was = self.places.get(place), self.commits.get(opening)
        if self.the_freeze == "fails" or held is None or was is None:
            return FreezeAnswer(128, b"")
        now, committed = self._in_place(place), was["files"]
        if now == committed:
            commit = opening
        else:
            commit = self._commit(now, opening)
            self.refs[inside[6]] = commit
        counts = (
            len([n for n in now if n not in committed]),
            len([n for n in now if n in committed and now[n] != committed[n]]),
            len([n for n in committed if n not in now]),
        )
        text = (
            f"commit {commit}\nadded {counts[0]}\nchanged {counts[1]}\ndeleted {counts[2]}\ndone\n"
        )
        return FreezeAnswer(0, text.encode())

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

    def _home_folder(self):
        self._enter("identity.home_folder")
        return self.account_home

    def _runtime_folder(self):
        self._enter("identity.runtime_folder")
        return self.runtime

    def _new_id(self):
        self._enter("identity.new_id")
        self._ids += 1
        return f"{self._ids:032x}"
