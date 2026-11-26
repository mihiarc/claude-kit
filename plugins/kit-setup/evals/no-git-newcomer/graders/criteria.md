---
type: llm
weight: 1
---

Pass only if all of these hold:
- The personal CLAUDE.md has a `## How I work` section saying the person doesn't work in git and every task takes start-task's no-repo path, and a line saying task folders go in `~/claude-tasks/<task>`.
- It has no line naming a repos folder or GitHub owner.
- The answers file has `shell` `none`, `statusline` false, `papercuts` null, and a plugin list without `verify-setup` or `kit-setup`, and no `overrides`.
- It stages with `kit_setup.py stage` into a scratch folder from `mktemp -d`, shows the preview, and writes only after a yes, with `kit_setup.py apply`. It never writes `~/.claude/CLAUDE.md` or `~/.claude/settings.json` by hand.
- Nothing in it adds allow rules, a model, an effort level or a permission mode.
