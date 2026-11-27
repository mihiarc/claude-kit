---
name: verify-setup
description: Write or refresh a repo's own `pr-checks` skill (`.claude/skills/pr-checks/SKILL.md`), which says how to check a change in that repo end to end, from the repo's real commands. Use when a repo has no pr-checks skill (the user's CLAUDE.md "Verification" requires one before the first PR), when it is stale or fails, when a repo still has an older `.claude/skills/verify/` skill, or when the user says "set up verification", "add a pr-checks skill", "how do we verify changes here". Not for running a verification (use the repo's own `pr-checks` skill) or for adding CI (its own task).
---

# verify-setup

Every repo the user builds in has a `pr-checks` skill: one short file that tells any session how to
show a change works there, end to end. This skill writes it. The file is only worth having if
every command in it was run and worked, so this skill runs each one before writing it down.

Claude Code bundles `/run` and `/verify`, which launch the app and check a change against it. The
file this skill writes is named `pr-checks`, not `verify`, so it doesn't replace the bundled
`/verify`: it holds the repo's own checks and the PR's report, and leaves launching the app to
`/run` and `/verify`, which follow the recipe that `/run-skill-generator` records.

## Step 1 — Find what the repo already checks

Read, don't guess:

- **CI:** `.github/workflows/*.y*ml`: which jobs run on a pull request, and their commands.
- **Commands:** `Makefile`, `pyproject.toml` (scripts, `[tool.pytest]`, ruff), `package.json`
  scripts, `justfile`, `noxfile.py`, `tox.ini`.
- **The repo's CLAUDE.md and README:** stated gates ("lint && typecheck && test && build"), how to
  run the app, required data or credentials.
- **Tests:** where they live, which are slow or need data (markers, skips), any end-to-end suite.
- **What the repo is:** web app, API, library, CLI, data pipeline, agent, documents. This decides
  the end-to-end check in Step 2.

If a `.claude/skills/pr-checks/SKILL.md` already exists, read it and treat this as a refresh: keep
what still runs, fix what doesn't. An older kit wrote the same file as `.claude/skills/verify/SKILL.md`,
which replaces the bundled `/verify`: `git mv` it to `.claude/skills/pr-checks/`, set its `name`,
and refresh it.

## Step 2 — Choose the end-to-end check

One check that drives the real thing, chosen by what the repo is. `/run` and `/verify` infer a
standard launch on their own. When launching takes more (a database, an env file, a graphical
session, a multi-step build), run `/run-skill-generator` first: it gets the app running from a
clean environment and commits the recipe as `.claude/skills/run-<name>/`. Either way, the check
launches through `/run` or `/verify` instead of restating the launch steps.

| Repo | End-to-end check |
|---|---|
| Web app | Launch with `/run`; in a browser (Claude in Chrome or Playwright), load the page the change touches and do the user's action; read the console for errors |
| API / backend | Launch with `/run` against its test database; call the routes the change touches; check status and body |
| Library | Run the public entry point on a small real input and compare with a known answer (a published figure, a fixture, the previous release) |
| CLI | Run the command a user would run, on real input, and check its output and exit code |
| Data pipeline | Run on the smallest real slice (one state, one tile, one month) and check row counts, schema and one known value |
| Agent / LLM app | One live turn (or the eval runner on a tiny set) under a hard dollar cap, checking the answer's shape and its tool calls |
| Documents | Build or render them, and check links and figures resolve |

When the change replaces an existing system, add a differential check: the same inputs through
old and new, with a list of approved differences.

Name any credential, data file or service the check needs, and how a session gets it without
reading secrets (a profile name, a sync command the repo documents, a seed script). If the check can't run without
something the user must provide, say so in the file.

## Step 3 — Run every command

Run each command from a clean state (a fresh worktree, `uv sync` or `npm ci` first). Record how
long it takes and what success looks like. A command that fails gets fixed or left out, never
written down untested. If the repo's tests are red on main, write that down as a known failure
with the failing test names, and tell the user.

## Step 4 — Write `.claude/skills/pr-checks/SKILL.md`

Keep it under about 60 lines:

```markdown
---
name: pr-checks
description: How to verify a change in <repo> end to end before opening a PR: <one line on what the checks are>. Run it before every PR; the PR's `Verified by:` line reports what it showed.
---

# Verify a change in <repo>

## Fast checks (every change)
- `<command>`: <what it checks>; passes when <...>. About <n> s.

## End-to-end check
1. Launch with `/run` (following `.claude/skills/run-<name>/` if the repo has one), or <setup step> when there's nothing to launch
2. <drive the real thing>
3. Passes when <observable result>.

## When the change touches <area>
- <extra check for that area>

## Needs
- <credentials, data, services, and how to get them without reading secrets>

## Known gaps
- <no CI / slow suite skipped by default / tests already red on main: names>

## Report
End the PR body with: `Verified by: <fast checks> pass; <end-to-end check and what it showed>`, or `none` and why. Once the PR's independent review is done, a `Reviewed by:` line goes just above it: who reviewed, what they found and what was fixed, or `none` and why.
```

Make sure `.claude/skills/` is not gitignored (check `git check-ignore -q .claude/skills/pr-checks/SKILL.md`);
if it is, add an exception for `.claude/skills/` and say so.

## Step 5 — Prove it and land it

Follow the new skill once, from top to bottom, as a fresh session would. Then commit it, with any `run-<name>`
recipe, on its own (`Add pr-checks skill`) on the task's branch, or as a small PR if no task branch is open. If the
repo has no CI, end your report with that, as a candidate task: adding CI is never folded in here.
