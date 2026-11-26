---
name: kit-setup
description: Set up claude-kit for a person from inside Claude Code, with no terminal needed. Interviews them in plain words (who they are, whether they work in git, where their files go, what stays private, how they write), shows the CLAUDE.md and settings it would write, writes them only on a yes through the kit's own installer, backs up every file it replaces, and offers the extras one at a time (status line, session names, Docket). Rerun it to change answers later. Use for "set up the kit", "set me up", "install claude-kit", "run kit-setup", "I just installed kit-setup, what now", "change my kit settings", or "redo my setup". Not for starting a task (start-task) or for changing one setting by hand when the person names the file.
metadata:
  author: mihiarc
  version: "1.0"
---

# kit-setup

Set up claude-kit for someone who may never open a terminal. The kit's installer
(`installer/kit_install.py`, the same one `install.sh` runs) does all the writing; this skill
interviews the person, builds their answers into a profile and their own `CLAUDE.md`, shows
what the installer would write, and runs it only on a yes. Because both routes write through
the one installer, a person can start here and switch to `install.sh` later, or the reverse.

`scripts/kit_setup.py` (run it with `python3 -I "${CLAUDE_SKILL_DIR}/scripts/kit_setup.py"`)
does the mechanics: `find-kit`, `stage` (builds the preview in a scratch folder and writes
nothing else) and `apply` (writes, backs up, installs, checks). `references/interview.md` holds
the questions and how each answer is written down. Read it before Step 2.

## Rules that hold throughout

- **Plain words.** Assume the person has never used a terminal. Say what a thing does before its
  name, one question at a time, each with a suggested answer they can accept with "yes". Don't
  show commands they don't need to run.
- **Nothing is written before the yes in Step 4.** The scratch folder from `mktemp -d` is the
  only place you write until then. The one exception is getting the kit in Step 1.2 (refreshing
  the marketplace's copy, or downloading it), which writes only the kit's own folder and runs
  only on its own yes. Never write `~/.claude/CLAUDE.md` or `~/.claude/settings.json` yourself,
  not even to fix one line: only the kit's installer writes them, through `apply`.
- **No secrets in the chat.** Never read `~/.claude/settings.json` (old or new) into the
  conversation, and never print a settings file with `cat` or the like: it may hold tokens in
  `env` or elsewhere. `stage` reports what the preview needs with values that might be secret
  shown as `<hidden>`, and `kit_setup.py show --stage $S/stage` prints the new settings the same
  way. A hidden value the person wants to keep is kept by name (`keep`, Step 3), so it goes from
  file to file and never through the chat; never ask them to type or paste it.
- **Safe defaults stay.** The kit's base settings have no allow rules for `git push` or
  `gh pr merge`, ask before force pushes, deletes and connector tools that send, share or
  trash, and set no model, effort or permission mode. Never loosen any of these on your own or
  suggest that they should be. When the person asks for something looser, write exactly what
  they named into `overrides` in the answers (Step 3) and show it in the preview. Don't offer a
  broader form of it (a wildcard, related commands): if they want more, they'll name it.
- **Never the person's files without a backup.** `apply` moves each replaced file aside as
  `<file>.bak-<timestamp>` first. A file you'd change outside `apply` (none, normally) gets the
  same treatment.

## Step 1 — Check the machine and find the kit

1. **python3 and git.** Run `python3 -I -c "print('ok')"` and `git --version`. On a Mac without
   the developer tools, both are stand-ins that open an install dialog. If either fails, tell the
   person the setup needs Apple's free Command Line Tools, that a dialog may already be asking to
   install them (or they can run `xcode-select --install` with your help), and to come back when
   it's done. Stop here until python3 works. git is needed only for the fallback in 3 below and
   for the global gitignore, so a missing git is a note, not a stop.
2. **Find the kit.** Run `kit_setup.py find-kit`. It prints JSON:
   - `kit` set: use it. `how` says where it came from: the kit an earlier install used, or the
     marketplace's own copy of the kit (the folder Claude Code keeps when the person added the
     kit's marketplace).
   - `switched_from` set as well: an earlier install used another copy of the kit, at that
     `path`, which can't be used (`state` `no`: it's an older copy without this setup; `stale`:
     it has no installer). Tell the person, in plain words, that the setup will move them to the
     copy at `kit`, that the preview will show their profile pointing at it and the old copy's
     line taken out of their shell's startup file, and that the old folder itself is left alone.
     Go on only on their yes.
   - `kit` empty and `stale` listed: the marketplace copy is older than this skill and has no
     installer. Say so, and with their yes run `claude plugin marketplace update <marketplace>`
     (or have them run `/plugin marketplace update <marketplace>`), then `find-kit` again. If it
     is still stale, stop and say the kit's marketplace copy has no installer.
   - `kit` empty, nothing stale: no copy of the kit is reachable (for example, the desktop app
     has no `claude` command on the PATH). Offer to download the kit with
     `git clone <repository> ~/claude-kit`, using `repository` from the JSON, and use that folder.
     If they'd rather not, or git is missing, stop and say what's needed.
   The kit's folder must not contain spaces; the installer refuses one that does.
3. **What is there already.** Read `~/.claude/CLAUDE.md`, `~/.claude/me/CLAUDE.md` and
   `~/.claude/me/profile` if they exist. Don't read `~/.claude/settings.json`: `stage` reports
   what the preview needs from it. If the person's own layer
   exists, this is a **rerun**: the interview starts from what it says and asks only what they
   want to change. If `~/.claude/CLAUDE.md` holds the person's own rules (it doesn't import
   `starter/core.md`), they are carried into their new `CLAUDE.md` (references/interview.md,
   "Carrying over"), so nothing they wrote is lost.

## Step 2 — Interview

Ask the questions in `references/interview.md`, in its order, one at a time, and note each
answer. Skip what an earlier answer settles. Keep the whole interview short: a newcomer should be
through it in a few minutes, and every section of their `CLAUDE.md` can be filled in later.

The git question decides a lot. A person who doesn't work in git gets start-task's no-repo mode:
their `CLAUDE.md` says they don't work in git and where task folders go, which start-task reads,
so every task they start gets a plain folder and no worktree, branch or PR.

The extras are part of the interview, offered one at a time and each skippable, so the preview
in Step 4 shows everything: the status line, session names, and Docket.

## Step 3 — Stage the preview

In a scratch folder from `mktemp -d` (call it `$S`):

1. Write the person's own `CLAUDE.md` to `$S/personal.md`, from `starter/personal.md.template`
   in the kit filled in with their answers (references/interview.md, "Writing their CLAUDE.md").
   On a rerun, start from their current `~/.claude/me/CLAUDE.md` and change only the sections
   their new answers touch.
2. Write the answers to `$S/answers.json`: `plugins` (a list), `shell` (`zsh`, `bash` or
   `none`), `statusline` (true or false), `papercuts` (a path, or null for none), `overrides`
   only for a setting the person named, and `keep` (dotted names such as `env.GITHUB_TOKEN`)
   only for settings of their current file that they chose to keep after the preview listed
   them as not kept.
3. Run `kit_setup.py stage --kit <kit> --answers $S/answers.json --personal $S/personal.md
   --out $S/stage`. It writes only under `$S/stage` and prints JSON. If it exits non-zero, tell
   the person what it said in plain words, fix the answer and stage again.

## Step 4 — Show it, and write only on a yes

Show, in this order:

1. **Their own `CLAUDE.md`**, in full (`$S/stage/layer/CLAUDE.md`). It's theirs to edit any time.
2. **`~/.claude/CLAUDE.md`**, in full (`$S/stage/rendered/CLAUDE.md`): two lines that load the
   kit's shared rules and then theirs.
3. **The settings**, in plain words from the JSON's `settings`: how many actions ask first
   (`ask_rules`), that nothing is pre-approved (`allow_rules` empty) unless they named something,
   which hooks run and that they stay silent until they have something to say, whether the status
   line is on, and that no model, effort or permission mode is set (`model_effort_or_mode`
   empty). Offer the full file and, if asked, show it with `kit_setup.py show --stage $S/stage`,
   never by reading the file.
4. **What changes on disk**, from `files` and `dry_run`: each file as new, replaced (backed up
   first, with where the backup goes) or unchanged; the skills that get linked; the lines added
   to git's global ignore file and the shell's startup file. Say plainly that nothing has been
   written yet.
5. **Kept from their current settings** (`carried`): the plugins they installed with `/plugin`
   (kit-setup among them) and the marketplaces those come from. Claude Code keeps these in
   `settings.json`, which the installer rebuilds, so `stage` copies them into the overrides;
   without them kit-setup would be switched off and the kit's own marketplace dropped.
6. **Not kept** (`dropped`): any other setting in their current `settings.json` that the new one
   lacks, in plain words, values as `stage` shows them. The old file is backed up, so nothing is
   lost. To keep one, the person names it, and it goes into `keep` (Step 3) and you stage again.
   A blanket answer ("keep everything", "keep my old settings") is not a yes to any one item:
   list them and ask which. A setting that loosens the safe defaults (an allow rule, a model,
   an effort level, a permission mode) is kept only on a yes that names that one setting, after
   you've said what it does.
7. **Notes**: anything in `notes` (a settings file that is a link, an old copy of the kit still
   loaded by their shell), and each entry of `duplicates` (Step 6).

Then ask: write these, change something, or stop? Only a clear yes to the preview you just
showed writes. If you staged again for any reason (a change, a fix, a person coming back later
with "go ahead"), show what differs from the last preview and ask again before `apply`.

- **No or stop:** delete `$S` and say that nothing was written. Nothing outside `$S` has changed.
- **Change something:** take the change, stage again (Step 3), and show what moved.
- **Yes:** run `kit_setup.py apply --stage $S/stage`. It writes the personal layer's files, runs
  the kit's installer, then checks that the installed `CLAUDE.md` and `settings.json` equal the
  preview and the kit's own render of the profile, and that a second run would change nothing.
  If it exits non-zero or prints `FAILED`, say so with its output; don't call the setup done.
  If it says files or the kit changed since the preview (a plugin installed meanwhile, say), it
  wrote nothing: stage again, show what differs, and ask again.

## Step 5 — After the write

Do the follow-ups the person said yes to, each one only after the write succeeded:

- **Docket** (they said yes, and chief-of-staff is linked): if the questions file doesn't exist
  (`~/.claude/chief-of-staff/questions.md`, or the path their `CLAUDE.md` names), start it from
  `plugins/chief-of-staff/skills/chief-of-staff/assets/questions-template.md` in the kit, then
  build and open the page with `python3 -I <kit>/plugins/chief-of-staff/skills/chief-of-staff/docket/build.py --open`
  (with `COS_QUESTIONS=<path>` if it isn't the default).
- **A second computer** (git users only): offer to make `~/.claude/me` a private repo so it can be
  cloned on the other machine. Creating a repo on GitHub is outward-facing: show the commands
  (`git init`, a first commit, `gh repo create <name> --private --source ~/.claude/me --push`)
  and run them only on a yes. Without git, say the folder can be copied across by hand.

## Step 6 — Finish

Tell the person, briefly:

- What was written and where the backups are, from `apply`'s output.
- **Start a new session** (or restart the app) so Claude Code loads the new `CLAUDE.md`,
  settings and skills; this session still runs on the old ones. If they said yes to session
  names, open a new terminal window first.
- **Duplicates:** if `duplicates` listed plugins that are also installed with `/plugin`, the kit
  now provides those skills and hooks itself, so each would appear twice. Give the commands to
  remove the plugin copies (`/plugin uninstall <id>`), and leave running them to the person.
- **What to try first:** "start a task on <something they mentioned>", which runs start-task.
- They can rerun this skill any time to change an answer, and their own `CLAUDE.md`
  (`~/.claude/me/CLAUDE.md`) is theirs to edit directly.

Delete the scratch folder `$S`.

## Reference

- `references/interview.md`: the questions, the defaults, and how each answer is written into
  the person's `CLAUDE.md` and profile.
- `scripts/kit_setup.py`: `find-kit`, `stage`, `apply`. Its docstring gives the answers format.
- The kit's `installer/README.md`: the profile keys, the settings override rules and what an
  install does, step by step.
