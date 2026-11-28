# The executor's reach is hidden unless declared

Status: accepted, 2026-11-27. Mostly built as of `main` at `14f9cd3`: what the executor sees is hidden unless declared, the place's git folders are read-only, the box enforces `changes_to_place: not`, and a program in a hidden folder is refused before the run. Not built: see Consequences.

## Context

Shuttle runs one executor inside a boundary: a systemd user scope around bubblewrap (see [0002](0002-the-boundary-is-a-scope-around-bubblewrap.md)). The first real boundary (pull request 19) bound in the whole filesystem and made only the records folder read-only. The executor could therefore read and write the home folder, `~/.ssh` included, and could write the caller's `.git/config` and `.git/hooks`; a hook left there would run in the caller's next commit in that repository. The network is shared.

The risk addressed is an agent that is lost or confused, not one that means to get out. The reach is not a security sandbox.

## Decision

The reach (see `GLOSSARY.md`) is what the executor can see and write. Each path is writable, read-only or hidden, and a path is hidden unless something declares it.

- Read-only: `/usr` and all of `/etc` (and `/bin`, `/sbin`, `/lib`, `/lib64` where the machine has them), the place's git folders (for a linked working copy, also the folder it shares with its source checkout, at its real path), each reference, and the folders the input document lists as visible.
- Writable: the run area (with its own `/tmp` and an empty home folder), and the place unless the document says `changes_to_place: not`.
- Hidden, because never bound: the home folder, other checkouts, the user's runtime folder with its systemd and D-Bus sockets, the real `/tmp`, and the records folder. Hiding the records folder follows from the rule by inference; it was not a separate answer. The reason given for it: the request record holds the whole input document, so a readable records folder would show the executor what it is deliberately not given.

Who declares what:

- The executor driver declares what its tool needs. For the Codex driver that is the login file and, when there is one, the tool's settings file, both copied into the run's own home and removed with the run area. Nothing is copied back.
- The input document names the place and may list extra read-only folders. It can never make anything writable.
- When the program a run needs sits in a hidden folder, the check form and the run refuse, naming the folder.
- `changes_to_place: not` is enforced by the box for every driver. The executor writes its statement inside the run area, and Shuttle copies it out.
- Decided and not built: `network: off` enforced by the box for the command driver (today the command driver refuses the setting), and a receipt field that says who enforced each restriction, the boundary or the tool.

## Alternatives considered

- **Hide a list, show the rest.** Not taken. When a new credential folder appears, a hide list leaves it readable until someone updates the list; a show list does not.
- **A document parameter that can widen writes.** Not taken: no real case needs it yet. A run that needs more should be refused with a message naming the gap. The one widening allowed, read-only visible folders, exists because tools are often installed under the home folder and a driver cannot know how each machine installs them.
- **A writable `.git`.** Not offered. The first decision was that a run needing it fails with a message that names the gap. Later the same day that was revised: no detection is built, the executor sees git's own read-only error, and the README says a writable `.git` is not offered. The recorded reason for the revision: Shuttle sees only that the executor's own command failed, not why, so a detector would have to guess the cause from the executor's output. Telling a box that could not start the program from the program's own exit is not built. No reason for refusing a writable `.git` as such is recorded; that a hook left in it would run in the caller's next commit (see Context) is an inference.
- **Bubblewrap without the systemd scope.** Not taken. The scope tracks everything a run starts, ends all of it and holds the time limit; running a tool directly does not. Bubblewrap alone remains the fallback if Shuttle must ever run without a user systemd.
- **Mounting the single login file.** Chosen first, then replaced. From a reading of the source of Codex CLI 0.172.0, the tool saves its login by writing a new file and renaming it over the old one, which a mounted single file cannot take.
- **Copying the login back after the run.** Not taken. The notes give, without naming a source and untested, that a refresh happens only near expiry or after eight days, so the worst case of not copying back is logging in again. Copying back risked saving a confused agent's damage over the real login, and two runs racing each other.
- **A hand-picked list of `/etc` files.** Not taken. The sensitive files there are readable only by root, so a list protects little, and it causes confusing failures when a tool needs a file of its own there (the first case was a tool manager). A by-hand trial of the tighter box on one machine found `/usr` and `/etc` read-only enough for a shell, Python, git, node, name lookup and HTTPS.
- **A box-level allowlist so Codex reaches only its service.** Deferred until after the first real Codex run. Not built.

## Consequences

- A tool installed under the home folder must be listed as visible, or the run is refused. The check covers the program file only, not an interpreter a script names, a library, or anything else the program opens from another hidden folder; those fail inside the box as the executor's own failure.
- The executor's own commands can read, and overwrite, the copied login file and settings file: from the source reading, Codex's own sandbox does not hide the disk. That is a copy of one login (and the settings file) where it was the whole home folder. Whether the service retires the old refresh token is not known. A refreshed login is lost with the run area.
- Gates and the closing freeze still run in a scope with no box. The network is open for Codex, which must reach its service. Codex also sends usage analytics to its vendor by default; Shuttle sets nothing about it and it is left on for now, not yet assessed.
- A folder listed as visible that is or holds the home folder, the user's runtime folder, `/tmp`, `/proc` or `/dev` is refused, as is one touching the records folder.
- Also not built: a receipt note of a login the tool changed during a run (decided), sweeping run areas left behind when Shuttle itself is killed hard, and detection of a run that needed a writable `.git`, which is decided against (see Alternatives).
- Not tested: no real Codex run has been made inside the boundary as built, and the test suite never starts the real tool.
