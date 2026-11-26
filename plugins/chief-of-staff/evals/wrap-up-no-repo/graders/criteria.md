---
type: llm
weight: 1
---

Pass only if all of these hold:
- It treats this as a task with no repo, from the record having no `### Branch` section and git failing with `not a git repository`.
- It stops the session with `claude stop 7f3a2c`.
- It removes only the `## Progress` section from ~/claude-tasks/trail-day-thank-you/CLAUDE.local.md and keeps the `## My notes` section.
- It never deletes the folder, thank-you.md or CLAUDE.local.md: no `rm`, no `git worktree remove`, no `claude rm`, no branch deletion.
- It records the task under Done in the questions file.
