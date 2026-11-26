---
name: start-task
description: Start a task in a fresh Claude Code session. Size it so one session can finish it, settle its open decisions with the user, choose the model and effort level, create its worktree (or, for a task with no git repo, a plain task folder), and write its opening progress record (goal, what is settled and by whom, what failed, the checks that define done, what is out of scope) as a `## Progress` section of that folder's CLAUDE.local.md, which the new session loads at start. Then give the launch command. Use for "start a session on <task>", "set up the next task", "hand this off to a new session", "write a brief for <task>", "split this into tasks for fresh sessions", when work just finished and the next task should start clean, and when a coordinating session dispatches a task. Not for continuing the current task (update its own progress record) or a note to a human collaborator (`human-handoff`).
metadata:
  author: mihiarc
  version: "6.3"
---

# start-task

Start **one task in a fresh Claude Code session**. The method is small tasks in fresh sessions:
each task is sized so one session can finish it, and a task that runs longer keeps a progress
record that the next session on it loads at start. This skill writes that record's **opening
version**, before any session has worked on the task. The reader has none of this conversation,
so the record must be self-contained and let that session inherit the frame (what is settled,
what exists, what failed) instead of re-deriving or rebuilding it.

The record lives in `CLAUDE.local.md` at the root of the folder the task runs in, as a
`## Progress` section, unless the user's CLAUDE.md names another place. For a task in a git repo
that folder is the task's worktree; for a task with no repo it is a plain task folder (Step 5).
Claude Code loads that file at the start of every session there, and keeps it in context on every turn, so each line costs the
working session for its whole life.

`references/writing-guide.md` holds the longer guidance (contradicting the user, thin projects,
length, the check_refs report, the subtractive pass, quality bars). Read the section you need.
`references/example-record.md` shows the depth to aim for.

## What makes an opening record work

**Naming a document is not transmitting its content.** `see CLAUDE.md — boundary rules` costs
the next session a read and a guess; `disturbance/ may import common/, NEVER species/ (CLAUDE.md
rule 1)` costs one line and carries the rule. State the load-bearing rule, number or gotcha
inline, and cite the path so it can be checked.

**Invented specifics are worse than absent ones.** A wrong path or section number sends the next
session somewhere that doesn't exist and costs it trust in the rest. Verify before you write
(Step 5). If you can't verify it, say what you actually know.

**A claim that something does NOT exist needs the strongest evidence.** "There's no test suite"
tells the next session to stop looking or to build it. Open the artifact that would contain it,
not an index or a placeholder; check the same signal against something you know exists; and
scope the claim to what you searched ("not under `src/fire/`").

**Settle decisions now, not in the record.** This session has the frame loaded, so a question is
cheapest to settle here, with the user, before you write. The record holds the answer and who
gave it. Only a question that truly can't be settled now goes under Open questions, with your
lean.

## Step 1 — Pin the task and size it

State the task in one sentence, with its *why* and its boundary. If the user named it, use that;
otherwise find the canonical next item (a progress record's Next, a roadmap, an open TODO) and
propose it in one line. Ask if it's ambiguous.

Then decide **whether the task has a repo**. A task that changes files in a git repo takes the
git path: a worktree, a branch, a PR and the repo's verify skill. Any other task takes the
no-repo path, with none of those four: a document, an email, a form, an errand, and code or data
in a folder that isn't under git. When the user's CLAUDE.md says they don't work in git, every
task takes the no-repo path. Ask if it's unclear.

Then check the size: **can one session finish it?** If not, split it into tasks that each can,
and start the first (or each, if the user wants them run in parallel). If what you found
contradicts what the user said (the PR they called merged is open), tell them in one line before
writing, and confirm the target if it changes (writing-guide: "When your investigation
contradicts the user").

## Step 2 — Gather the frame

If this is the next step of your own work, you already have it: write from that, and spend your
effort verifying the specifics you'll commit to paper. Delegate broad discovery to a subagent
only when the task is in unfamiliar territory. Gather:

1. **The commitments** that constrain the task, stated, with the file and section that hold them.
2. **What already exists**: data, artifacts, modules, just-merged work. Path plus one line each.
3. **What this session learned that isn't written down**, the item most often lost: the approach
   that failed and why, the value hard-coded for a reason, the question the user already settled.
   Scan back through the conversation rather than trusting memory.
4. **How the repo verifies a change** (git path): its `.claude/skills/verify/SKILL.md` if it has one, its CI, and its test and build commands. If it has no verify skill, the task's first step is writing one with `verify-setup`; if it has no CI, say so in the record.
5. **The base** (git path): the commit the task starts from. Work that lives only on an unmerged branch or
   in uncommitted files is load-bearing; a worktree holds committed files only.
6. **The checks that define done**: the test, command, number or figure that shows the task is
   finished. If the project has no tests, name what the user will look at instead. For a task
   with no repo, the checks are always what the user will look at (the document, the sent draft,
   the filed form) and what it must show.

Rules the user's CLAUDE.md already states need no repeating; the next session loads them. Don't
invent a convention to fill a slot (writing-guide: "When the project is thin on structure").

## Step 3 — Settle what you can

List the non-obvious or hard-to-reverse choices the task needs, each with your lean, and put them
to the user now. Their answers go under **Settled**. What they defer goes under **Open
questions**, still with your lean, so the working session can get a one-word answer. If the work
reports to another session, say so in the record, with that session's name.

**Choose the model and effort yourself**; don't ask the user. Pick the cheapest that can finish
the task, unless the user's CLAUDE.md sets a rule. Mechanical, well-specified work whose checks
are clear (a rename, a sweep, a scripted data pull) gets a smaller model such as `sonnet` and
`low` or `medium` effort. Work that needs judgment, design or open-ended debugging, or where a
plausible wrong answer would be costly, gets the strongest model (`opus` or `fable`) and `high`
effort. When it's unclear, leave both out and the user's defaults apply. Record the choice under
Settled with a one-line reason, so a later relaunch of the task uses the same choice.

Name the single biggest risk (a tool that may not work, data that may not exist) with a **pivot**:
a smaller result still worth having if it fails. If there's a tempting shortcut that gives a
plausible wrong answer, name it as a trap under Out of scope.

## Step 4 — Write the record

```markdown
## Progress

Task: <the task in one or two sentences: what, why, and how it relates to prior work.>
Risk: <the biggest unknown, to check first, and the pivot if it fails.>   <omit if none>

### Read first
- <file> §<n> "<heading>": <the commitment it carries, stated>

### Already exists (don't rebuild)
- <path>: <what it is, one line>

### Settled
- <decision>: <the answer>. (<who>, <date>)
- <approach tried>: fails because <why>. Don't retry.
- Model <alias>, effort <level>: <one-line reason>. (<the session that started the task>)
- Verification: run the repo's checks and its `verify` skill before opening a PR, never open one on a failing check, end the PR body with a `Verified by:` line, and after three failed rounds on the same check stop and report. (user's CLAUDE.md "Verification")

### Done when
- <end-to-end check>: <what drives the real thing (the repo's `verify` skill, or the app, API, live session or pipeline run if it has none) and what it must show>
- <check>: <the command, test, number or figure, and what it must show>
- Independent review: before anyone is asked to merge, <who reviews: a fresh subagent given the diff and the repo's rules but not your conclusions, the `code-review` skill at `high` in a fresh context, or the session this task reports to> reviews the PR. Fix the confirmed findings, let CI rerun at the new head, and add a `Reviewed by:` line beside `Verified by:`: who reviewed, what they found and what was fixed.
- <how the work lands: the project's branch, commit and PR norms, and the PR's `Verified by:` line>

### Out of scope
- <what this task does not touch, and the trap to avoid if there is one>

### Open questions for <user>
1. <question>: <options>. I lean <X> because <why>.

### Done

### Next

### Branch
- <branch>, from <base> at <sha>. Nothing committed yet.
```

A **task with no repo** has no PR to verify, review or merge, so its record drops the
Verification line under Settled, the review and landing lines under Done when, and the Branch
section. Its Done when names what the user will look at and what it must show: the document and
where it lives, the draft waiting in their mail, the form and its confirmation.

Drop an empty section, except **Done**, **Next** and (in a repo) **Branch**, which the working
session fills. **Task**, **Done when** and **Out of scope** always stay. Keep a line only if the next
session would act differently without it; inventory (file tours, org context, dates that change
no action) goes (writing-guide: "Length, and mechanism over inventory"). Results and decisions
that live in git, a PR or another record are cited, not copied.

A **subagent** in this session gets the same content inline in its Agent prompt, with no file.

## Step 5 — Create the worktree or task folder, write, check

1. **Create the worktree** for a task in a git repo, from the main checkout:
   ```bash
   git worktree add .claude/worktrees/<task> -b worktree-<task> <base>
   ```
   This is the layout `claude --worktree` uses, and Claude Code never sweeps a worktree made
   with `git worktree add`. If `.claude/worktrees/<task>` already exists, it is another task's or
   an earlier start of this one: read its `## Progress` before doing anything, and pick another
   name unless it is this task. If the repo has a `.worktreeinclude` (gitignored files a worktree
   needs, such as `.env`), copy the files it matches into the same paths in the new worktree,
   because only a worktree Claude creates gets them. Confirm `CLAUDE.local.md` is ignored there
   (`git check-ignore -q CLAUDE.local.md`); if it isn't, tell the user before writing it.

   **Choose the task folder** for a task with no repo. One folder holds one task.
   - **The task's material already lives in a folder outside git** (the folder this session runs
     in, or one the user names): use that folder. Ask if it's unclear which folder holds it.
   - **Otherwise make a new one** with `mkdir -p`, where the user's CLAUDE.md says task folders
     go, or at `~/claude-tasks/<task>` if it names no place. `<task>` is a slug specific to this
     task, in lowercase letters, digits and hyphens (`land-trust-cover-letter`,
     `tax-forms-2026`), never a generic word such as `draft`, `notes` or `task`. If that folder
     already exists and isn't empty, it is another task's or an earlier start of this one: read
     what is there, and pick another slug unless it is this task.

   Then check the folder, and if a check fails, change the folder as it says or tell the user:
   - **Not inside a git repo.** `git -C <folder> rev-parse --is-inside-work-tree` fails with
     `not a git repository`. If it prints `true`, the record could be committed with that repo,
     so take the git path or another folder.
   - **Not a broad folder.** Never the home folder, a catch-all under it (`~/Documents`,
     `~/Desktop`, `~/Downloads`, a cloud-drive root), or a folder with git repos below it
     (`find <folder> -maxdepth 3 -name .git -print -quit` prints a path). A `CLAUDE.local.md`
     loads into every session started anywhere below its folder, and it stays there after the
     task is wrapped up. Make a subfolder for the task instead, and cite the material by its
     full path.
   - **No other task's record.** If its `CLAUDE.local.md` has a `## Progress` section, read it.
     Unless it is this task, give this task its own folder (a subfolder, or a new folder as
     above), and never add a second section or overwrite the first.

2. **Write the record** into the folder's `CLAUDE.local.md` (the worktree's, or the task
   folder's), appending if the file holds other notes. If the repo needs setup (`uv sync`, `npm install`), make it the first item under Next.

3. **Check the references**, and fix what it flags:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/check_refs.py" <folder>/CLAUDE.local.md <folder>
   ```
   Each path is `ok`, `creates` (labelled as a deliverable), `PARTIAL` (fix the prefix) or
   `MISSING` (correct it, drop it, or label it as created). Write cross-repo paths as full `~/`
   paths, and grep each cited section heading yourself (writing-guide: "Reading the check_refs.py
   report"). Then re-read the record once with the single aim of deleting (writing-guide: "The
   subtractive pass").

## Step 6 — Launch

Give the user the launch command; the user's CLAUDE.md may name its own form, or a wrapper for
some kinds of work. Otherwise:

```bash
cd <folder> && claude --name <name> --model <alias> --effort <level> "Start on the task in CLAUDE.local.md's Progress section."
```

`<folder>` is the worktree or the task folder. The name is `<repo>--<task>` for a task in a
repo. For a task with no repo it is the task's slug: the new folder's name, or, for an existing
folder whose name has spaces or capitals or is generic (`Notes`, `New Folder`), a slug made as
in Step 5. Leave out `--model`
and `--effort` if Step 3 chose the user's defaults. Add `--bg` to run it as a background
session. Launch it yourself only when the user asks, or when you are the session that dispatches
tasks.

Then tell the user the folder's path, the Task line, anything under Open questions, and the
command. Don't print the record: the next session reads it.

## Reference

- `references/writing-guide.md`: the longer guidance behind Steps 1, 4 and 5, and the quality
  bars to check the finished record against.
- `references/example-record.md`: a complete opening record for a task in a research repo,
  showing the grounding depth to aim for. A thinner project should produce a shorter record.
- `scripts/check_refs.py`: Step 5.3, checks every path the record cites.
