# Repo-fix brief

Fill in the bracketed fields and send one copy per repo, or one per small group of repos.

---

A papercut sweep picked the changes below for [repo name]. Make them on a fresh branch and
open one pull request. Don't merge it.

- Repo: [abs path]. Default branch: [main]
- Worktree path: [abs scratch path]/wt-[repo]. Branch: `papercuts/[date]`
- Changes:
  1. [entry text] → [repo-note: the proposed lines | repo-fix: the proposed fix]
  2. …
- The user's rules for commits and PR text: [from their CLAUDE.md, e.g. no co-author or
  "Generated with" lines; disclose automated work in the PR body]
- Do not quote: [anything the user's CLAUDE.md marks confidential]

Ground rules:

1. Leave the existing checkout alone, because other sessions may be working in it. Run
   `git -C <repo> fetch origin`, then
   `git -C <repo> worktree add <worktree path> -b <branch> origin/<default>`, and work only
   in the worktree. Use absolute paths, one plain command per call.
2. Re-check each change against the fresh default branch, and skip any that is already done.
3. CLAUDE.md notes state the current fact in 1–3 lines, in the file's style and under the
   section that fits. Leave out history words ("now", "used to", "after the fix"). If a doc in
   the repo already explains it, add a one-line pointer to that doc.
4. A fix is the smallest change that stops the papercut. Run the checks the repo's CLAUDE.md
   or README names (tests, lint, format). If they can't run, say why.
5. Commit with a plain message that follows the user's rules. Push the branch and open one PR
   whose body lists what each change addresses and the checks you ran, ending with a line
   such as "Drafted by Claude in a papercut sweep." Don't merge.
6. Remove the worktree (`git -C <repo> worktree remove <worktree path>`) and keep the branch.
7. If a command is denied, stop that change and report it. Don't route around the denial.

Report: the PR URL; each change as done or skipped, with the reason; and the checks you ran,
with their results.
