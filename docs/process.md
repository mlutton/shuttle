# How a change is made

Five roles. Each role on a change is held by a different agent.

- **Planner**: turns a ticket into a brief, reproduces findings, writes fix briefs, posts review comments.
- **Builder**: makes the change on a branch and opens the pull request.
- **Reviewer**: hunts for a wrong answer and writes one comment.
- **Auditor**: reads the change's comments against its code and commits the cuts.
- **Owner**: merges.

## Steps

1. **Brief.** Done when every criterion names where its evidence is seen, and the brief says what is out of scope. The brief names where each fact it or a ticket states came from. A change to `checks/` or to the shared test harness (`tests/rehearsal/`) lands as its own pull request first, and two open branches never change the same code, `checks/` or `tests/rehearsal/` file (the documents **Docs with the change** names are exempt); the brief names the files the builder owns.
2. **Build.** Done when every hosted check is green at the head commit and the sections of `.github/pull_request_template.md` are filled.
3. **Review.** Done when every row of the hostile-case tables that applies is tried, every rule in `CODING_STANDARDS.md` under a heading other than "The review" is answered once and the rules under "The review" are followed, and the comment gives one verdict for the exact commit. The standards file also holds the round rule.
4. **Post.** Done when the planner has read the comment against the public rule in `AGENTS.md` and it is on the pull request.
5. **Fix.** Done when each defect is reproduced by the planner, or returned to the reviewer as not reproduced; the fix brief gives the defect, its reproduction and the constraint the fix must keep, and the fix itself is the builder's; the builder's fix sits in commits on top; and the hosted checks are green again. Then step 3.
6. **Audit.** After the last review's "ready to merge". Done when the auditor has read every comment and docstring the change adds or touches against the code at the head commit and cut each one that fails **Comments give reasons** (corrected only where a reason would be lost), and cut each document line the change adds or touches that is untrue or names something that is gone; and the planner has read the auditor's commit and confirmed it changes words only, with the hosted checks green. That confirmation stands for a review of that commit; the verdict merged on is the last review's.
7. **Merge.** The owner merges on "ready to merge". Done when each note from the reviews is filed as follow-up work, where the planner keeps it.

## After every merge

The planner asks of each finding: could a machine have caught this? One that could becomes a check in the next pull request.
