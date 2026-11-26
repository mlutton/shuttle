"""A real run of the command against the real boundary, for the tests under tests/boundary/.

Everything is in one temporary root: the records folder, the place the scripts may write, and the
scripts. A script says it is up through a named pipe the test reads, so no test polls or sleeps.
"""

import json
import os
import resource
import subprocess
import sys
import tempfile
import unittest

import rehearsal.the_boundary as the_boundary

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RealRun(unittest.TestCase):
    """The set-up shared by the tests that run a real script in the real boundary."""

    def setUp(self):
        the_boundary.require(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.records = os.path.join(self.root, "records")
        self.place = os.path.join(self.root, "place")
        os.mkdir(self.records)
        os.mkdir(self.place)

    def script(self, name, text):
        path = os.path.join(self.root, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def pipe(self, name):
        path = os.path.join(self.root, name)
        os.mkfifo(path)
        return path

    def document(self, script, arguments=(), request_id="r-1", limit=60):
        return {
            "format_version": 1,
            "request_id": request_id,
            "records_location": self.records,
            "thread": "t",
            "round": 1,
            "kind": "plain",
            "time_limit_seconds": limit,
            "executor": {
                "name": "command",
                "settings": {"command": sys.executable, "arguments": [script, *arguments]},
            },
        }

    # For a case that could make the command write or read without end (a link to /dev/zero):
    # no file it makes can pass 16 MB and its memory cannot pass 1 GB, so a regression ends in
    # an error the test sees instead of growing until the machine gives out.
    LIMITS = {resource.RLIMIT_FSIZE: 16 * 1024 * 1024, resource.RLIMIT_AS: 1024 * 1024 * 1024}

    @classmethod
    def limited(cls):
        for which, size in cls.LIMITS.items():
            resource.setrlimit(which, (size, size))

    def start(self, doc, path_first=None, limits=False):
        """The real command, started; the caller waits for it with `communicate`. With
        `path_first`, that folder comes first on the command's PATH. With `limits`, the command
        and what it starts run under `LIMITS` (the limits are inherited across exec)."""
        path = os.path.join(self.root, f"{doc['request_id']}.input.json")
        with open(path, "w") as f:
            json.dump(doc, f)
        proc = subprocess.Popen(
            [sys.executable, "-m", "shuttle", "run", path],
            cwd=REPO,
            env=self.environment(path_first),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=self.limited if limits else None,
        )
        self.addCleanup(self.end, doc["request_id"], proc)
        return proc

    @staticmethod
    def environment(path_first):
        environment = dict(os.environ)
        if path_first:
            environment["PATH"] = path_first + os.pathsep + environment.get("PATH", "")
        return environment

    def end(self, request_id, proc):
        """Nothing a test started outlives it."""
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        for name in (f"shuttle-run-{request_id}", f"shuttle-gate-{request_id}-0"):
            subprocess.run(["systemctl", "--user", "stop", f"{name}.scope"], capture_output=True)

    def run_to_the_end(self, doc, path_first=None, limits=False):
        """Run the command to its end: (exit code, standard output lines, standard error)."""
        proc = self.start(doc, path_first, limits)
        stdout, stderr = proc.communicate(timeout=120)
        return proc.returncode, stdout.splitlines(), stderr

    def outcome(self, request_id="r-1"):
        with open(os.path.join(self.records, f"{request_id}.outcome.json")) as f:
            return json.load(f)

    def units_left(self):
        """The Shuttle units the user's systemd still has loaded, failed ones too."""
        done = subprocess.run(
            ["systemctl", "--user", "list-units", "--all", "--no-legend", "shuttle-*"],
            capture_output=True,
            text=True,
        )
        return done.stdout.split()

    def scope_state(self, request_id="r-1"):
        done = subprocess.run(
            ["systemctl", "--user", "is-active", f"shuttle-run-{request_id}.scope"],
            capture_output=True,
            text=True,
        )
        return done.stdout.strip()

    def processes_with(self, marker):
        """How many processes on this machine carry `marker` in their command line."""
        found = 0
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == os.getpid():
                continue
            try:
                with open(f"/proc/{name}/cmdline", "rb") as f:
                    found += marker.encode() in f.read()
            except OSError:
                continue  # it ended while looked at
        return found
