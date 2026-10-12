---
name: downloads-tidy
description: Reorganize and declutter ~/Downloads by reading the user's own filing rules (their CLAUDE.md files) and matching every file and folder against their real filing homes (the topic-based folders under ~/Documents, the repos under ~/Github, datasets under ~/Data, Zotero for academic papers) before moving or deleting anything, so Downloads ends up completely flat with zero subfolders. Use this whenever the user asks to clean up, tidy, organize, sort, or declutter their Downloads folder, says Downloads is a mess or out of control, wants to free up space there, or asks to file/sort through what's accumulated there — trigger even if they don't name this skill explicitly or don't use the word "skill". Also trigger for narrower asks like "what's in my Downloads that I can get rid of" or "help me find the duplicates in Downloads".
---

# Downloads Tidy

Downloads is a staging inbox, not a destination. Files land there once (a browser
download, a Slack/email attachment, an export) and from there either get used and
forgotten, or get filed somewhere permanent. Nothing should live in Downloads
long-term, and nothing that needs organizing should be organized *inside*
Downloads — if something is important enough to deserve a folder, that folder
belongs in a real home (a folder under `~/Documents`, a Github repo, `~/Data`,
or Zotero), not in `~/Downloads`.

**The end state of every run is a flat Downloads folder: zero subfolders.**
Anything left over when you're done is either a loose file that's genuinely
still-active work, or a loose file nobody could confidently place — never a
folder. Package directories (`.gdb`, `.zarr`, `.app` and the like) count as
single files. If you find yourself creating a new folder inside `~/Downloads`,
stop — that folder belongs somewhere else.

This matters because the failure mode this skill exists to prevent is subtle:
sorting files by *type* into folders like `Documents/`, `Images/`,
`Spreadsheets/`, `Archives/` *feels* like tidying, but it isn't — it just moves
the mess one level down and hides it behind a folder name. A screenshot and a
signed contract both being PNGs/PDFs tells you nothing about whether either one
matters. The only classification that actually helps is: **does this already
have a home, and if not, what project/topic is it obviously part of?**

Where things go, and what must never be touched, is the user's call, and they
have written it down in CLAUDE.md files beside the folders those rules govern.
This skill reads those files every run and routes by what they say. It never
carries a folder layout of its own, so it keeps working when the user
reorganizes.

## Step 0: ask which kind of pass this is

Always ask before scanning anything — don't guess from phrasing, and don't
default silently. Two genuinely different asks:

- **Quick tidy** — just the last week or two of clutter. Fast, low-stakes,
  good for "keep Downloads sane" maintenance. Ask for (or default to) a
  cutoff, e.g. "items from the last 14 days."
- **Deep clean** — the whole folder, including things that have been sitting
  there for months. Slower, involves real judgment calls on ambiguous/large
  items, and is worth doing every so often rather than every time.

Also ask (once, at the start — don't re-ask per file) about two conventions
that are very useful defaults but are specific to how *this* user works and
shouldn't be assumed silently for anyone else's Downloads folder:

1. Do saved email PDFs (anything that looks like an exported message —
   "<Org> Mail - ...", "Gmail - ...", or similar) get trashed on the
   assumption they're already in the mail system, or filed/kept?
2. Do academic paper PDFs (journal articles, arXiv/SSRN preprints, GTRs/
   research reports) go into Zotero via `zotero_add_from_file` rather than
   being filed as documents? (Only offer this if a Zotero MCP tool is
   available.)

If the user asks for a plan only (a dry run), do Steps 1–7, present the plan as
in Step 8, and stop there.

## Step 1: read the filing rules — live, every run

The rules files, not this skill, decide where things go. When the user
redesigns a folder layout they rewrite the rules files with it, so a run that
reads them fresh files correctly into the new layout. Never route from memory,
from an earlier run, or from the examples in this file.

Read each of these in full (they're short):

1. `~/.claude/CLAUDE.md`. Its "Where things live" section names the top-level
   homes (how repos are grouped under `~/Github`, what `~/Data` holds) and any
   dataset that must never leave this machine.
2. `~/Documents/CLAUDE.md`: the areas and what each holds, the handling rules
   (overwrites, versioning, records, coauthor files, naming), restricted
   areas, and the sharing and confidentiality rules.
3. Every per-area rules file, found live, skipping any area the root rules
   restrict (see the digest below):
   ```bash
   find ~/Documents -name CLAUDE.md -not -path '*/.venv/*' \
     -not -path '*/node_modules/*' -not -path '<restricted area>/*'
   ```
4. Any `README.md` or `CLAUDE.md` at the root of `~/Data`.
5. Later, when a repo becomes a candidate home, that repo's CLAUDE.md or
   README for where data and outputs go inside it.

Distill a working digest in your notes (not a file), each line citing the
rules file it came from:

- **Homes.** Each area and what it holds, in the rules' own words, plus any
  per-area routing: a table mapping topic folders to repos, a folder named for
  inputs filed from Downloads, where a funder's or client's records are kept.
- **Handling rules.** Overwrites and version naming, what counts as a record,
  how coauthor files are marked, folder naming, whether files may sit loose at
  an area's root.
- **Restricted areas.** Anything the rules say is opened only when the user
  names it. Listing counts as opening: file names alone can be personal (a
  medical bill, a salary letter), so don't `ls`, `find`, count or read inside
  it, not even to confirm it's empty. Its path goes to `--exclude` in Step 3.
  If you did look inside one, say so in the plan; never report an area as
  untouched when it wasn't.
- **Confidential scopes.** Every client, engagement, project or dataset a rules
  file marks confidential, under NDA, or never leaving this machine, with the
  file that governs it. Find them with
  `grep -il -E 'confidential|NDA|never leaves' <the rules files>` and locate
  each governing file by searching, never by a remembered path; these folders
  move.
- **Routes through other tools.** Anything the rules say reaches its home
  through an app or connector instead of hand-filing.

When a rules file and the live tree disagree (a named folder doesn't exist),
trust the tree for paths, don't route by the missing name, and list the drift
in the report.

## Step 2: discover the homes — live, every run

List the areas as they exist today, leaving out restricted areas:

```bash
find ~/Documents -mindepth 1 -maxdepth 1 -type d | sort
```

For each area that looks relevant to what's in Downloads (never a restricted
one), look one or two levels deeper to see the existing project folders and
naming (so filings reuse what's there rather than inventing a near-duplicate):

```bash
find ~/Documents/<area> -mindepth 1 -maxdepth 2 | sort
```

Do the same for code homes — find the repo roots (a directory with a `.git`
inside counts as a repo; repos are grouped by organization and function, so
search a few levels deep):

```bash
find ~/Github -maxdepth 4 -name .git -type d
```

And for datasets: `find ~/Data -mindepth 1 -maxdepth 2 | sort`.

For any repo that looks like a plausible match for something in Downloads,
check two things before assuming the repo *doesn't* already have the content:

- **`.gitignore`** — many repos deliberately keep raw/large data out of git
  history ("lives on disk only, not in git history" is a pattern actually
  seen in the wild here) while still storing it on disk under a `data/` or
  similar directory. A `.gitignore` entry doesn't mean the data isn't there —
  it means `git ls-files` won't show it, so check the filesystem directly.
- **`git log --oneline --since="60 days ago"`** — recent commits often
  describe exactly this kind of drop being received and filed ("Move the
  handoff drop into data/raw/", "Bump to v5.6", etc.), which tells you both
  whether the content already landed and whether it's since been superseded.

## Step 3: build the match index

Don't do the matching by hand file-by-file — use the bundled script, which
indexes every file under the home directories by name (and by name with a
trailing `" (1)"`/`" (2)"` re-download suffix stripped) and classifies every
Downloads item against it by exact byte size:

```bash
python3 -I "${CLAUDE_SKILL_DIR}/scripts/build_match_index.py" \
  --downloads ~/Downloads \
  --homes ~/Documents ~/Github ~/Data \
  --exclude <each restricted area from Step 1> \
  [--since-days 14]   # quick-tidy mode only \
  > <scratchpad>/downloads-tidy-match.json
```

Write the output to the session scratchpad directory, not `/tmp` or anywhere under
`~/Downloads`.

This produces three buckets — read the script's own docstring
(`--help` or just open the file) for the exact schema and caveats, but in
short:

- **`exact_dup`** — same name (or same name minus the " (1)" suffix) *and*
  same byte size found somewhere in the homes. These are candidates, not
  verdicts: name and size find likely copies cheaply but can't tell two files
  apart. An item goes on the trash list as a duplicate only after the
  byte-for-byte check in the Guardrails.
- **`size_mismatch`** — same name, different size. This is the "needs a
  closer look" bucket, not an error case: it usually means either the
  Downloads copy is a newer/older version of something filed, or two
  unrelated files just happen to share a name. Investigate before deciding
  anything (see Step 4).
- **`no_match`** — nothing by that name exists anywhere in the homes. This
  item has probably never been filed and needs a filing decision (Step 5),
  unless it was filed under another name: when an entry carries `same_size`
  (home files of exactly its size, listed for items of 64 KiB or more), check
  those byte for byte first. Exports get renamed on the way into a repo
  (`fig3_fuel.png` for `3d_fuel_structure_final.png`), and filing a second
  copy is as wrong as trashing an unfiled one.

Package directories (`.gdb`, `.zarr`, `.app`, `.SAFE`, …) are matched whole,
by directory name and total size: their internal files have generic names
that collide across unrelated datasets.

Generic filenames (`image.png`, `index.html`, `manifest.json`, and similar)
produce noisy matches because they recur everywhere — build artifacts, test
fixtures, node_modules. Don't trust a hit on a generic name at face value;
these usually belong in the "leave as a loose file, no confident home" bucket
regardless of what the script reports.

## Step 4: investigate size_mismatch before touching anything

Never assume "bigger/newer wins" or "smaller/older is stale" — check what's
actually different:

- **Text-ish files**: `diff` them directly.
- **A zip vs. an already-extracted sibling folder**: use the bundled
  ```bash
  python3 -I "${CLAUDE_SKILL_DIR}/scripts/check_zip_redundant.py" <zip> <folder>
  ```
  It compares every entry byte for byte against same-named files in the
  folder. It matches by basename because a naive comparison of zip-internal
  paths with folder-relative paths looks plausible but silently reports
  everything as missing (an actual bug hit while building this skill).
- **Something that looks like a repeated "handoff" or export drop**: check
  the likely destination repo's recent git log — the commit history often
  directly explains what happened to the previous version.
- **Two same-named files with genuinely different content** (not just
  size) — don't guess which is authoritative; ask the user, showing both
  candidates' sizes and dates.

## Step 5: route the no_match bucket by content and rules, not by type

For anything genuinely unfiled, the question is never "what kind of file is
this" — it's "what project, client, or topic is this obviously part of, and
which home do the rules say holds that." Look for:

- Project/client names embedded in filenames
- A cluster of related files that clearly belong together (a report + its
  figures + a data zip, meeting notes referencing the same initiative)
- Where it was downloaded from. Browsers record the URL and the referring page
  on the file itself:
  ```bash
  xattr -px com.apple.metadata:kMDItemWhereFroms "<file>" | xxd -r -p | plutil -p -
  ```
  (`mdls` reads the same field from the Spotlight index and returns `(null)`
  wherever Spotlight hasn't indexed the file.) A client's SharePoint, a
  journal site, an agency's site, a Box share or a Slack workspace often names
  the project or the source outright.
- The Step 1 digest: an area whose rules say it holds this kind of item, and
  per-area routing that sends a topic to a repo

Name the destination by role first (the area whose rules cover funder
solicitations, the repo that generated this output), then pick the existing
project folder inside it whose name matches. Reuse existing folders; never
invent a slightly different name for the same thing. If the rules say files
never sit loose at an area's root, an item that fits an area but no project
folder in it is a question for the user, not a guess.

Only create a new folder when nothing close already exists. New folders are
kebab-case everywhere, in `~/Documents`, `~/Data` and anywhere else, even when
older siblings aren't yet.

If academic-paper filing was confirmed in Step 0, send citable papers/reports
to Zotero instead of filing them as documents. The match index doesn't look
inside Zotero, so first check whether the paper is already in the library:
search by DOI, then title (`zotero_search_items`, or `zotero_find_duplicates`
for a batch). If it's already there, the Downloads copy is redundant and goes
in the trash list. Only if it isn't, add it with `zotero_add_from_file` — after
a successful add (it returns an item key), the source PDF becomes redundant and
can be trashed.

If nothing gives a confident signal — a bare screenshot, an unlabeled
`image.png`, a spreadsheet with no distinguishing content — don't force a
guess into the user's curated Documents tree. Leave it as a loose file
directly in `~/Downloads`. That's a legitimate end state; a wrong guess filed
into an otherwise-clean project folder is worse than an unsorted file sitting
in the inbox where it's still easy to find and reconsider.

## Guardrails: check every planned move

These come from the user's rules and override any routing above. Where a rules
file states a guard differently from this list, the rules file wins; this list
says what to look for.

- **Duplicates are proven, never inferred.** Anything trashed as a duplicate,
  whether of a filed copy, a sibling re-download or a zip's extracted folder,
  needs a byte-for-byte match (`cmp -s <a> <b>`, matching
  `shasum -a 256`, or the zip check in Step 4) with an original that exists
  and stays. Name, size and dates only nominate candidates. Cite the
  comparison in the plan entry.
- **Never overwrite.** Before any move, check whether the destination path
  exists. If it does, compare with `shasum -a 256`. Identical means the
  Downloads copy is a duplicate and goes on the trash list. Different means a
  deliverable (.docx, .pptx, .pdf, .xlsx) is saved beside the existing file
  under the next name in that folder's version series (`_v4` after `_v3`,
  otherwise `_YYYYMMDD`), and anything else is a question for the user.
  Don't rearrange what's already filed (archiving superseded drafts,
  renaming); list it as a follow-up when the rules call for it.
- **Records move as-is.** The rules define what counts as a record (signed
  contracts, anything submitted or named FINAL, solicitations, editor and
  reviewer letters, and so on). File records byte-for-byte under their
  existing names: no kebab-casing, no tidying. A re-download copy (" (1)") of
  a record goes to trash only when `shasum` shows it identical to a copy that
  is filed or being filed. A record with no filed copy is never trashed.
- **Gemini meeting-note exports** ("Notes by Gemini" PDFs) are the one
  exception: they go on the trash list. Google Drive keeps the originals
  automatically, and the rules send meeting notes onward through their own
  tool, never by hand-filing. Don't file them and don't drive that tool.
- **Coauthor files stay distinct.** Author initials before the extension
  (`_SK`, `_kb`, `_PVC`, any case, possibly followed by a version) mark whose
  draft a file is. Files that differ only in initials are different authors'
  versions: never duplicates, never merged, renamed or overwritten. File them
  side by side. Confirm the suffix really is initials (a coauthor of that
  project, sibling files with other initials); `_pr` or `_us` may be a place
  code.
- **Restricted areas need per-item confirmation.** Items that look like they
  belong in a restricted area (personal, HR, tax, health, payroll, travel
  reimbursement) go in their own plan group with that area as the proposed
  home. File each one only after the user confirms that item by name; a batch
  "go" doesn't cover them. Don't open the area to look for duplicates or
  existing subfolders; propose the area itself and let the user name the
  folder.
- **Confidential scopes.** Before planning any item that matches a
  confidential scope (client or engagement name, site names, the source URL's
  host), read its governing rules file in full and follow its handling. If
  those rules forbid local copies of client-supplied data, flag the item for
  the user instead of filing it. Confidential material never goes into a git
  working tree (it can be pushed), a Box, Drive or other cloud folder, or a
  published page.
- **Local-only datasets.** Anything derived from a dataset the rules say never
  leaves this machine stays local: never into a repo working tree or a synced
  folder. Propose that dataset's existing local home and ask.
- **Datasets with no repo home.** If the rules files say where a new dataset
  goes (and what record of its source to add), follow them. Otherwise put it
  in the "needs a home" group with its size, source URL and the nearest
  candidate repos, and leave it in Downloads. Don't invent a provenance or
  README convention.
- **Outputs from code** (figures, run bundles, handoff packages) belong in the
  generating repo, or in a project folder with a README naming the generating
  script and commit. Write that README entry only from what you verified in
  the repo's `git log`. If you can't identify the script and commit, file into
  the repo or ask.
- **Partner logos.** The rules name a per-organization logo folder with a
  sources file. Check it before filing. A new logo goes in with its source URL
  (the download's recorded URL, Step 5) and usage terms added to the sources file. Ask
  for terms you can't find; don't invent them.
- **Credentials** (`client_secret*.json`, `*.pem`, `.env`, key files) are
  never filed into a repo or Documents. Flag them in the plan and propose
  trashing once the user confirms the secret is stored where it belongs.

## Step 6: handle common junk without asking

These patterns are unambiguous busywork, not judgment calls — put them on the
trash list without a separate question:

- `.DS_Store` files
- Microsoft Office lock files (`~$*.docx`, `~$*.xlsx`, `~$*.pptx`) — these are
  transient markers left behind by a file being open in Word/Excel/PowerPoint,
  not real content
- Empty/placeholder pages (e.g. an `index.html` whose only content is an
  "Under Construction" stub) — peek at the content before assuming, but these
  are safe to discard once confirmed
- A zip that the Step 4 zip check proves redundant against an
  already-extracted sibling folder, once the folder itself has a home
- Gemini meeting-note exports (see Guardrails)

## Step 7: surface ambiguous/big items efficiently

Don't do one giant upfront interrogation, and don't guess silently either.
Batch related questions together (one round covering several ambiguous items
beats five separate rounds), and always show the evidence that makes
something ambiguous rather than asking blind — sizes, dates, zip contents,
git log excerpts, source URLs. The user should be able to answer from the
evidence you show them, not have to go dig it up themselves. Reasonable
triggers for "ask rather than guess":

- Anything over roughly 500MB
- Same basename, different sizes, with no clear "which one is current"
  signal from git log or file dates
- Raw data with no repo home (see Guardrails)
- Anything a guardrail sends to the user: a collision that isn't a
  deliverable, a restricted-area item, a confidential item, a logo with
  unknown terms, an output whose generating commit you can't find
- Anything where the investigation in Step 4 turned up genuinely conflicting
  evidence

## Step 8: present the plan, then execute in reviewable batches

- Present the plan in groups:
  - **Trash**, each item with its reason and proof (duplicate of `<path>`,
    byte-identical by `cmp`; junk; Gemini export; zip proven redundant)
  - **File**, `source → destination`, with "(new)" on any destination folder
    that doesn't exist yet, each with the rule that sent it there:
    the rules file and what it says. Where no rule covers a filing and it
    rests on evidence alone (a project name, a repo's README), write "no
    rule" and give the evidence, so the user can see which filings are
    judgment calls.
  - **Zotero adds**
  - **Confirm each**: restricted-area items, one line each
  - **Flagged**: confidential items, credentials, datasets that need a home
  - **Open questions**: everything waiting on an answer, each with its
    evidence
  - **Leave loose**

  Give counts per group and every entry in the confirm, flagged and question
  groups. Close with the exact commands a "go" would run (`trash -v …`,
  `mkdir -p …`, `mv -n …`), so the user approves what will actually execute.
  It doesn't need a fancy UI, just a chance to eyeball counts and entries.
  A plan-only run ends here.
- **Wait for an explicit "go"** before moving, trashing or adding anything.
  Approval of one batch doesn't cover the next.
- **Re-check right before executing.** The user may reorganize between the
  plan and the "go". Confirm each destination folder still exists and each
  source is unchanged; re-plan any item whose destination moved instead of
  recreating the old path.
- **Trash, never permanently delete**: `trash -v <explicit paths>` (macOS
  `/usr/bin/trash`, reversible with Finder's Put Back). Never `rm`.
- **File with explicit paths**, not wildcards that could wander somewhere
  unintended. Use `mv -n`, then confirm the source is gone and the
  destination exists: `mv -n` skips silently on a collision.
- If filing something into a git repo's working tree (e.g. a data drop into
  a repo's `data/raw/`), just place the file — don't `git add` or commit on
  the user's behalf; leave that decision to them.
- Never blind-delete a folder that mixes disposable and keep-worthy content —
  if a folder's contents are heterogeneous, handle its contents individually
  rather than making one call for the whole thing.

## Step 9: final sweep — eliminate remaining folders

After filing and trashing, list what's left in Downloads
(`find ~/Downloads -mindepth 1 -maxdepth 1`). Any directory still there that
isn't a package needs one more pass: file or trash its contents using the same
logic as above, then remove the now-empty folder. If a folder contains a few
items with real homes and a few with no confident home, split it — file what
you can, and un-fold the rest into loose files directly in `~/Downloads`
rather than leaving the folder behind for just the leftovers.

## Step 10: report back concisely

Summarize, don't enumerate every file:

- Space freed (before/after `du -sh ~/Downloads`, and that everything trashed
  is recoverable from the Trash)
- Roughly how many items were trashed vs. filed vs. left loose
- Where the significant clusters went (by project/topic, not a file-by-file
  list)
- Anything flagged but not acted on (a credential file sitting loose, an
  ambiguous item the user should double check, a dataset waiting for a home)
- Drift between the rules files and the live tree, and follow-ups the rules
  call for (superseded drafts to archive, a sources-file entry to complete)

## A note on scale

A genuine first deep-clean of a Downloads folder that's accumulated for a
long time can easily involve hundreds of files and take real back-and-forth —
that's normal, not a sign something's going wrong. Subsequent runs (especially
quick tidies) should be much faster since most of the "does this already have
a home" groundwork doesn't need to be redone from scratch each time — the
match index in Step 3 handles that regardless of how much has accumulated.
