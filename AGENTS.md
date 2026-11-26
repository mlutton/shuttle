# Working on Shuttle

- Work in your own git worktree of the clone.
- Commit with the identity already configured; before pushing, check the author address ends in `users.noreply.github.com`.
- Push a branch and open its pull request, then stop: merging and repository settings are the owner's.
- Everything written here is public: no contact details, credentials or personal data.
- Routine: `./checks/all.sh --fix`, then `./checks/all.sh`. A formatter's first run over existing code is its own pull request.
- Scripts under `checks/` stay thin: they gather and hand over, a tested function decides.

Read when:
- planning or sequencing a change: `docs/process.md`
- reviewing: `CODING_STANDARDS.md`
- writing code that takes a file name or judges an import: the hostile-case tables in `tests/hostile/`
- you need to know what the checks do: `README.md`
