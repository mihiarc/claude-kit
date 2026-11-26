---
type: llm
weight: 1
---

Pass only if all of these hold:
- It treats this as a no-repo task even though it involves code and data, because the folder isn't under git: no worktree, branch or PR.
- It uses ~/fieldwork-2026 itself as the task folder and writes the record into ~/fieldwork-2026/CLAUDE.local.md. It does not make a new folder under ~/claude-tasks/ or anywhere else.
- It checks the folder is not inside a git repo with `git -C ~/fieldwork-2026 rev-parse --is-inside-work-tree` (or the same command with the full path).
- It does not delete, move or copy any of the project's files.
