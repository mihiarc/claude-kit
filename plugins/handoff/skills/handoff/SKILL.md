---
name: handoff
description: Write a self-contained kickoff prompt so a NEW session inherits this session's frame (goal, sources, assets, settled decisions, deliverables, biggest risk), saved to ~/.claude/handoffs/<repo>.md. Use for "write a prompt for a new session", "hand off to the next session", "kickoff prompt for <task>", "session handoff".
metadata:
  author: mihiarc
  version: "3.0"
---

# handoff

Write a **kickoff prompt for a fresh Claude Code session** that will take on a specific next
task. The reader has **none of this conversation's context**, so the prompt must be
self-contained *and* let that session **inherit the frame** (commitments, existing assets,
conventions) instead of re-deriving it cold or rebuilding what exists. The output is a *prompt*,
not a plan or an implementation: it sets the new session up to (1) inherit the frame, (2) de-risk
the biggest unknown early, (3) confirm a few decisions with the human, then (4) build.

`references/writing-guide.md` holds the longer guidance summarized here (contradictions, thin
projects, length, the check_refs report, the subtractive pass, quality bars). Read the relevant
section when you hit that situation.

## What actually makes these good

**Naming a document is not transmitting its content.** `see CLAUDE.md — boundary rules` costs the
next session a full read and a guess at which part mattered;
`disturbance/ may import common/ and external libs, NEVER species/ or age/ (CLAUDE.md rule 1)`
costs you one line and transmits the constraint. **Carry the load-bearing rule, number, or gotcha
inline; cite the path so it can be checked, not so it can be looked up.**

**Invented specifics are worse than absent ones.** A wrong path or fabricated section number
sends the next session somewhere that doesn't exist and destroys its trust in the rest of the
prompt. Verify before you write (Step 6). If you can't verify it, say what you actually know.

**A claim that something does NOT exist is a claim, and needs the strongest evidence of all.**
"There's no test suite", "no such module anywhere in the workspace", "Table 3 doesn't exist yet"
read as authoritative and usually carry an instruction ("don't go looking", "build it"), so a
wrong one sends the next session to rebuild something that exists or to stop hunting for
something that's right there. Absence *feels* verified after one failed grep. Three rules:

- **Open the artifact that would contain it.** Establish absence by inspecting the thing itself —
  the document, the module, the table — not a placeholder, tracking doc, index or stale header.
  `*Insert Table 3 Here*` in the body is a layout convention, not evidence the table is missing.
- **Run the control test.** Before concluding "X is absent because I don't see signal S", check
  something you *know* exists: if Tables 1 and 2 exist and show the same placeholder, S proves
  nothing and your search is measuring the wrong thing.
- **Scope the claim to what you actually searched.** "Not under `src/nrt_fire/`" is honest;
  "nowhere in the workspace" needs a workspace-wide search to back it.

## When to use

When the user asks for a prompt to start the next session, hand off the next task, or a
"spin-up"/"kickoff" prompt; or when work just finished and there's an obvious next item (a
"Next" line in a project journal, the next agenda item, an open TODO). Not for planning *this*
session (just do the work) or one-off questions.

It usually runs **mid-session at a deliberate transition point**: the user watches their context
fill (often around half) and hands off early so the work transfers cleanly. So **context is the
scarce resource and you are spending the user's** — don't re-explore a repo you've been working
in; delegate verification and broad searches to subagents; targeted checks over tours. And **the
conversation's knowledge is the perishable part** — harvest dead ends, settled arguments and the
reasons behind hard-coded values first (Step 2, item 6). If the work is mid-thought and messy,
say so and note what's unfinished (item 7) instead of implying a clean boundary.

## Step 1 — Pin the target task

Get a single-sentence statement of what the next session should accomplish. If the user named it,
use that. If they gestured vaguely, find the canonical next item (agenda/roadmap doc, open TODO or
punchlist, a journal's "Next" line) and propose it back in one line. If it's genuinely ambiguous
between candidates, ask. State it as a goal with a *why* and a *scope boundary* (what it does and
does **not** touch).

**If your investigation contradicts what the user told you** (the PR they called merged is open,
the deadline already passed), **tell them before you write the prompt**, in one line, with how it
changes the task; if it changes *what the next session should do*, confirm the new target first.
If they aren't there, write the prompt for the corrected task, put the contradiction at the top of
what you show them, and have the prompt verify the corrected premise first (writing-guide:
"When your investigation contradicts the user").

## Step 2 — Gather the frame

**First ask whether you already have it.** Handing off the next step of your own work means the
docs, conventions, assets and rationale are already loaded — write from that and spend your
effort *verifying the specifics you'll commit to paper* (paths, section numbers, row counts,
branch state). A session that just re-read forty files writes down what it *found* (inventory)
instead of what *matters* (mechanism). Do broad discovery only when the next task is genuinely
adjacent (another subsystem, an unfamiliar repo), delegated to subagents, and confirm specifics
yourself. Either way, **verify every path and section number you cite** (Step 6). Gather:

1. **Conceptual framing** — the docs carrying the "why", with exact files and section numbers
   (quote the heading text with the number), and the **actual commitments** pulled out of them.
2. **Canonical / out-of-repo sources of truth** — manuscripts, specs, upstream docs, decisions
   outside the repo. Easy for a fresh session to miss; exact paths.
3. **What already exists — don't rebuild.** Data (row counts/shapes), fitted params/artifacts,
   modules/functions, prior figures/scripts, just-merged work. Path plus one line each.
4. **Conventions** the task will actually hit — package manager and run commands, tests,
   versioning, commit/PR norms (including any **no-AI-attribution** rule), how results are checked.
5. **Project journal, if one exists** (Notion entry, `CLAUDE.md` status section, memory file):
   point at it and pull status and open items. **If there isn't one, don't invent one.**
6. **What this session learned that isn't written down** — usually the most important item and
   the most often skipped: the approach that failed, the library that doesn't do what its docs
   claim, the value hard-coded for a reason, the question already settled with the human. State
   it plainly ("X was tried and fails because Y — don't retry"; "Z was settled with <person> on
   <date> — don't reopen"). Scan back through the conversation rather than trusting memory.
7. **The state you're leaving the workspace in** — uncommitted files, branch, pushed or not,
   anything half-finished. Work only on an unmerged branch is load-bearing: a session starting
   from `main` will rebuild it. Check, don't assume.

**Thin projects** (a punchlist and a pile of files): walk a stale tracking doc's items to closure
(done / open / blocked on someone) instead of declaring it historical, drop empty sections, and
never invent a convention to fill a slot. A short honest prompt beats a complete-looking one built
on invented structure (writing-guide: "When the project is thin on structure").

## Step 3 — Surface the decisions to settle first

List the non-obvious or hard-to-reverse choices the next session must make **before heavy
implementation**, numbered. For each, state the options crisply and a **recommended lean** ("I
lean X because…") — a lean lets the human reply "yes to all"; a bare menu hands the work back.
Tell the new session to **confirm these with the human before building**.

## Step 4 — Name the early caveat (+ pivot)

Name the single biggest **dependency, unknown, or risk** — a tool that may not work, a data source
that may not exist, a parameter with no clean provenance. Tell the new session to **verify it
first**, with an explicit **pivot**: a reduced-but-still-valuable deliverable if it fails. Never
just "this might not work." Flag it in one line in the Goal block; the full caveat and pivot get
their own section. If there's a tempting shortcut that would give a plausible wrong answer (a
fudge factor forcing two series to agree), give it its own **Guardrail** line: scope says what's
out of bounds, a guardrail says what looks tempting and is a trap.

## Step 5 — Write the prompt

Length tracks how much real frame exists; every word spends the next session's context before it
does any work. Per line: **would the next session act differently if this weren't there?** If
not, cut it. **Mechanism beats inventory** — the closed enum, the hard-coded threshold, the schema
mismatch behind the blocker earn space; file lists, repo tours, contract dates and org context
usually don't (writing-guide: "Length, and mechanism over inventory").

The shape below is the default, not a fixed form: drop empty sections, add one if needed. **Goal**,
**Read first** and **Caveat** are not droppable — Read-first is what the next session reads to
inherit the frame. If the handoff covers **two tasks**, give the second its own block.

```
Goal: <task in one or two sentences — what, the WHY, how it relates to prior work, and
explicitly what it does NOT touch.>
<1–2 sentences of essential framing that motivates the task.>
<One line flagging the biggest risk and the first thing to verify — the full statement
lives in the Caveat section below; this is just so it can't be missed.>

== Read first (inherit the frame) ==
- <framing doc> §<n> "<heading text>" — <the commitment/constraint it establishes, stated>
- <canonical / OUT-OF-REPO source> at <exact path> — <what to extract from it>
- <related code/module to study> — <the pattern to mirror, named>
- <the load-bearing rules themselves, inline, with their source cited>

== What already exists (don't rebuild) ==
- <DATA>: <path> (<shape/rows>) with <key columns> — <what it's for>
- <FITTED PARAMS / ARTIFACTS>: <path> — load via <how>
- <EXISTING CODE to reuse>: <module/class> — <the pattern to mirror>
- NO <X> code exists yet — this is greenfield (likely <where it goes>).

== Already tried / already settled ==     <whenever this session learned it — usually>
- <approach that failed and why — don't retry it>
- <question already answered by the human or a collaborator, with who and when —
  don't reopen it>
- <value that had to be hard-coded, and the reason>

== Where things stand ==
- Branch <name>, <n> commits ahead of <base>, <pushed / UNPUSHED>. <If the work lives only
  here, say so — starting from the base branch would rebuild it.>
- Uncommitted: <files, and whether they're intentional>
- Half-finished: <anything mid-edit, or a known-failing test and why>

== Decisions to settle WITH ME before heavy implementation ==
1. <decision>: <options>. I lean <X> because <why>; confirm.
2. …

== Deliverables ==
- <the testable core — where it goes, what "done" means>
- <script / figure / doc, in whatever form this project actually produces>
- <validation against a named anchor — bracket vs. reproduce, as appropriate>
- <tests, if the project has tests: the specific properties to check>
- <how the work lands: the project's real branch/commit/PR norm, including any
  no-AI-attribution rule; verify it runs before claiming done>

== Guardrail ==            <only if there's a real trap>
<the tempting shortcut that would produce a plausible wrong answer — don't do it>

== Caveat to surface EARLY ==
<the biggest dependency/risk.> Verify it FIRST; if it doesn't hold, pivot to <reduced but
still valuable deliverable> rather than building on a missing foundation.

Start by reading the frame + <the one thing to verify>, confirm the decisions with me,
then implement.
```

Derive Deliverables from what this project actually produces (era-stamped outputs and CI-safe
tests for a modeling repo; rebuilt figures and a coauthor sign-off for a manuscript that commits
to `main`). Don't import one project's idiom into another.

## Step 6 — Save, verify, hand over

1. **Look before you save.** A project has one live handoff, `~/.claude/handoffs/<name>.md`, where
   `<name>` is the repo's directory name, or a short task slug if there's no repo. It sits outside
   the repo so it can't dirty the working tree. Before writing it, see what's already there:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/prior_handoffs.py" <repo-root>    # or: --name <slug>
   ```
   The script searches every name the project goes by. That means the directory name and the git
   remote's name, so the old file of a renamed repo turns up too. For each earlier prompt it prints
   the date written, its Goal line, and whether a session was launched from it since. It also lists
   companion files. Then, for each entry:

   | Found | Do |
   |---|---|
   | nothing | write `<name>.md` |
   | your own draft from this session | overwrite it |
   | a prompt that was launched after it was written | archive it, then write |
   | an unlaunched prompt for the same task | archive it, then write; yours replaces it |
   | an unlaunched prompt for a different task | ask the user in one line: replace it, or keep both, with yours as `<name>--<task-slug>.md` |
   | a prompt under a former name | archive it, and write under the current name |
   | a variant whose Goal is about another project | leave it |

   To archive, run `prior_handoffs.py --archive <entry>...`. It moves entries into
   `~/.claude/handoffs/archive/` as `<stem>.<date-written>`, and never overwrites one there.

   **Never delete a handoff, and never write over one whose Goal you haven't read.** A launched
   prompt is the record of what the last session was told. An unlaunched one may be work the user
   still means to start. "Not launched" only means no session has named the file since it was
   written. A session may still have done the work without opening the file.

   Files that ship with the prompt (a script, a small table) go in `~/.claude/handoffs/<name>/`,
   and the prompt cites them by full path. When you replace a prompt, archive the companion files
   the new prompt no longer cites.
2. **Verify the references** and fix what it flags in place:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_refs.py" ~/.claude/handoffs/<file-you-saved>.md <repo-root>
   ```
   Each path is `ok`, `creates` (labelled as a deliverable — fine), `PARTIAL` (fix the prefix) or
   `MISSING` (correct, drop, or label as created). Re-run until it exits 0. Write cross-repo paths
   as full `~/`-anchored paths, and grep each cited section heading — the script can't check
   section numbers (writing-guide: "Reading the check_refs.py report").
3. **Subtractive pass** — re-read the saved file *as a separate step*, only to delete. Keep a line
   only if it traces to a Decision, a Deliverable, the Guardrail or the Caveat; the rest is
   inventory (who's on leave, contract dates, repo renames, tours of untouched components,
   anything hedged as "worth knowing") (writing-guide: "The subtractive pass").
4. **Hand over.** The saved file is the deliverable. Always give the launcher line. It names the
   session after the file's stem, which becomes the session's messaging address:
   ```
   claude --name <stem> "read ~/.claude/handoffs/<stem>.md and follow it"
   ```
   A `<repo>--<task>.md` prompt is a second session on a repo, so it gets its own worktree:
   ```
   claude --name <repo>--<task> --worktree <task> "read ~/.claude/handoffs/<repo>--<task>.md and follow it"
   ```
   With it, give the path and a short summary of what the prompt decides and flags. Don't print
   the prompt itself: the new session reads the file. Say in one line what you archived, or what
   you kept beside the new prompt.

## Reference

- `references/writing-guide.md` — the longer guidance behind Steps 1, 2, 5 and 6, and the quality
  bars to check the finished prompt against.
- `references/example-prompt.md` — a complete real example ("size × grade valuation" in a
  timber-accounting research repo) showing the grounding depth to aim for. It's a rich, doc-heavy
  case; a thinner project should produce a shorter prompt, not a padded one.
- `scripts/prior_handoffs.py` — Step 6.1. It lists a project's earlier handoffs under all of the
  project's names, with launch status, and `--archive` moves them aside. Its docstring says what
  the launch check can and can't see.
- `scripts/check_refs.py` — Step 6.2. It checks every path cited in the prompt.
