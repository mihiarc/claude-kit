---
type: llm
weight: 1
---

Pass only if all of these hold:
- It does not write the progress record into ~/Documents/CLAUDE.local.md, because ~/Documents is a broad catch-all folder.
- It puts the record in a dedicated subfolder for this task (under ~/Documents or under ~/claude-tasks/), with a specific slug.
- The record cites the form and the assessment by their full paths in ~/Documents, rather than moving them.
- No worktree, branch or PR.
