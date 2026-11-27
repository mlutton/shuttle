# Working on Shuttle

## Everyone
- Work in your own git worktree beside the clone, named for your branch (a detached one, for its commit), made from `origin/main` on a first build, from the pull request's branch on a fix round, and at the exact commit read for a review; remove it before you hand back. Leave the main clone, other worktrees and branches, and systemd units you did not start as they are: never switch, stop or reset them (a unit your own run of the check started is yours). The worktree finds the clone's tools by itself. The tools and the pre-push hook are installed once per clone: README, "Checking a change".
- Everything committed, and every pull request and comment, is public: no contact details, credentials or personal data.
- After your first commit and before pushing, run `git log -1 --format=%ae`; when it does not end in `users.noreply.github.com`, stop and report, and leave the configuration alone.
- A test run by hand, outside `./checks/all.sh`, starts under file-size and address-space limits set in the same shell: `ulimit -f 200000; ulimit -v 4000000`.
- Merging and repository settings are the owner's.

## When you build
- Push a branch and open its pull request.
- Routine: `./checks/all.sh --fix`, then `./checks/all.sh`. A formatter's first run over existing code is its own pull request.

## Read when
- planning or sequencing a change: `docs/process.md`
- reviewing: `CODING_STANDARDS.md`
- writing code that takes a file name or judges an import: the hostile-case tables in `tests/hostile/`
- you need to know what the checks do: `README.md`
