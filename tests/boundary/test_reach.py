"""The executor's reach, through the real command in the real box: hidden unless declared.

A real script is the executor. It tries each thing the reach is about (listing and reading what is
hidden, reading and writing what is read-only, writing what is writable, asking the user's systemd
for anything) and reports one word for each; the test asserts only that report and what is left on
the machine afterwards. The reach limits the damage of a lost or confused agent; these tests are
not a proof against an attacker.

The same table holds wherever the test's own folders live: under the machine's temporary folder
(the common case in this suite, and a place the box binds over with the executor's own `/tmp`),
and under another folder (`/var/tmp`) that the box does not bind unless it is asked to. The run
area is made in the temporary folder or in the other, by the variable the command reads.

None keeps time. The pure order of the box's arguments is pinned in tests/by_value/test_box.py.
"""

import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
real_run = importlib.import_module("rehearsal.real_run")

# Another folder for scratch files that is not the machine's temporary folder and is there, and
# can be written, on a typical machine and on the hosted runner.
OTHER_SCRATCH = "/var/tmp"

# argv 1 is a JSON file naming what to try; the report is written in the place (argv 2). Each
# attempt is one word: "ok" when it worked, "refused" when the system refused it (an OSError), or
# "error" with the name of what went wrong.
PROBE = r"""
import ctypes, json, os, socket, subprocess, sys

targets = json.load(open(sys.argv[1]))
report = {}


def attempt(name, action):
    try:
        action()
    except OSError:
        report[name] = "refused"
    except Exception as error:
        report[name] = "error " + type(error).__name__
    else:
        report[name] = "ok"


def read(path):
    with open(path, "rb") as f:
        f.read(10)


def write(path, text="changed"):
    with open(path, "w") as f:
        f.write(text)


def remount(path):
    libc = ctypes.CDLL(None, use_errno=True)
    # MS_REMOUNT | MS_BIND, the way a read-write view of a read-only bind would be asked for
    if libc.mount(b"none", path.encode(), None, 32 | 4096, None) != 0:
        raise OSError(ctypes.get_errno(), "remount refused")


def mount_command(path):
    done = subprocess.run(["mount", "-o", "remount,rw", path], capture_output=True)
    if done.returncode != 0:
        raise OSError("remount refused")


def command_fails(name, argv):
    try:
        done = subprocess.run(argv, capture_output=True, timeout=30)
    except FileNotFoundError:
        report[name] = "no such program"
        return
    report[name] = "failed" if done.returncode != 0 else "WORKED"


# What is hidden: not listed, not read, not reached through a link or the root.
for name in ("home", "beside", "records", "runtime", "other_scratch_file_folder"):
    attempt("list " + name, lambda p=targets[name]: os.listdir(p))
attempt("read a file beside", lambda: read(targets["beside_file"]))
attempt("read the request record", lambda: read(targets["request_record"]))
attempt("list the records through the root", lambda: os.listdir("/proc/self/root" + targets["records"]))
attempt("read the sentinel in the real tmp", lambda: read(targets["sentinel"]))
attempt("connect to the user's bus", lambda: socket.socket(socket.AF_UNIX).connect(targets["bus"]))
command_fails("systemctl --user", ["systemctl", "--user", "is-system-running"])
command_fails("busctl --user", ["busctl", "--user", "list"])
report["runtime variables"] = [
    n for n in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if n in os.environ
]

# What is read-only: read, never written, by a plain write, through the root or by a remount.
for name in ("usr", "etc", "visible"):
    folder = targets[name]
    attempt("read " + name, lambda p=targets[name + "_file"]: read(p))
    attempt("write " + name, lambda p=folder: write(p + "/new-file.txt"))
    attempt("write " + name + " through the root", lambda p=folder: write("/proc/self/root" + p + "/new-two.txt"))
    attempt("remount " + name, lambda p=folder: remount(p))
    attempt("mount command " + name, lambda p=folder: mount_command(p))
    attempt("write " + name + " after the remounts", lambda p=folder: write(p + "/new-three.txt"))
reference = targets["reference"]
attempt("read the reference", lambda: read(reference))
attempt("write the reference", lambda: write(reference))
attempt("write the reference through the root", lambda: write("/proc/self/root" + reference))
write(targets["tmp_file"] + ".x")  # a file of its own, to put in the reference's place
attempt("replace the reference", lambda: os.rename(targets["tmp_file"] + ".x", reference))
attempt("remount the reference", lambda: remount(reference))

# What is writable: the place, its own /tmp and its own home.
attempt("write the place", lambda: write(targets["place"] + "/made-in-the-place.txt", "kept"))
attempt("write tmp", lambda: write(targets["tmp_file"], "gone with the run"))
home = os.environ.get("HOME", "")
report["home is its own"] = home != targets["home"] and home.startswith(targets["area_parent"])
report["home at start"] = sorted(os.listdir(home)) if os.path.isdir(home) else "not a folder"
attempt("write home", lambda: write(home + "/made-in-the-home.txt", "gone with the run"))
report["listing of tmp"] = sorted(os.listdir("/tmp"))

with open(sys.argv[2], "w") as f:
    json.dump(report, f)
"""


class TheReachOfTheExecutor(real_run.RealRun):
    """The table, once, for the folders of the test wherever they are (see the subclasses)."""

    # ROOT_PARENT (see RealRun) is where the test's own folders are made; AREA_PARENT is where
    # the run area is made. None is the machine's temporary folder.
    AREA_PARENT: str | None = None

    def made_folder(self, parent):
        folder = tempfile.mkdtemp(prefix="shuttle-reach-", dir=parent)
        self.addCleanup(shutil.rmtree, folder, True)
        return os.path.realpath(folder)

    def in_the_real_tmp(self, name):
        """A path that is directly in the machine's temporary folder."""
        path = os.path.join(os.path.realpath("/tmp"), name)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def run_the_probe(self, **document_extra):
        suffix = uuid.uuid4().hex
        beside = os.path.join(self.root, "beside")
        os.mkdir(beside)
        with open(os.path.join(beside, "secret.txt"), "w") as f:
            f.write("not for the executor")
        visible = os.path.join(self.root, "visible")
        os.mkdir(visible)
        with open(os.path.join(visible, "v.txt"), "w") as f:
            f.write("readable")
        reference = os.path.join(self.root, "reference.txt")
        with open(reference, "w") as f:
            f.write("the runbook")
        sentinel = self.in_the_real_tmp(f"shuttle-sentinel-{suffix}")
        with open(sentinel, "w") as f:
            f.write("in the real temporary folder")
        runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        other = self.made_folder(OTHER_SCRATCH)
        area_parent = self.made_folder(self.AREA_PARENT or tempfile.gettempdir())
        home = os.path.expanduser("~")
        targets = {
            "home": home,
            "beside": beside,
            "beside_file": os.path.join(beside, "secret.txt"),
            "records": self.records,
            "request_record": os.path.join(self.records, "r-1.request.json"),
            "runtime": runtime,
            "bus": os.path.join(runtime, "bus"),
            "other_scratch_file_folder": other,
            "sentinel": sentinel,
            "usr": "/usr",
            "usr_file": "/usr/bin/env",
            "etc": "/etc",
            "etc_file": "/etc/passwd",
            "visible": visible,
            "visible_file": os.path.join(visible, "v.txt"),
            "reference": reference,
            "place": self.place,
            "tmp_file": f"/tmp/shuttle-written-{suffix}",
            "area_parent": area_parent,
        }
        with open(os.path.join(self.support, "targets.json"), "w") as f:
            json.dump(targets, f)
        report_path = os.path.join(self.place, "report.json")
        script = self.script("probe.py", PROBE)
        doc = self.document(script, [os.path.join(self.support, "targets.json"), report_path])
        doc["references"] = [
            {
                "name": "runbook",
                "path": reference,
                "hash": hashlib.sha256(b"the runbook").hexdigest(),
                "size": 11,
                "hash_source": "caller",
            }
        ]
        doc["reach"]["visible"].append(visible)
        doc.update(document_extra)
        code, lines, err = self.run_to_the_end(doc, variables={"TMPDIR": area_parent})
        self.assertEqual((code, err, lines[-1]), (0, "", "ended_by_itself"))
        with open(report_path) as f:
            return json.load(f), targets, area_parent, suffix

    def test_what_is_hidden_is_hidden_what_is_read_only_is_never_written_and_what_is_writable_is_its_own(
        self,
    ):
        report, targets, area_parent, suffix = self.run_the_probe()
        hidden = (
            "list beside",
            "list records",
            "read a file beside",
            "read the request record",
            "list the records through the root",
            "read the sentinel in the real tmp",
            "list other_scratch_file_folder",
        )
        for name in hidden:
            with self.subTest(name):
                self.assertEqual(report[name], "refused")
        for what, path in (("home", targets["home"]), ("runtime", targets["runtime"])):
            with self.subTest("list " + what):
                # nothing to hide where the machine has no such folder; then it is refused anyway
                self.assertEqual(report["list " + what], "refused", path)
        self.assertEqual(report["connect to the user's bus"], "refused")
        self.assertEqual(report["runtime variables"], [])
        for name in ("systemctl --user", "busctl --user"):
            with self.subTest(name):
                self.assertIn(report[name], ("failed", "no such program"))
        for folder in ("usr", "etc", "visible"):
            with self.subTest(folder):
                self.assertEqual(report["read " + folder], "ok")
                for how in (
                    "write {}",
                    "write {} through the root",
                    "remount {}",
                    "mount command {}",
                    "write {} after the remounts",
                ):
                    self.assertEqual(report[how.format(folder)], "refused", how.format(folder))
        self.assertEqual(report["read the reference"], "ok")
        for name in (
            "write the reference",
            "write the reference through the root",
            "replace the reference",
            "remount the reference",
        ):
            with self.subTest(name):
                self.assertEqual(report[name], "refused")
        for name in ("write the place", "write tmp", "write home"):
            with self.subTest(name):
                self.assertEqual(report[name], "ok")
        self.assertIs(report["home is its own"], True)
        self.assertEqual(report["home at start"], [])
        # its own /tmp holds nothing of the machine's (the sentinel is the machine's) ...
        self.assertNotIn(f"shuttle-sentinel-{suffix}", report["listing of tmp"])
        # ... and what it wrote in the place stays, while what it wrote in /tmp and home is gone
        with open(os.path.join(self.place, "made-in-the-place.txt")) as f:
            self.assertEqual(f.read(), "kept")
        self.assertFalse(os.path.exists(f"/tmp/shuttle-written-{suffix}"))
        self.assertEqual(
            os.listdir(area_parent), []
        )  # the run area, with its tmp and home, is gone
        for name in ("new-file.txt", "new-two.txt", "new-three.txt"):
            self.assertFalse(os.path.exists(os.path.join(targets["visible"], name)))
        with open(targets["reference"]) as f:
            self.assertEqual(f.read(), "the runbook")
        self.assertNotIn("new-file.txt", os.listdir("/usr"))


class TheReachWithTheFoldersInTheTemporaryFolder(TheReachOfTheExecutor):
    """The common case: everything is under the temporary folder, which the box binds over."""

    ROOT_PARENT = None
    AREA_PARENT = None


class TheReachWithTheFoldersElsewhere(TheReachOfTheExecutor):
    """The place, the visible folder, the reference and the run area are all outside it."""

    ROOT_PARENT = OTHER_SCRATCH
    AREA_PARENT = OTHER_SCRATCH


class TheReachWithTheFoldersSplit(TheReachOfTheExecutor):
    """The place and the visible folder are outside the temporary folder; the run area is in it."""

    ROOT_PARENT = OTHER_SCRATCH
    AREA_PARENT = None


class TheReachWithTheAreaElsewhere(TheReachOfTheExecutor):
    """The place and the visible folder are in the temporary folder; the run area is outside."""

    ROOT_PARENT = None
    AREA_PARENT = OTHER_SCRATCH


del TheReachOfTheExecutor  # the table is run by its subclasses, never by itself
