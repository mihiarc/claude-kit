---
type: llm
weight: 1
---

Pass only if all of these hold:
- The task takes the no-repo path: no `git worktree add`, no branch, no PR, and no verify skill step.
- The folder is a new one at `~/claude-tasks/<slug>`, made with `mkdir -p`, where the slug is specific to this task (such as `trail-day-thank-you`), in lowercase letters, digits and hyphens, and not a generic word such as `draft`, `letter`, `notes` or `task`.
- It checks that the folder is not inside a git repo with `git -C <folder> rev-parse --is-inside-work-tree`, expecting it to fail.
- The record it describes has no `### Branch` section and no Verification line, review line or PR line, and its Done when names what the user will read.
- The launch command starts with `cd` into that folder, and its `--name` is the folder's slug.
