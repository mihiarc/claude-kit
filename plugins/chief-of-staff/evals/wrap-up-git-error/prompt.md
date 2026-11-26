---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
tags: [no-repo]
---

Use the chief-of-staff skill. The background session `fia-tools--export` (id 91bd0e) reported its work merged. Its record has a `### Branch` section naming `worktree-export`. But `git -C ~/repos/fia-tools/.claude/worktrees/export rev-parse --is-inside-work-tree` fails with `fatal: cannot change to '~/repos/fia-tools/.claude/worktrees/export': No such file or directory`. Wrap it up. You can't run commands or write files in this check, so don't try: say exactly what you would do, in order, with the commands.
