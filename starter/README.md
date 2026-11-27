# starter

The files a new user's `~/.claude` is built from. They hold only what works for anyone; everything specific to one person goes in that person's own layer, a folder (`~/.claude/me` by default) that can be kept in a private repo to sync it between machines.

| File | What it is | Where it goes |
|---|---|---|
| `core.md` | The shared rules: how to work, verification, the progress record, compaction. It names no paths or tools; it refers to "my CLAUDE.md" for those. | Stays in the kit and is imported live, so a change here reaches everyone through one kit PR. |
| `CLAUDE.md.template` | Two import lines: the core, then the person's own file. | `~/.claude/CLAUDE.md`, with `__KIT__` replaced by the path to the kit and `__ME__` by the personal layer. |
| `personal.md.template` | Fill-in sections for one person's specifics: where things live, what stays private, how they launch sessions, how they write. | `CLAUDE.md` in the personal layer, filled in. |
| `settings.json` | Base settings with safe defaults: no allow rules for `git push` or `gh pr merge`; ask before pushes that force or delete and before connector tools that send, share or trash; no model, effort or permission mode, so Claude Code's own defaults apply; Claude Code reading a repo's `AGENTS.md` alongside your `CLAUDE.local.md` (Claude Code 2.1.285 or later); the gotcha hook, the status line, and a reminder after compaction. | Merged into `~/.claude/settings.json`, with `__KIT__` replaced by the full path to the kit. |
| `gotchas.md` | An empty gotchas file whose header explains the entry format. | `~/.claude/gotchas.md`, or wherever `GOTCHAS_FILE` points (the personal layer, to sync it). |

## Setting it up by hand

The kit's `install.sh` does these steps for you from a profile; see `installer/README.md`. By hand:

1. Clone the kit, say to `~/src/claude-kit`, and make the personal layer folder, `~/.claude/me`.
2. Copy `CLAUDE.md.template` to `~/.claude/CLAUDE.md` and replace `__KIT__` with `~/src/claude-kit` and `__ME__` with `~/.claude/me`.
3. Copy `personal.md.template` to `~/.claude/me/CLAUDE.md` and fill in your sections.
4. Copy `settings.json` into `~/.claude/settings.json` (or merge it into the one you have, adding the permission lists together), and replace each `__KIT__` with the kit's full path, or with `$HOME/src/claude-kit`; the hook commands quote it, so `~` would not expand there. If you installed the papercuts plugin with `/plugin install`, it wires its own hooks, so leave out the `PreToolUse`, `PostToolUse` and `PostToolUseFailure` entries.
5. Copy `gotchas.md` to `~/.claude/gotchas.md`.

The hooks need `python3` and do nothing when their script is missing, and the status line needs `jq`.
