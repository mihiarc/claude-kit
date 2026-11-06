---
name: visual-inventory
description: >-
  Build a report page a person reads visually first: an items × checks grid on a fixed
  five-status scale (good, watch, problem, out of scope, pending, each with a fixed color and
  icon), then findings-by-kind bars, the top five findings, and a detail section per item. A
  bundled script renders it from one JSON file into one self-contained HTML page that works
  in light and dark mode and at phone width. Use it for any page someone reads to see status
  across many items: a docs audit, visual or data QA, a roadmap or delivery tracker, a code,
  dependency or security review, a migration checklist, an evaluation across models or
  datasets. Trigger on "make a report page", "inventory of", "status grid", "QA report", "docs
  audit page", "roadmap page", "show me where everything stands", or when the user's
  CLAUDE.md asks for report pages in this format. Not for a chart of continuous data (use
  dataviz), a slide deck, or a document people will keep editing as text.
metadata:
  author: mihiarc
  version: "1.0"
---

# visual-inventory

Some readers take in results visually first. For them, a report page earns its place in the
first screen: a grid that shows every item against every check, colored by status, before
any prose. When every report uses the same grid and the same five statuses, a reader learns
the format once and reads each new page at a glance. This skill fixes that format and
renders it, so each page differs only in what it reviews.

## The page

The page always reads in this order:

1. **Header.** The title, a lede (what was checked, against what, and the headline story),
   and optional tiles with headline numbers.
2. **Inventory grid.** A legend with the page's five labels sits above it. Rows are the
   items under review; columns are what gets checked. Each cell is filled by its status,
   carries the status icon, and shows a count (how many findings) or a short state (`done`,
   `by Mon 11/9`). Hovering shows the row, column, status and a sentence; clicking jumps to
   the row's detail section, or to one block in it. A column can hold several items per row,
   one chip each (one per guide, per figure, per file).
3. **Findings by kind.** One bar per row, split by kind of finding, all on one scale, with a
   table view underneath.
4. **The top findings.** At most five, most important first, each in the same layout: what
   it says, the evidence (with an optional thumbnail that enlarges on click), the fix, and
   where the fix goes.
5. **Detail.** One section per row with a status chip, and blocks inside it: a figure, two or
   three sentences telling its story, a table of claims or values, each with its own chip.

## What's fixed and what each page supplies

**Fixed on every page:** the five statuses, their order, colors and icons.

| Status | Icon | Light | Dark |
|---|---|---|---|
| `good` | ✓ | `#0ca30c`, white ink | same |
| `watch` | ! | `#fab219`, ink `#0b0b0b` | same |
| `problem` | ✕ | `#d03b3b`, white ink | same |
| `out` (out of scope) | – | `#e1e0d9`, ink `#52514e` | `#383835`, ink `#c3c2b7` |
| `pending` | ○ | no fill, 1.5px dashed `#898781` outline | same |

These come from the dataviz skill's fixed status palette (its `references/palette.md`,
"Status palette" and "Chart chrome & ink"): good, warning and critical for the three colored
statuses, which clear 3:1 on the dark surface and so keep their values; the gridline fill
and secondary ink for out of scope; muted ink for pending's outline. The renderer carries
them, so a page never restyles them. Every cell and chip shows its icon, so color is never
the only signal. Status colors mean status only: finding kinds take the dataviz
categorical slots in their fixed order, and figures you draw for a page should not reuse
the status colors for a series.

**Supplied by each page:** its labels for the five statuses, its rows and columns, its kinds
of finding, its section titles, and what a cell's number means. Label sets from different
kinds of report:

| Status | Docs audit | Data or visual QA | Roadmap |
|---|---|---|---|
| `good` | current | plausible | done |
| `watch` | unverifiable | questionable | in progress |
| `problem` | stale | implausible | blocked |
| `out` | flag only | not applicable | n/a |
| `pending` | not yet read | not yet checked | not started |

## Building a page

1. **Read the user's CLAUDE.md** for where report pages live, who opens them, and what may
   not appear in them (confidential data, client names). Without a rule there, keep the JSON
   and the page together in a folder named for the subject: `<subject>/inventory.json` and
   `<subject>/index.html`.

2. **Design the grid before gathering.** Pick the rows (the things under review), the columns
   (the checks), the five labels in the reader's words, and the kinds of finding. The grid
   is the review's plan: every cell starts `pending`, and the page shows honestly what has
   and hasn't been checked. Kinds name what is wrong, such as wrong number, wrong name,
   missing or broken link, so that fixes of one kind batch together. At most eight take a
   color; fold the rest into one kind marked `other`.

3. **Write the JSON.** Start from `assets/example.json`, a docs audit of a fictional library
   that uses every field. `references/input-schema.md` documents each field. Rules of thumb:
   - A cell's status is its worst finding, and its count is the findings at that status.
     If the count means something else, say so in `grid.cell_note`. Never average statuses.
   - A state is a few words (under 32 characters). The rest goes in `tip`.
   - Choose the top five by consequence for the reader, not by count. Write each in plain
     words, and write the fix as the state it should become.
   - Give each figure two or three sentences: what it shows, and why it earned its status.
   - Images are relative paths or embedded. Set `embed: true` when the page will be moved
     or sent on its own. Load the dataviz skill before drawing a figure for a page.

4. **Check, then render.**

   ```sh
   python3 "${CLAUDE_SKILL_DIR}/scripts/render.py" inventory.json --check
   python3 "${CLAUDE_SKILL_DIR}/scripts/render.py" inventory.json            # writes index.html beside it
   python3 "${CLAUDE_SKILL_DIR}/scripts/render.py" inventory.json -o page.html --open
   ```

   `--check` names every bad field by its path and writes nothing. Rendering checks first,
   too, and refuses to write a page from bad input. The script needs only the Python
   standard library, and the page it writes makes no external calls.

5. **Look at it before handing it over.** Open the page and check that the grid tells the
   headline story on its own, that labels fit their cells, and that it reads in both light
   and dark mode and in a narrow window. Fix the JSON and re-render; never hand-edit the
   HTML, since the next run overwrites it.

6. **Open it for the user,** with `--open` or the system's opener (`open` on macOS,
   `xdg-open` on Linux), and give the page's full path. If the user's CLAUDE.md says another
   session or a coordinator opens report pages, send the path there instead. The page is a
   local file: publish or send it only when the user asks.

When the review moves on, update the same JSON and re-render, so the page stays one current
picture and its history lives in version control or the files beside it.

## Files

- `scripts/render.py`: validates the JSON and renders the page. Usage is in its docstring.
- `references/input-schema.md`: every input field, its type and what it does.
- `assets/example.json` and `assets/example.html`: the worked example and the page rendered
  from it, with its figures in `assets/figures/`.
