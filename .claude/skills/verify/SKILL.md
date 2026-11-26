---
name: verify
description: How to verify a change in claude-kit end to end before opening a PR. Covers plugin manifest validation, the private-terms scan, plugin unit tests, and driving Docket (the chief-of-staff page) in a browser against the sample questions file on a spare port. Run it before every PR; the PR's `Verified by:` line reports what it showed.
---

# Verify a change in claude-kit

## Fast checks (every change)
- `claude plugin validate .`: the marketplace manifest lists valid plugins. Passes on `✔ Validation passed`. Under 1 s.
- `claude plugin validate plugins/<name>` for each plugin the change touches: same pass line. Under 1 s each.
- `scripts/check-private-terms.sh`: no employer, client or colleague names, personal paths or account IDs in the working tree. Passes with exit 0 and no output; a "nothing checked" line means `.git/info/private-terms` is missing, so the scan didn't run. The hooks in `scripts/hooks/` (on once `core.hooksPath` points there) run the same check; when it blocks, generalize the text and never edit `.git/info/private-terms`.
- `scripts/test-check-private-terms.sh`: runs the check and the tracked hooks in a scratch repo with a made-up term. Passes when all 41 lines start `ok`, in about 4 s. Clean commits pass even when history the remote holds matches. Any commit the remote lacks is refused when its files, a file name (non-ASCII ones too), its message, its author or committer, or a pushed tag's message or the blob it names carries the term, and what the remote holds is asked of the remote, so a repointed remote with stale tracking refs is no loophole. A GNU-style escape such as `\b` matches file contents, since one grep checks the list and does every match. Binary files (also one whose first NUL comes late), lines that aren't valid UTF-8 (the run goes on after one matches), a Latin-1 byte in the list, CRLF lists and terms with trailing blanks are covered. A list with an invalid regex or no terms refuses every commit and push, while the working-tree check passes with no list. The hooks run from a worktree that lacks `scripts/`. Run it after any change to the check script or the hooks.
- `extras/secrets/kit-secret`: `python3 -m unittest discover extras/secrets/tests` passes when it prints `OK` (about 26 tests, under 10 s). Fake `security`, `gh` and clipboard tools log every argv and environment, so the tests check that a made-up value never reaches an argument list, an environment, a temp file or the output; nothing touches the real keychain or GitHub. Run it on `/usr/bin/python3` too.
- A plugin with a `tests/` folder (today, `chief-of-staff`, `kit-setup`, `setup-check` and `speaker-prep`): `python3 -m unittest discover plugins/<name>/tests` passes when it prints `OK`. Under 1 s, except `kit-setup` and `setup-check` (under 15 s), which run `install.sh` into scratch HOMEs. Run `setup-check`'s on `/usr/bin/python3` too.

## End-to-end check: the setup check (`plugins/setup-check`)
- Run `python3 -I plugins/setup-check/skills/setup-check/scripts/setup_check.py report --offline` on the real machine. It is read-only except for its own `~/.claude/setup-check/` folder, and it prints the version rows and drift without a traceback.
- A hook change: start an interactive `claude --plugin-dir plugins/setup-check` from a trusted folder. When something is behind or drifted, the screen shows `SessionStart:startup says: Setup check: …`; otherwise, nothing.

## End-to-end check: the installer (`install.sh`, `installer/`, `starter/`, `extras/zsh/`, `extras/bash/`)
- `python3 -m unittest discover installer/tests` passes when it prints `OK` (about 30 tests, under 15 s). It copies the kit into a scratch HOME and runs `install.sh` there twice for zsh and twice for bash, and never touches the real HOME. Run it on `/usr/bin/python3` too, the 3.9 that ships with macOS.
- A change that could move what an existing user's install writes: run the old installer and the new one into two scratch HOMEs with that user's profile, and compare `~/.claude/settings.json` (as parsed JSON), `~/.claude/CLAUDE.md` with its imports expanded, the links under `~/.claude` and the rc file. Every difference should be on the PR's list of approved differences.

## End-to-end check: a skill change
Load the changed skill in a session (symlink the checkout's skill folder into `~/.claude/skills/`, or `/plugin install` from a local marketplace) and run one prompt from its `evals/` file, or the request its description names. It passes when the skill triggers and does what its SKILL.md says.

## End-to-end check: Docket (`plugins/chief-of-staff/skills/chief-of-staff/docket/`)
Never use port 8765 or the user's real questions file. Both belong to the live chief-of-staff session, and an entry there wakes it.

1. Copy `docket/sample/questions.md` into a scratch folder, and point `COS_QUESTIONS` at the copy. Generated files go in a `docket/` folder beside it. The sample has a card in every board column. Its Done and Answered entries dated 2099 always show, and those dated 2000 never do.
2. For the PR buttons, write `["example-repo"]` to `<scratch>/docket/.repos.json` and set `COS_GITHUB_ORG=example-org`. The fresh cache means no `gh` call is made.
3. `COS_QUESTIONS=<copy> python3 -I build.py` prints `Wrote …/index.html (11 cards, …)`.
4. Start `COS_QUESTIONS=<copy> COS_DOCKET_PORT=8799 python3 -I server.py` in the background.
5. In Chrome (Claude in Chrome), open `http://127.0.0.1:8799/`. Do the action the change touches: a type chip, a drag between columns (`left_click_drag` fires real HTML5 drag events), a tick, an answer option, Drop, Merge/Review/Discuss, or Refresh. Then read the console for errors.
6. Each action appends one line to `<scratch>/docket/inbox.jsonl` with the expected `num`, `item`, `action` and, for a `move`, `to`. A moved card shows "moving" in its new column. Edit the copy the way the chief-of-staff session would (SKILL.md, "Docket, the local page") and rebuild. The page reloads itself within 5 s (it polls `/version`), each card sits in its new column, and no "moving" or "sent" mark is left.
7. Stop the server.

Quick server check without a browser: POST `{"token": <docket/.token>, "num": "1", "choice": "a"}` to `/answer`, which returns `ok` and appends one inbox line.

## Needs
- The `claude` CLI and `python3` (stdlib only).
- Claude in Chrome for the Docket browser check.

## Known gaps
- No CI. Every check here runs by hand before a PR.
- Only the Docket parser has unit tests. The page's JavaScript is checked in the browser only.

## Report
End the PR body with: `Verified by: plugin validate (marketplace + <plugins>) and private-terms scan pass; <end-to-end check and what it showed>`, or `none` and why. Once the PR's independent review is done, a `Reviewed by:` line goes just above it: who reviewed, what they found and what was fixed, or `none` and why.
