---
name: human-handoff
description: Hand finished work to a human collaborator who likely has no AI assistant: read the whole exchange so the note adds only what is new, size the handoff to the need (a note alone, one self-explaining file, a few files, a zip, a link), check it the way they will open it, and draft the covering note in the user's voice. The user reads the full note and every readme in chat before any Gmail or Slack draft exists; Claude sends only on the user's explicit word. Use whenever the user wants to send, share, deliver, export or hand off results, files, data, a review or a decision request to a named person, e.g. "send Jeff the displacement series", "package this for Shannon", "get the export ready for my co-author", "draft the email with the results attached", "zip this up for the client", even when they ask only for the email or only for the files. Not for a kickoff prompt to a new Claude session (`handoff`), a published web page (Artifact), or reviewing a drop someone sent the user.
metadata:
  author: mihiarc
  version: "2.5"
---

# human-handoff

Get work ready to go to a **person**, and draft the note that goes with it. Two rules frame
everything:

- **Assume the recipient has no AI assistant.** Every file is something they open and make
  sense of by hand, and every repeated paragraph is something they reread. So send the fewest
  files that carry the work, and say only what they don't already know.
- **The user reads every note before it exists in their account.** A message from their
  account is theirs alone to answer for, so they have to know every word. By default the user
  sends. Claude sends only when the user, having read the final text, says to (step 5).

The sibling skill `handoff` writes a kickoff prompt for a new Claude session. That reader shares
your tools; this one shares nothing.

## What makes a human handoff land

**The note is the one thing everyone reads.** It stands alone on what this is, where each
piece plugs into their work, and the one ask. It adds to the conversation already on record;
it doesn't restate it.

**One file, when one file can carry it.** About half of the user's emailed handoffs are a note
plus a single attachment. A zip is for files that must travel together. A pile of loose files, or the same
data in raw, compressed and subset forms side by side, leaves the recipient guessing which one
matters.

**Explanations travel inside the file.** Put a readme sheet first in a workbook, a dictionary
table inside a GeoPackage, the decision on page one of a brief, and units in column headers.
Then the definitions can't get separated from the data, and there is no README to lose.

**Speak their tools and conventions.** Recipients use Excel, Stata, R, QGIS, Word or just a
browser. Deliver in what theirs reads:
- CSV beside parquet only if they have no parquet reader;
- a GeoPackage in EPSG:4326 so it opens anywhere;
- a standalone HTML that opens by double-click;
- Word with tracked changes when they don't use Overleaf.

Match their key order, names and orientation, and label every row and column with its key. A
headerless matrix once had to be oriented by inference from its diagonal and geography before it
could be used.

**Give them a way to check.** One number they can reproduce ("Georgia sums to 230,918,793 cu
ft/yr; compare EVALIDator") tells them they read the file correctly. That takes no
checksum and no tooling.

**Be plain about limits.** Name what Claude did. Say what failed and why, which values are
placeholders, the data vintages, and any licence or redistribution limit.

**The user answers for every word that travels.** A readme is part of the message: a readme
sheet, a README.txt, a dictionary table's descriptions, a document's cover page. The user reads
each one in chat, verbatim, just as they read the note (step 5). Any other prose in the files that
the user won't personally review, such as a generated methods write-up or a long document, says
plainly that Claude wrote it. That statement sits where the reader meets the prose (a document's
first page, the top of a sheet) and invites the recipient to scrutinize those parts. The note
says so too.

## Workflow

### 1. Read the whole exchange

Read the **entire thread** in both directions, not only the latest message, plus earlier
threads or DMs with the same person on the topic. Use Gmail `search_threads` by participant and
topic words, then `get_thread` in `PLAIN_TEXT`. For long or several threads, have a subagent
build the ledger below; it keeps the thread text out of the main context. Also read the repo's
CLAUDE.md and memory for this person's contract (formats, key order, who is cc'd, shared
folders), and the previous handoff folder to them, if any.

Write a short **ledger** into `note.md` (step 5). It is for the user and is never sent:

- **Already sent:** files and versions, with dates.
- **Already said:** facts, explanations and caveats they have heard.
- **Their asks:** each one with its status: answered (where), answered now, or deferred.
- **Open commitments,** on either side.
- **Their words for things:** the names they use for files, variables and methods. Use those.

The note then carries only what's new. When pointing back helps, do it in one clause ("two
updates since my note of 09-19", "the 09-19 series"). Don't re-explain what they told you,
re-list earlier attachments, or recap earlier emails.

If the format, key order or the tool they'll use is still unknown, ask the user one to three
specific questions. Guessing a contract is how handoffs fail.

**Confidentiality.** Trace each file back to its inputs. Stop and ask if anything derives from a
source the user treats as confidential. Data the user's instructions mark as confidential never leaves
this machine, and aggregates of it go only with the user's explicit OK. Also stop on anything the user marked
sensitive, and on other people's unpublished material. When data can't leave either side,
send code for them to run instead (a query or script, plus what to send back).

### 2. Choose the shape

| Shape | When | What they receive |
|---|---|---|
| Note only | an answer, a review reply, a decision request | the note |
| **Note + one file** | **the default:** one file can carry it | a self-explaining file |
| Note + two to four files | pieces they'll use separately | each file self-explaining; one line each in the note |
| Note + one zip | files must stay together (GIS layers, HTML with assets, code with data), too many to attach singly, or a type gateways quarantine (bare `.html`) | one zip; README.txt inside naming the entry point ("unzip; open brief.html in any browser") |
| Note + link | too big to attach, a live product, or it must stay on a shared platform | a link, checked to open for them |
| Note + code | the data can't leave | a query or script, and what to send back |

Every file earns its place: would they open it? Leave out logs, intermediates, manifests and
checksums meant for your side; the local record keeps those (step 4). Send one form of each
dataset, the one their tool reads, and a second form only if they can't read the first. Add an
editable twin (`.docx` or `.md` beside a PDF or HTML) only when they'll comment or edit.

### 3. Build it

**Where:** follow the repo's existing convention if it has one (`share/`, `handoff/`,
`output/<name>_handoff/`, superseded drops in `archive/circulated/`). Otherwise use
`output/<recipient>_handoff/<YYYY-MM-DD>/`, where the recipient slug is their lowercase first
name. Confirm the location is gitignored (`git check-ignore -q <path>`); a handoff is never
committed. Outside a repo, ask where it goes.

```
<handoff dir>/<YYYY-MM-DD>/
├── note.md                  header, ledger, note, checksums: the record; never sent as a file
├── <topic>_<YYYY-MM-DD>.<ext>   one-file shape: the file itself
└── <topic>_<YYYY-MM-DD>/        zip shape: the folder, zipped beside it by scripts/package.py
```

**Names** are descriptive, dated, and keep the same stem as the previous drop to this person,
since their code or their folders may depend on it. A rename gets one line in the note.

**Builder script.** When the handoff will recur, build it with a script in the repo (for example
`scripts/export_<thing>_for_<recipient>.py` or `scripts/build_handoff.py`), so the next drop is a
rerun. A one-off can be built ad hoc.

**Making files explain themselves:**
- **Workbook:** a `readme` sheet first. It says what each sheet is, units, the key and its
  order, years, how missing values appear (ideally they don't), coverage, and the source and date.
- **CSV:** units in the column names. If the columns need more than the note can hold, send a
  workbook with a readme sheet instead, or a short dictionary CSV beside it.
- **GeoPackage:** the dictionary as a table inside it, EPSG:4326 for display, and areas
  precomputed in an equal-area CRS (and say which).
- **HTML:** standalone, opens by double-click, with the decision or finding first. Zip it for
  email.
- **Document for review:** Word with tracked changes, or the format they edit in.
- **Prose Claude wrote:** every readme goes to the user verbatim in step 5. A document or section
  the user won't review line by line opens with a plain authorship line, for example: "Claude (an
  AI assistant) wrote this text from the pipeline output. Chris has not reviewed it line by line,
  so please scrutinize it and check any number against the workbook."

In a zip, `README.txt` is plain text and short. It names the entry point first, then gives each
file one line, then conventions, coverage and caveats, and "changed since <date>" if there was an
earlier drop. Paths in it are relative. A home-directory path means nothing to them. The user
reviews it in step 5 like the note.

### 4. Check it the way they'll open it

Reopen every file from disk with the reader their tool uses, not the object you wrote it from:

- **Keys:** complete, unique, in their order (compare against their list file if one exists).
  Leading zeros survive. Names their tool sorts as text are zero-padded.
- **Values:** no NaN, inf or blank cells unless the file says how missing values appear.
  Totals and counts match the source, and conserved quantities stay conserved.
- **Orientation:** rows and columns mean what the file says. Spot-check two or three values by
  hand, including one edge case.
- **Tool limits:** Excel caps at 1,048,576 rows, 16,384 columns and 31-character sheet names.
  Numeric columns hold numbers, not text.
- **Consistency:** every number in the note appears in, or follows from, the files. It matches
  the manuscript and earlier notes, or the note says it changed.
- **Links:** they open for the recipient. Check the sharing setting; a link that works for the
  user can 404 for everyone else.

Then scan and record:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/package.py" <file> [<file> ...]  # one or a few files
python "${CLAUDE_SKILL_DIR}/scripts/package.py" <folder> --zip       # zip shape
```

The script blocks on likely secrets and symlinks, and warns about home-directory paths (including
inside Office files), empty files and bare `.html`. It prints each file's SHA-256 and size, and
which channels the total fits. Copy the checksums into `note.md`, so the user can later tell which
version the recipient has. `--sums` puts a `SHA256SUMS.txt` inside the zip, for recipients who
verify drops. Rerun the script after any change.

### 5. Draft the note, then show it to the user

`note.md` holds the record. It has a header, the ledger from step 1, the checksums from step 4,
and the note itself:

```
Channel: Gmail reply | Slack DM <name> | new email
Thread:  "<subject>" (<thread id>), replying to <message id> from <sender>
To: <addresses>   Cc: <addresses>
Attach:  <file> (<MB>), attach by hand      | Link: <url>, sharing checked
Status:  Not sent. <User> sends.
```

**The first sentence is plain, human language that sets the context.** Say it the way you
would say it to the person across a table: what this message is and why now, in their terms.
Use their name for the file, the meeting or the question, and no line numbers, internal codes
or jargon. The news or the purpose goes in that sentence or a short second one; there is no
preamble paragraph. The specifics start after that.

Why: the first line is the one most read, and the one the inbox preview shows (GOV.UK Service
Manual; Nielsen Norman Group). Busy readers skim, and they decide from the opening whether and
how to read the rest (Rogers and Lasky-Fink, *Writing for Busy Readers*).

- Starts in the weeds: "v6.3 fixes the Set 2 population and the double if, and land now shrinks
  with displacement."
- Sets the context: "I went through the v6.3 and v5.7 files you posted Monday. Most of the fixes
  are in; four things are still open, and I have one request at the end."
- One file: "Here's the county displacement series you asked for last week, as one Excel file
  with a readme sheet."

**The body is built for skimming.** Most readers scan, and a busy one goes straight to the part
they need. So every block should be findable, and usable on its own:
- **Order.** After the opening comes the ask, or the pointer to the attachment when the file is
  the point. The items and background follow. A reader who stops after the ask should still know
  what you need from them.
- **Paragraphs.** One idea each, two to five lines, key words first, and a blank line between
  them. Write each paragraph as one unbroken line, with no hard wraps, so phones can reflow it.
- **Lists.** Use one for three or more parallel items, after a lead-in line ("Still open in the
  posted files:"). Start each item with the words that tell it apart, then the action, then the
  reason. Number the items when the reader will answer them one by one, or when order matters;
  otherwise use bullets.
- **Space.** End each list item with one extra Enter, so a blank line separates the items and
  the list never reads as one block of text. That is how the user writes lists; nothing more
  is needed inside an item.
- **Labels, not headings.** A short email gets plain labels ("Request:", "Still open:") and no
  headings.
- **Labels in lists.** When a list item opens with a label phrase ending in a colon
  ("Classification:", "mortality_2026-09-29.xlsx:"), bold the label. That holds in the note's HTML
  body and in documents (Word, HTML, Markdown). A plain-text body can't show bold, so a note with
  labelled list items needs an `htmlBody`.
- **Bold.** Beyond list labels, at most one or two phrases, such as a deadline or the decision,
  and only in an HTML body.
- **Tables.** Only for a real grid the reader will look things up in (scenarios by results,
  files by contents). Keep it to three columns or fewer, with a header row and no merged cells,
  in an HTML body. Plain text can't hold a table, and Outlook's Word-based renderer breaks complex
  ones. When each row needs a sentence of reasoning, use a numbered list instead.
- **Last pass.** Read it as someone on a phone would, and cut anything that doesn't serve the ask.

Sources: Nielsen Norman Group (how people scan; bulleted lists); GOV.UK style guide (lead-in
lines, front-loading, sparing bold); MIT Communication Lab (the ask first; numbered requests
the reader answers point by point); Rogers and Lasky-Fink ("use enough formatting but no more",
"make responding easy").

**Voice.** Follow the user's "Drafting in my voice" rules in the global CLAUDE.md; they win
wherever this summary differs:
- after the opening: the ask, then the specifics that support it;
- no pleasantries, stakes-selling, closing recap or volunteered next steps;
- answer at the altitude they asked, and don't correct their framing;
- plain words; avoid "not X, Y" and "X rather than Y";
- a full citation goes directly under the paragraph that cites it;
- one plain line on what Claude did ("Claude built the export and checked it against your v6.3
  block."). When the files carry Claude-written prose the user hasn't reviewed, say which parts
  and ask the recipient to scrutinize them;
- sign with the user's first name.

**Length follows the recipient.** In the user's own mail:
- colleagues get 40-110 words;
- technical users get 120-250, with a file or column list and one paragraph of caveats;
- co-authors, partners and funders get 250-450, with decisions split from minor items.

**What goes in:**
- what this is;
- one line per file on what it is and where it plugs in, or the entry point;
- what changed since last time, only if something did;
- the caveats that change how they use it;
- the check value;
- one consolidated ask (numbered questions for a reviewer, a now-or-later split if there are
  several).

**Show it before any draft exists.** Put the complete note in chat, verbatim, exactly as it would
go: channel, To, Cc, subject, attachments or links, and the full body, with the same blank lines
it will have in the email. Never a summary, and never only a path.

Show every readme the same way, verbatim as the recipient will see it: the readme sheet's rows,
the README.txt, a dictionary table's descriptions. For any other Claude-written prose the user
won't review, show the authorship line and where it sits. Then stop and wait for the user to read
it all. They may edit it, ask for changes, or say to create the draft (or to send it). The
go-ahead covers the note and the readmes together. If a readme changes afterwards, show it again.

Create the Gmail or Slack draft only after that go-ahead, and with exactly the text they
approved. If anything changes afterwards, whether their edits or a fix you make, show the new
version before the draft is created or updated.

**Gmail** (after the go-ahead):
1. Reply to the latest message in the thread. Copy To and Cc from the thread; never type an
   address from memory.
2. Reuse the latest message's subject verbatim. It already carries `Re:` and any gateway tag such
   as `[External Email]`.
3. Call `create_draft` with `replyToMessageId`, `to`, `cc`, `subject`, and a plain-text `body`:
   no Markdown, lists as `1.` or `-`, code as plain text, and one line per paragraph. Add
   `htmlBody` when the note needs a table or bold, which includes any list whose items open with a
   label. Keep it to simple HTML (`<p>`, `<ol>`,
   `<ul>`, a `<table>` with a header row) and keep the plain-text version as `body`. Tell the user
   to check the rendering in the draft.
4. Stop at the draft unless the user, having read the final text, explicitly says to send.
   Then send that exact draft:
   - check its sender, recipients and thread with `get_draft` in `METADATA_ONLY`;
   - send it with `send_message` and its `draftId`, so what goes out is what they approved.

   Never compose a fresh message to send, and never use `reply` or `forward`: both transmit
   text that was not drafted and read. If the user attaches a file by hand, the user sends.
5. Don't attach through the connector. Attachments travel base64-encoded through the tool call,
   so every megabyte costs its size in context. The user attaches the file by hand, and the
   `Attach:` line says which one.
6. Give the user the draft's `viewUrl`, so they can reread it where it will send from.

**Slack:** `slack_send_message_draft` in the right DM or channel, after the go-ahead. The user
sends it and uploads any file in Slack; never `slack_send_message` or scheduling.

**Box, Drive and shared folders:** uploading there publishes the files, so the user uploads, and
the note names the folder and the file. Listing the folder read-only to check for earlier drops
is fine.

### 6. Report

Give the user:
- what goes out (the file or zip, its path and size, and the channels it fits);
- the draft link, or the sent message's ID if they asked Claude to send;
- what's left for them: attach, reread, send.

Record the handoff where the project tracks such things, such as a memory entry: what went,
where it sits, the ask, and whether it has gone out. If the repo keeps superseded
drops in `archive/circulated/`, move the previous one there.

## Not this skill

- A kickoff prompt for a new Claude session: `handoff`.
- A web page or report to publish: the Artifact tool.
- Reviewing a drop someone sent the user: follow the repo's own conventions (for example,
  checksum the drop and write a `docs/handoff_review_*.md`).
- Sending without the user's explicit go-ahead on the final text.
