---
name: setup-check
description: Check whether this machine's Claude Code setup has fallen behind or drifted. It compares the installed Claude Code CLI, plugins and claude-kit with their latest versions, reports failed auto-updates, and lists what ~/.claude holds that neither the kit nor the user's personal layer does (stray skill links, hand-edited settings, unknown marketplaces). Use when the session-start "Setup check:" line appears, or when the user asks "is my setup up to date", "what version am I on", "has my setup drifted", "why didn't Claude Code update", "check my plugins for updates". It only reports, and never updates anything itself. Not for installing or changing the kit (kit-setup, or the kit's install.sh).
---

# Setup check

1. Run the check from this skill's folder:

   ```
   python3 -I <this skill's folder>/scripts/setup_check.py
   ```

   It looks up the latest Claude Code version on npm and the kit's origin (about a second), compares, saves the result as the snapshot the session-start hook reads, and prints the report. With no network, add `--offline`: the report then uses the latest versions from the last run, and says when they were looked up. `--json` prints the same data as JSON.

2. Show the user the report as it prints, then sum up in a sentence or two: what is behind, what failed, what has drifted, and what changed since the last check. A failed auto-update on its own is not "behind": say so when the CLI row is `ok`.

3. The report's last section names the commands that would catch up (`claude update`, `/plugin update <plugin>`, `git pull` in the kit and a rerun of its `install.sh`). Pass them on, and run none of them unless the user asks: this check only reports.

4. A drift line the user means to keep, such as an agent another tool installed, goes in `drift-ignore.md` in their personal layer (the folder `~/.claude/kit-install.json` names as `me`). Each line there starts with the item in backticks, as its drift line starts, then who put it there or why it stays, and a date:

   ```
   - `agents/some-agent.md` — installed by another project's setup (2026-01-31)
   ```

   Offer to add such a line, and write it only on the user's yes. Never add one to make a warning go away.

## What the rows mean
- **Claude Code**: the running version against the latest on the auto-update channel `autoUpdatesChannel` names (`latest` unless it says `stable`). A separate `FAILED` row reports a failed last auto-update that left this version in place.
- **plugin `name@marketplace`**: the installed version against the version in the local copy of its marketplace, which is as fresh as that marketplace's last update. `?` means one side has no version.
- **claude-kit**: the kit commit `install.sh` last built the settings from, against the kit checkout. `BEHIND` means rerun `install.sh`. A second row appears when the kit's origin has commits the checkout lacks. An install from before the kit recorded its commit shows `?` until `install.sh` runs once more.
- **Drift**: files and links in the folders where setup lives (`skills`, `agents`, `hooks`, `commands`, `output-styles`, `rules`) that aren't links into the kit or the personal layer's repo; `settings.json` keys and entries that differ from what the kit renders for the profile; `settings.local.json`, `keybindings.json`, user plugins and marketplaces neither names. Values are never printed: only key paths, with anything that looks like a secret replaced by `…`.

## The session-start line
A `startup` SessionStart hook prints one line when something is behind or has drifted, and nothing otherwise. It reads only the snapshot and never touches the network. When the snapshot is over a day old it starts a refresh in the background, which the next session reads.
