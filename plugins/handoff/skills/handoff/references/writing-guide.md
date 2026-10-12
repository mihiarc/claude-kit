# Writing and trimming a handoff prompt — detail

Loaded on demand from `SKILL.md`. These sections were moved out of the main file so the skill
costs less context each time it runs; the rules in `SKILL.md` are the short form of what is
here.

## Contents

- [When your investigation contradicts the user](#when-your-investigation-contradicts-the-user)
- [When the project is thin on structure](#when-the-project-is-thin-on-structure)
- [Length, and mechanism over inventory](#length-and-mechanism-over-inventory)
- [Reading the check_refs.py report](#reading-the-check_refspy-report)
- [The subtractive pass](#the-subtractive-pass)
- [Quality bars](#quality-bars)

## When your investigation contradicts the user

This happens often and matters more than it looks: the user says "the South pass is done and
merged" and you find the PR still open; they say "the deadline is coming up" and it passed last
week. Their mental model is a session or two stale.

**Tell the user before you write the prompt.** Don't silently encode the correction, and don't
silently accept the wrong premise — a handoff built on a false premise sends the next session
confidently down the wrong path, which is worse than no handoff. State what you found in one
line, say how it changes the task, and proceed on the corrected footing. If the correction
changes *what the next session should do*, confirm the new target before continuing.

If the user isn't there to answer, don't stall and don't quietly pick the original framing:
write the prompt for the **corrected** task, put the contradiction and your reasoning at the top
of what you show them, and have the prompt tell the next session to verify the corrected premise
as its first move.

## When the project is thin on structure

Not every project has numbered docs, a roadmap, and a test suite. Manuscript revisions, one-off
analyses, and early spikes often have a punchlist and a pile of files at the repo root.

When you find that a tracking doc is stale — a punchlist mostly already applied, a roadmap
overtaken by a branch — reframing it is right, but **finish the job by walking its items to
closure anyway.** Say which are done, which are still open, and which are blocked on someone
else. Declaring the list historical and stopping there is how a genuinely open item silently
falls off the handoff, and it's the one thing the next session cannot recover, because you've
told it the list doesn't matter.

Match the project you actually have. Drop sections that would be empty, and never invent a
convention to fill a slot — a fabricated "era-stamped outputs" instruction for a project that
commits straight to `main` teaches the next session something false. **A short honest prompt
beats a complete-looking one built on invented structure.** When the real constraint is external
(a coauthor's sign-off, a collaborator's data drop), say so plainly and mark those items as
blocked rather than as work the session can do.

## Length, and mechanism over inventory

There's no character cap. But there is a real cost, and it isn't aesthetic: **the prompt is the
first thing the next session loads, so every word you write spends that session's context budget
before it does any work.** The whole reason this handoff exists is that the user is protecting a
context budget — handing off early, on purpose, to get a clean start rather than a degraded one.
A 25,000-character prompt hands the fresh session a meaningful chunk of that budget already
spent, which partly defeats the point of handing off at all.

So: length should track how much real frame exists. There's no target number worth quoting — a
single-repo task with a tidy roadmap and a cross-repo task with three contradicting design docs
have genuinely different amounts to transmit, and a threshold would just get gamed in one
direction or the other. What matters is the ratio: if the prompt has grown but the Decisions,
Deliverables, and Caveat haven't, you've started *transcribing the repo* instead of *transmitting
the frame*. The fix is to cut inventory (see below), not to trim adjectives — and the subtractive
pass makes that a separate step, because you won't spot it while writing.

The discipline is per-line: **for every line, ask whether the next session would act differently
if it weren't there.** If not, cut it.

What earns space: verified paths, load-bearing rules and numbers, the decisions and their leans,
the caveat and its pivot, anything the codebase does *not* make obvious. What doesn't: restating
what a file's name already says, generic engineering advice, motivational framing, and recaps of
things the next session will read in the first file it opens. Cut prose before you cut content —
if it's running long, tighten sentences and drop redundancy rather than dropping a real
constraint.

**Mechanism beats inventory.** The most common way a long prompt gets worse is by filling up with
*inventory* — lists of files that exist, tours of adjacent repos, contract dates, org context —
while the *mechanism* gets squeezed out: the one closed enum, the hard-coded threshold, the schema
mismatch that is actually why the work is stuck. Inventory is easy to produce and reads as
thorough; mechanism is what the next session cannot re-derive cheaply and is the reason the
handoff exists. When something must go, cut inventory first, and never let a newly-found detail
displace the verified finding that explains the blocker. If you catch yourself describing a
component nothing in the Deliverables touches, that's inventory.

## Reading the check_refs.py report

It lists every cited path and marks each:

- `ok` — resolves.
- `PARTIAL` — the filename is real but the prefix as written is wrong, usually a repo-relative
  path needing its full prefix. Fix the prefix.
- `creates` — doesn't exist, but the prompt says on that line that the task will create it
  (wording like "to create", "does not exist yet", "greenfield"). This is fine and doesn't fail
  the check — it's how you distinguish a deliverable from a broken reference.
- `MISSING` — doesn't exist and isn't described as an output. Correct it, drop it, or label it as
  created.

Re-run until nothing is `MISSING` or `PARTIAL` (the script exits 0 at that point).

Two limits worth knowing. Paths resolve against the single repo root you pass, so bare
repo-relative paths pointing at a *sibling* repo will flag. Don't fix that by re-running against
the parent — **write cross-repo references as full `~/`-anchored paths**, which is unambiguous
for the next session too. And the script cannot check **section numbers** — the other easily
invented reference — so confirm each by grepping the heading out of the doc.

## The subtractive pass

Re-read the saved file *as a separate step*, with the single
purpose of deleting. This has to be its own pass, because the per-line test in Step 5 is applied
while you're writing — exactly when you're most attached to the thing you just spent effort
discovering. A finding being true, and hard-won, is not the same as it being useful to the next
session.

Go line by line and ask: **does this trace to a Decision, a Deliverable, a Guardrail, or the
Caveat?** If it traces to none of them, it is almost certainly inventory, and it goes. These
categories in particular are true, interesting, and nearly always deletable:

- who is on leave, who moved teams, who owns an adjacent workstream
- contract dates, signature status, penalty terms, deadlines that motivate urgency without
  changing an action
- repo renames and directory tours for components nothing in the Deliverables touches
- anything you introduce with a hedge like "worth knowing rather than acting on" — that phrase
  is you noticing it doesn't belong

Cutting here costs nothing: the next session can ask, and the repo still holds the detail.
Keeping it costs that session's context on its first read.

## Quality bars

- **Carries content, not just citations.** The load-bearing rules, numbers, and gotchas are
  stated inline. Someone could act on the prompt having opened none of the linked docs.
- **Self-contained.** No "as we discussed." Spell out paths, filenames, section numbers,
  reproduction commands, and the *why*.
- **Verified references.** Real paths (checked), real section numbers (grepped), real column and
  symbol names. A fabricated path is worse than an omitted one — and a wrongly-asserted *absence*
  is worse still, since it tells the next session to stop looking.
- **Decisions carry a lean**, not just a menu.
- **The caveat has a pivot** — never just "this might not work."
- **Matches the project's idiom** — its real testing/versioning/PR conventions, or its lack of
  them.
- **Every line earns its place** (the per-line test above).
