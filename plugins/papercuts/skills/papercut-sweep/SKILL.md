---
name: papercut-sweep
description: >-
  Triage a running log of development papercuts (things that slowed Claude sessions down) so
  each entry ends up where the next session will meet it: settled answers promoted into a
  gotchas file grouped by tool, repo-specific notes and small fixes proposed per repo and
  opened as PRs for the ones the user picks, decisions the user owes kept as OPEN lines, and
  resolved or one-off entries deleted. Starts by checking the previous sweep's PRs, backs both
  files up, and edits the log with a script that keeps lines other sessions append mid-sweep.
  Use whenever the user wants to work on, clear out, triage, sweep or tidy their papercuts,
  friction log or gotchas file, says the log is getting long, asks what the last sweep left
  open, or wants a sweep scoped to one project ("just the frontend papercuts", "papercuts since
  last week"). Not for logging one new papercut mid-task (append it the way the user's
  CLAUDE.md says), a codebase review (codebase-audit), or cleaning comments after a refactor
  (residue-sweep).
metadata:
  author: mihiarc
  version: "1.0"
---

# papercut-sweep

Each papercut cost a session time once. Left in the log, it helps only a session that thinks
to grep for it. A sweep moves every entry to where the next session runs into it without
searching: a settled answer into the gotchas file that sessions check when tooling fails, a
repo quirk into that repo's CLAUDE.md, which every session there loads, a bug into a fix.
The log keeps only what still needs someone to act, so it stays short enough to read.

## Before you start

Read the user's global CLAUDE.md for:

- the log and gotchas paths, and the entry format;
- where repos live, and the GitHub owners and orgs they belong to;
- what must never reach GitHub (confidential clients, datasets);
- their rules for commits and PR text;
- any command they use to record what a session is working on. Run it now, and clear it at
  the end.

If it names no log, ask where it is. Work in a scratch folder (the session's scratchpad if it
has one).

`scripts/papercut_log.py` (stdlib Python, run with `python3`; full usage in its docstring)
does the reading and editing:

| command | what it gives you |
|---|---|
| `summary LOG [filters]` | entry and open counts, counts by project group and by date |
| `export LOG OUT.json [filters] [--batches N]` | entries as JSON for triage; with `--batches`, N files balanced by group |
| `sections GOTCHAS` | the gotchas file's `##` headings with line counts |
| `prs LOG --owner O…` | every PR or issue the log cites, with state, and age, size, checks and review for open PRs |
| `merge LOG TRIAGE… --overrides O.json --gotchas G --plan P --review R` | the first-apply plan, plus a review file listing every decision in full |
| `apply PLAN [--write --backup-dir D]` | the diff and totals; writes only with `--write` |

Filters are `--since`, `--project`, `--ids` and `--exclude-ids`, and the last two take
`@file`. Use the script instead of reading the whole log into context or writing one-off
edit code. Rewriting the log with the Write tool loses anything another session appended
after you read it. The script addresses entries by a hash of their text, re-reads both files
at write time, keeps new lines, and refuses an entry that changed.

## 1. Close out the last sweep

Run `prs LOG --owner <each owner>`. A `(guess)` row came from a bare `#N`, resolved against
the entry's own repo, so check that it is the right one before acting on it.

- **Merged or closed as done:** the entry that cites it can go, unless it also carries an open
  question.
- **Closed unmerged:** read why (`gh pr view N -R owner/repo --comments | tail -30`) and bring
  the reason to the user. The entry stays until they decide.
- **Still open, from an earlier sweep:** ask about these before triage, as one short question
  listing each PR's age, size, checks and review state. Offer to walk through them (a diff
  summary each, then merge, close or leave), or to carry on. Unmerged sweep PRs are the
  cheapest wins available, and their outcome changes which entries are still live.

**See which hints fired.** The hint hook appends every line it delivers to
`~/.claude/gotcha-hints.jsonl` (or `$GOTCHA_HINTS_LOG`), by line id. `gotcha_hints.py check`
prints the ids. A papercut logged after its line fired means the line arrived and didn't
help, so rewrite it. A papercut whose line exists but never fired means the trigger missed,
so widen it.

## 2. Size it up and batch it

Run `summary LOG` with the user's scope. With no scope given, sweep everything.

**Defer live work.** Run ListAgents (subagents can't), and map each live session to a project
group by its name before any `--`. Entries dated today from a project with a live session may
describe work in progress, so give them `keep`.

**Pull out the cross-project clusters before batching.** Export everything and skim one line
per entry (`symptom` is the second ` · ` field). Look for causes that recur across projects:
Claude Code's own guards and permission classifier, MCP servers, shell behavior, git and gh
quirks. Batching by project would split such a cluster across every agent, and each would
draft a competing line for the same rule. Triage those clusters yourself, or give each one its
own batch, and record which ids belong to which cluster.

**Batch the rest.** About 30 entries or fewer: triage them yourself. More: run
`export LOG <scratch>/batch.json --exclude-ids @<cluster-ids> --batches N` with N from two to
four. Send each batch to a subagent on the cheapest tier that reads and judges well
(sonnet-class), using `references/triage-brief.md`. Write one shared context file and point
every agent at it. It holds:

- the PR states from step 1;
- the deferred ids;
- the cluster labels and which clusters you own;
- the repo paths and owners;
- what must not be quoted.

Reading entries and checking repos is legwork. Joining clusters across batches and deciding
what the user sees is the judgment that stays with you.

## 3. Give every entry one outcome

| outcome | when | result |
|---|---|---|
| delete | resolved, one-off, already covered by a gotchas line or a repo doc, or superseded by a later entry | removed |
| gotcha | the answer is settled and holds wherever the tool is used | one line under that tool's `##` heading, ending in a trigger; entry removed |
| repo note | the quirk matters only inside one repo | 1–3 lines for that repo's CLAUDE.md, proposed; entry held |
| repo fix | a small code, script or config change would stop it, and it is still present on the default branch | proposed as a PR; entry held |
| machine fix | a shell option, global ignore, setting or permission rule would stop it recurring | the exact change, proposed; entry held |
| open | needs the user's decision, or waits on something outside | stays, with the third field rewritten to `OPEN: <who decides what>` |
| keep | a tracking line whose PRs are still open, or an entry you deferred | left as it is |

Several entries that one line covers: give the line to one of them, and give the rest
`same_as` pointing at it, so counts stay honest and `merge` removes them all.

What earlier sweeps learned:

- **Check the default branch before proposing a repo change.** Fetch and read `origin/HEAD`,
  not the local checkout, which may sit on a feature branch. In two sweeps, 6 of 10 and then
  14 of 34 candidate changes were already on main.
- **One rule with its boundary beats a list of examples.** A first sweep cleared 17 entries
  with three shell options. A later one turned 19 refusals from one guard into a single line
  that states what the guard refuses.
- **Write gotcha lines for the moment they're needed.** Lead with what the next session will
  see (the error text, quoted verbatim, or the odd behavior), then `→` and what works. Match
  the file's voice, and replace an existing line (`replaces` holds its first words) before
  adding a near-duplicate.
- **Give each gotcha line a trigger.** The plugin's hint hook (`hooks/gotcha_hints.py`) hands
  a line to a session at the call that needs it, and never loads the whole file, so a line
  with no trigger reaches only a session that greps for it. End the line with a comment:
  `<!-- error: <the verbatim error text> -->` for a failure, `command: <regex>` for a
  command shape that goes wrong, `tool: <tool name>` for one tool, and `in: worktree` to
  limit it to worktree sessions. Leave a line untriggered only when nothing distinctive marks
  the moment. Check triggers before they're written (step 5).
- **An unknown cause with no recurrence in about two weeks is a one-off:** delete it. If it
  recurs, keep it as `OPEN: cause unknown; <what would settle it>`.
- **Measured or published numbers are the user's call**, even when the fix looks obvious. Mark
  the entry open and state the question.
- **`readlink` a hook, script or setting before calling its fix a machine fix.** If it
  resolves into a repo, the fix is a repo PR.
- **Paths in older entries may predate a move.** Find the current location before judging.

## 4. Show one decision message

Put your own decisions (the clusters, corrections to agents' calls, deferred `keep`s) in an
overrides file. Then run:

```
merge LOG <scratch>/triage-*.json --overrides <scratch>/overrides.json --gotchas G \
  --plan <scratch>/plan.json --review <scratch>/review.md
```

The review file lists every decision in full. Name its path in the message, but don't paste
it: forty full gotchas lines can't be decided in one read. The message holds what needs a
choice, at about a screen:

- **Totals** from `merge`: the log entries before and after, and the gotchas lines added and
  replaced.
- **Gotchas:** cluster lines and rewrites of existing lines in full; other additions as a count
  per section.
- **Delete:** the count, with grouped reasons ("14 fixed on main", "11 already in gotchas").
- **Repo changes:** numbered, per repo: the entries, the proposed note or fix, and what you
  checked on the default branch.
- **Machine fixes:** the exact command or setting.
- **Open:** the question each one puts to the user.
- **Left alone:** the deferred and kept entries, one line each.

Ask which repo changes and machine fixes to make (AskUserQuestion with multiSelect, or
numbers when there are more than four). Their answer also approves the log and gotchas edits
in the plan. Fold any line they change back into the overrides and run `merge` again.

## 5. Apply the log edits

Run `apply <scratch>/plan.json --preview-dir <scratch>/preview` and read the diff. Then check
the triggers in the planned gotchas file against real work. `scripts/transcript_corpus.py
<scratch>` extracts the Bash commands and failed tool results from the user's transcripts, and
an expect file holds each promoted entry's own error or command with the line id it should
fire:

```
python3 -I <plugin>/hooks/gotcha_hints.py check <scratch>/preview/<gotchas file> \
  --commands <scratch>/commands.jsonl --errors <scratch>/errors.jsonl --expect <scratch>/expect.jsonl
```

Fix any trigger that misses its own entry or fires on more than about 1% of commands (noise),
then run `apply <scratch>/plan.json --write --backup-dir <dir>`. For `<dir>`, use the dated folder
that earlier tracking lines in the log name, with today's date, or
`~/.claude/papercut-backups/<date>/` if there is none. The first backup in a folder is kept,
so it stays the pre-sweep copy however many times you apply, and each written plan is copied
in beside it with its reasons.

Held entries stay until their change exists. After the PRs are open and the machine fixes are
made (step 6), write a small second plan:

- delete the held ids that landed;
- prepend one tracking line that step 1 of the next sweep reads;
- apply it to the same backup folder.

```
- <date> · papercut sweep: PRs awaiting review: owner/repo#N, owner/repo#M · delete this line once they're merged; the pre-sweep log is in <backup dir> · <project>
```

## 6. Make the picked changes

For each picked repo, send a subagent (sonnet-class) the brief in
`references/repo-fix-brief.md`. Run them in parallel, at most four at once, and give several
small repos to a single agent. Each works in a worktree off a freshly fetched default branch,
leaves the user's checkout alone because other sessions may be working there, opens one PR,
and does not merge. Agent hand-backs are reports, not approvals.

Before any text reaches GitHub, check it against the user's confidentiality rules. When an
entry quotes data from another repo, compare both repos' visibility
(`gh repo view --json visibility`); real data from a private repo does not belong in a public
one.

For machine fixes, use the update-config skill for Claude Code settings. Shell rc files,
settings and permission edits are often denied in auto mode. When that happens, give the user
the exact line to run as `! <command>`, and don't retry.

## 7. Report

Run `summary LOG` again and report:

- the entry count before and after;
- where entries went: gotchas added, PRs with links, machine fixes, deleted, still open;
- the questions the open entries put to the user;
- anything the user has to run themselves;
- the review file and backup folder paths.

Clear the claim from "Before you start". A sweep fills a lot of context, so suggest a fresh
session for whatever comes next.
