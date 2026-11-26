# The interview

One question at a time, in this order, each with a suggested answer. Skip a question an earlier
answer settles, and accept "skip" or "not sure" for any of them: the section stays a fill-in
for later. On a rerun, say what their files say now and ask only whether they want to change it.

## Questions

1. **About you.** "In a sentence or two: what do you mostly use Claude for, and is this computer
   personal, for work, or both? Is there anything that must never be kept on it?"
   → the opening lines of their `CLAUDE.md`.

2. **Git.** "Do you keep your work in git, for example on GitHub? Git is a tool that keeps the
   history of a project's files. If you're not sure, the answer is probably no, and that's fine."
   - **Yes** → "Which folder holds your projects, and which GitHub accounts or organisations are
     they under?" Suggest `~/src` or the folder their repos are in now, if you can see one.
     → "Where things live: Repos".
   - **No** → "Each task gets its own folder, where its notes and files go. Where should those
     folders go? I'd suggest `~/claude-tasks`." → the no-repo lines (below).

3. **Documents for you.** "When Claude writes something for you to read (a summary, a brief,
   meeting prep), where should it go: a folder on this computer, or a document tool you use?"
   Suggest `~/Documents/claude`. → "Where things live: Documents for me to read".

4. **What stays private.** "Is there any work, client or folder whose content must never go
   online (to GitHub, a shared web page or a cloud session)?" → "What stays private", one line
   each: the name and the rule ("never leaves this computer; write a local file instead").

5. **Connected tools.** "Which tools have you connected to Claude, such as Gmail, Google Drive or
   Slack?" Tell them that anything that sends, shares or deletes through those tools asks them
   first. → a "Connected tools" line under "Where things live".

6. **How you write.** "When Claude drafts an email or a message for you, anything it should know?
   For example: how long, how you open, how you sign off." Optional.
   → "Drafting in my voice". Leave the section's fill-in if they skip.

7. **Papercut log.** "Would you like a running list of things that slowed you down, so they can
   be fixed later? I'd keep it at `~/.claude/me/papercuts.md`." Yes → `papercuts` in the answers
   and a "Papercut log" line under "Where things live". No → `papercuts: null` and drop that line.

8. **Skills.** Say which skills the setup links, one line each, and ask if that's right:
   - `start-task`: starts each task in a fresh session with its own folder and notes.
   - `chief-of-staff`: one session that keeps the questions waiting on you and steers the others.
   - `papercuts`: the papercut sweep, and the hook that shows a known fix when a command fails.
   - `verify-setup` (git users only): writes how to check a change in a repo.
   The kit's `.claude-plugin/marketplace.json` lists the others with a line each; mention that
   more exist and add any they ask for. Never `kit-setup` itself: it's already installed.

9. **Status line.** "Claude Code can show a line under the prompt with the session's name and how
   much of its memory and usage limits are used. Want it?" It needs `jq`: check `command -v jq`.
   If jq is missing, say so, suggest skipping it for now, and that they can rerun the setup once
   jq is installed. → `statusline` true or false.

10. **Session names.** "Do you start Claude by typing `claude` in a terminal window?" Yes → the
    kit names each session after its folder, which other sessions use to message it: `shell` is
    their shell (`zsh` or `bash`, from `$SHELL`). No, or the desktop app only → `shell: none`.

11. **Docket.** Only if chief-of-staff is linked: "Chief of staff keeps one list of the questions
    waiting on you. Docket shows that list as a page in your browser, where you can answer and
    sort them. Want it?" Yes → a "Sessions" line in their `CLAUDE.md` (below) and the Step 5
    follow-up.

12. **Another computer.** "Do you use Claude on a second computer?" Git users who say yes are
    offered the private repo in Step 5. Otherwise nothing changes.

## Writing their CLAUDE.md

Start from `starter/personal.md.template` in the kit. Replace each fill-in with their answer,
delete the HTML comments (they are instructions to the person, and the person has now answered),
and delete a section whose question they skipped only if it has nothing useful left; otherwise
keep its fill-in so they can complete it later. Write their words, tightened, in the first
person ("I keep…"). Don't add rules they didn't give.

**No-repo lines** (they don't work in git). start-task reads both facts, so write them as they
stand here, under a `## How I work` section after the opening lines:

```markdown
## How I work
- I don't work in git. Every task takes start-task's no-repo path: a plain task folder with its notes, and no worktree, branch or PR.
- Task folders go in `~/claude-tasks/<task>`.
```

Use the folder they chose in place of `~/claude-tasks`. Then drop the template's "Repos" line.

**Sessions line** (Docket yes): under `## Sessions`:
`- Chief of staff keeps its questions in ~/.claude/chief-of-staff/questions.md and shows them in Docket, its local page.`

**Carrying over.** If `~/.claude/CLAUDE.md` holds the person's own rules (it doesn't import
`starter/core.md`), put each rule under the section of the template it belongs to, and any that
fit none under a `## Carried over` section at the end, word for word. Tell them in the preview
which file they came from; the installer backs that file up when it replaces it. `stage` notes
how many of its lines are missing from the new file, so a dropped line shows up.
