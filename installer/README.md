# installer

The terminal route into claude-kit. Clone the kit, then run its `install.sh`:

    git clone <kit-url> ~/src/claude-kit
    ~/src/claude-kit/install.sh                    # defaults, or ~/.claude/me/profile if you have one
    ~/src/claude-kit/install.sh --profile <path>   # a profile kept elsewhere, such as in a private repo
    ~/src/claude-kit/install.sh --dry-run          # say what would change and change nothing

It needs `python3`; the status line also needs `jq`, and the stacked-PR guard `gh`. It is safe to rerun: a file or link it replaces is first moved aside as `<file>.bak-<timestamp>` (with `-2`, `-3` added rather than overwriting an earlier backup), and a second run with the same profile changes nothing. It builds `CLAUDE.md` and `settings.json` and reads the repo list before it writes anything, so a mistake in the profile or the overrides stops the run with nothing changed.

## What it does

| Step | Result |
|---|---|
| Personal layer | Makes the folder (`~/.claude/me` by default; it can't be `~/.claude` itself or a folder holding it) and, if it has no `CLAUDE.md`, gives it one: the rules from your existing `~/.claude/CLAUDE.md` if you had one, or else `starter/personal.md.template` to fill in. A first run with no profile also writes `profile` there, every key commented out at its default. |
| Skills | Links each skill of the profile's plugins into `~/.claude/skills`, so skills keep their bare names and edits to the kit take effect at once. A kit link whose plugin left the profile is removed; links of your own are left alone. A skill of your own with a kit skill's name is moved to `~/.claude/kit-backups/skills/`, outside the folder Claude Code loads skills from. |
| `~/.claude/CLAUDE.md` | Two imports: the kit's `starter/core.md`, then your layer's `CLAUDE.md`. |
| `~/.claude/settings.json` | The kit's base settings (`starter/settings.json`), merged with your overrides (see below). The file is rebuilt on every run, so a setting Claude Code wrote there itself (from `/config`, or a user-scope `/plugin install`) is not kept: the run lists each such setting, at any depth, so you can move it into your overrides. |
| `~/.claude/kit-install.json` | What the settings were built from: the kit's folder and commit (and whether it had uncommitted changes), the profile and the personal layer. The setup check (`plugins/setup-check`) reads it to tell when the kit has moved since the last run and to compare your `~/.claude` with what the kit renders. Rewritten on each run, never backed up. |
| Gotchas and papercuts | Creates the gotchas file from the kit's empty starter, and the papercut log if the profile names one. Neither is ever overwritten. |
| Global gitignore | Adds `CLAUDE.local.md`, `**/.claude/settings.local.json`, `.playwright-mcp/` and `.claude/worktrees/` to git's global excludes file. |
| Shell | Adds a line to `~/.zshrc` or `~/.bashrc` sourcing `extras/<shell>/claude-kit.<shell>` (the session-name wrapper, `extras/secrets` on `PATH` for `kit-secret`, and in zsh the Bash-parsing switch for Claude Code's Bash tool), then your own `shell_file` if the profile names one. |
| Repos | Clones the profile's repo list into `repos_dir` with `gh`, or `git` without it, skipping any already there. `--skip-repos` skips this step. |

## The profile

`profile.example` lists every key with its default. In short: `kit`, `me`, `plugins` (names or `all`), `shell` (`zsh`, `bash` or `none`), `shell_file`, `settings`, `gotchas`, `papercuts`, `repos_dir` and `repos`. Each line is `key = value`; a `#` at the start of a line or after a space starts a comment, and a value holding ` #` goes in quotes. The file is read, never run, and a relative path in it is taken from the profile's own folder, so a personal layer kept in a repo can name its files relative to itself. `shell_file` goes in a `source` line that runs at every shell start, so a path holding a quote, `$`, backtick or backslash is refused.

## Settings overrides

Your overrides file (`settings.overrides.json` in your layer, or the profile's `settings`) is merged over the kit's base by these rules, so that only what you add differs from the base:

- **Objects** merge key by key, at every depth.
- **Lists** are added together, the base's items first and then yours, without repeats. This covers permission rules: your `allow` rules join the base's `ask` rules, and since Claude Code checks `ask` before `allow`, a base ask rule still asks.
- **Other values** (strings, numbers, true and false) take yours.
- **`null`** removes the base's key, for example `"statusLine": null`. Under `permissions` and `hooks` it is refused: the base's permission rules and hooks are the kit's safe defaults, and an override can add to them but not remove them.
- **Types are checked.** Where the base has a key, yours must be the same kind (an object, a list or a plain value), and `permissions` lists must hold rule strings, `hooks` an object of lists and `env` an object of strings. A mismatch stops the run with a message naming the key.

`__KIT__`, `__ME__` and `__HOME__` in the overrides become those folders' full paths. When the profile's gotchas file isn't `~/.claude/gotchas.md`, the merged settings set `GOTCHAS_FILE` to it in `env`, which the gotcha hook reads.

## For other install routes

`kit_install.py render --profile <path> --out <dir>` writes the `CLAUDE.md` and `settings.json` that `install.sh` would install into `<dir>` and touches nothing else, so a guided setup can show them first and install exactly the same files.

## Tests

    python3 -m unittest discover installer/tests

They cover the profile, the merge rules (with randomized property checks), rendering, and end-to-end runs in a scratch HOME for zsh and for bash: a second run changes nothing, a newcomer gets no allow rules and no model, effort or permission mode, every installed hook exits 0 and stays silent on an ordinary call, and the bash session-name wrapper names sessions exactly as the zsh one does.
