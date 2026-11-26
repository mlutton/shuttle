# Working on Shuttle

## Everyone
- Work in your own git worktree of the clone; it finds the clone's tools by itself. The tools and the pre-push hook are installed once per clone: README, "Checking a change".
- Everything committed, and every pull request and comment, is public: no contact details, credentials or personal data.
- Before pushing, run `git log -1 --format=%ae`; when it does not end in `users.noreply.github.com`, stop and report, and leave the configuration alone.
- Merging and repository settings are the owner's.

## When you build
- Push a branch and open its pull request.
- Routine: `./checks/all.sh --fix`, then `./checks/all.sh`. A formatter's first run over existing code is its own pull request.

## Read when
- planning or sequencing a change: `docs/process.md`
- reviewing: `CODING_STANDARDS.md`
- writing code that takes a file name or judges an import: the hostile-case tables in `tests/hostile/`
- you need to know what the checks do: `README.md`
