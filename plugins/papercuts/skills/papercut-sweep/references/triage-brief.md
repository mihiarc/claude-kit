# Triage brief

Fill in the bracketed fields and send one copy per batch. The outcome list and the return
format are the contract that `papercut_log.py merge` reads, so keep both intact.

---

You are triaging one batch of entries from a papercut log. Each entry is a bullet,
`- date · symptom · fix · project`, recording something that slowed a Claude Code session
down. The sweep moves each entry to where the next session will meet it. Your job is to
propose an outcome per entry. Don't edit the log, the gotchas file, or any repo. The only file
you write is your result.

- Batch: [abs path to batch-N.json] (fields: `id`, `date`, `project`, `group`, `open`, `refs`, `text`)
- Shared context: [abs path]. Read it first. It lists PR states already checked, entries
  deferred because a live session owns them, cluster labels (and which clusters the parent
  triages itself), repo paths and owners, and what must not be quoted.
- Gotchas file: [abs path]. Read it in full. It holds settled answers, one line each, under
  `##` tool headings, and it is where `gotcha` outcomes go.
- Write your result to: [abs path to triage-N.json]

Outcomes, one per entry:

- `delete`: resolved, one-off, already covered by a gotchas line or a repo doc, or
  superseded by a later entry. An unknown cause with no recurrence in about two weeks counts
  as a one-off.
- `gotcha`: the answer is settled and holds wherever the tool is used. Propose the line:
  `- <what the next session sees: error text, quoted verbatim, or behavior> → <what works>`,
  in the file's voice, ending in a trigger comment so a hook can hand it to the session that
  hits it: `<!-- error: <distinctive part of the error text> -->`, or `command: <narrow
  regex>` for a command shape that goes wrong, `tool: <tool name>` for one tool, and
  `in: worktree` to limit it (keys separated by `;`, values are Python regexes). Leave out
  the trigger only when nothing distinctive marks the moment. If an existing line covers most
  of it, propose its replacement and put the existing line's first words (enough to match only
  that line) in `replaces`.
- `repo-note`: the quirk matters only inside one repo. Propose 1–3 lines for its CLAUDE.md
  that state the current fact, with no history words ("now", "used to", "after the fix").
- `repo-fix`: a small code, script or config change would stop it from happening again.
- `machine-fix`: a shell option, global ignore, setting or permission rule would stop it
  recurring. Give the exact change. Run `readlink` on a hook, script or setting first: if it
  resolves into a repo, the outcome is `repo-fix`.
- `open`: needs the user's decision, or waits on something outside. Put the whole rewritten
  entry in `line`, with its third field stating the decision: `OPEN: <who decides what>`, or
  `OPEN: cause unknown; <what would settle it>`. Anything that would change measured or
  published numbers is the user's call, even when the fix looks obvious.
- `keep`: the shared context defers it, or it is a tracking line whose PRs are still open.

When one line covers several entries, give the line to one entry and set `same_as` to that
entry's id on the others (their `outcome` can repeat it).

Checks:

- Look at the default branch, not the working tree, which may be on a feature branch:
  `git -C <repo> fetch -q origin`, then `git -C <repo> show origin/HEAD:<path>`,
  `git -C <repo> log --oneline -15 origin/HEAD -- <path>`, or
  `git -C <repo> grep -n <pattern> origin/HEAD`. If the change is already there, the outcome
  is `delete`, with the commit as the reason. Try `git -C` before believing an environment
  note that says a folder is not a git repository.
- Paths in older entries may predate a move. If a path is missing, find where it went before
  judging the entry.
- For `gotcha`, search the gotchas file for the tool and the symptom first.
- Use plain commands with absolute paths, one per call, with read-only `git` and `gh` only.
- Entries that share one cause get the same `cluster` label. Use the shared context's labels
  where they fit.

Write a JSON array to the result path, one object per entry in batch order:

```json
{"id": "a1b2c3d4", "outcome": "gotcha", "reason": "≤ 20 words",
 "section": "gotchas heading, for gotcha", "line": "proposed gotchas line, or the rewritten OPEN entry",
 "replaces": "first words of the gotchas line this replaces, or empty",
 "same_as": "id of the entry whose line covers this one, or empty",
 "repo": "abs repo path, for repo-* outcomes", "change": "proposed note text, fix, or machine change",
 "verified": "what you checked on the default branch", "cluster": "short label, or empty"}
```

Reply with the result path, then at most five lines on clusters and anything you could not
decide.
