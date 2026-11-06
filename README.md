# claude-kit

Skills, hooks and small tools I use with [Claude Code](https://code.claude.com), packaged as a plugin marketplace so you can install only the pieces you want.

## Install

```
/plugin marketplace add mihiarc/claude-kit
/plugin install handoff@claude-kit
```

Skills installed from a plugin are namespaced, so the handoff skill runs as `/handoff:handoff`. Claude also picks skills up on its own when a request matches their description.

## Plugins

| Plugin | Kind | What it does |
|---|---|---|
| [stacked-pr-guard](plugins/stacked-pr-guard) | hook | Blocks `gh pr merge --delete-branch` and `git push --delete` when open PRs are based on the branch, since GitHub closes those PRs instead of retargeting them. |
| [codebase-audit](plugins/codebase-audit) | skill | A full critical review of a codebase or component, with severity-rated findings checked against current best practice and filed as GitHub issues once you confirm. |
| [disk-cleanup-inventory](plugins/disk-cleanup-inventory) | skill | A tiered inventory of what is using disk space, delivered as a checklist worksheet; deletes only what you tick. |
| [downloads-tidy](plugins/downloads-tidy) | skill | Files and declutters `~/Downloads` against your own filing rules and existing folders, leaving it flat. |
| [ec2-spinup](plugins/ec2-spinup) | skill | Starts a small, tagged, self-terminating EC2 worker in a chosen region, with instance-profile auth and IP-restricted SSH. |
| [handoff](plugins/handoff) | skill | Writes a kickoff prompt so a new Claude session inherits this one's goal, sources, settled decisions and risks. |
| [human-handoff](plugins/human-handoff) | skill | Packages finished work for a human collaborator and drafts the covering note; sends only on your word. |
| [papercuts](plugins/papercuts) | skill + hook | A sweep skill that triages a papercut log into gotchas, repo PRs you pick and open decisions, and a hook that hands a session the one gotcha line its command or error needs. |
| [residue-sweep](plugins/residue-sweep) | skill | Removes development residue (history-narrating comments, stale names, dead code, doc drift) without changing behavior. |
| [speaker-prep](plugins/speaker-prep) | skill | Turns a deck or brief into talking points or a timed script, with print-ready PDFs. |
| [visual-inventory](plugins/visual-inventory) | skill | Report pages read at a glance: an items × checks grid on a fixed five-status scale, findings by kind, the top five and per-item detail, rendered from one JSON file into one self-contained HTML page. [Example](plugins/visual-inventory/skills/visual-inventory/assets/example.html). |

Several skills read your own `CLAUDE.md` for specifics such as where files live, what is confidential, and how to tag cloud resources, so they work best when those are written down.

## Extras

These can't ship as plugins, so they're set up by hand.

- **[Status line](extras/statusline/statusline.sh)** shows the session name, folder, branch, model and effort, plus context use against a handoff budget and the 5-hour and 7-day rate limits with a projection to reset. It needs `jq`. Point your `~/.claude/settings.json` at it:

  ```json
  "statusLine": {"type": "command", "command": "/path/to/claude-kit/extras/statusline/statusline.sh", "refreshInterval": 30}
  ```

  The budget and color thresholds are variables at the top of the script.

- **[Session names](extras/zsh/claude-names.zsh)** is a zsh wrapper that starts every interactive `claude` with a stable `--name`: the repo name in a main checkout, `<repo>--<task>` in a worktree, and the folder name elsewhere. Sessions use these names as messaging addresses. Source it from `~/.zshrc`.

## Using a checkout directly

To keep bare skill names (`/handoff`) and have edits take effect immediately, symlink skills from a clone instead of installing them:

```sh
git clone https://github.com/mihiarc/claude-kit ~/claude-kit
ln -s ~/claude-kit/plugins/handoff/skills/handoff ~/.claude/skills/handoff
```

Hooks set up this way go in your own `settings.json`, using each plugin's `hooks/hooks.json` as the template with `${CLAUDE_PLUGIN_ROOT}` replaced by the plugin's path.

## License

MIT.
