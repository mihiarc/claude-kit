# Input schema

`render.py` reads one JSON object. Every field below is checked by `render.py --check`, which names each bad field by its path (`rows[2].cells.readme.status`) and suggests the field you probably meant when a name is misspelled. Unknown fields are errors.

`assets/example.json` uses every field, so copy it as a starting point.

**Ids** (`id`, `link`, `kind`) are letters, digits, `-` and `_`, starting with a letter or digit. They become page anchors.

**Text fields** are plain text with two pieces of inline markup: `` `code` `` and `[label](target)`. A link target is `http(s)://`, `mailto:`, a `#anchor` on the page, or a relative path. Nothing else is interpreted, and HTML is escaped.

**Statuses** are always one of `good`, `watch`, `problem`, `out`, `pending`.

## Page

| Field | Type | Required | What it is |
|---|---|---|---|
| `title` | text | yes | The page title, also the browser tab title. |
| `lede` | text | | One or two sentences under the title: what was checked, against what, and the headline story. |
| `tiles` | list of [tiles](#tile) | | Headline numbers in a row under the lede. |
| `statuses` | [statuses](#statuses) | yes | This page's labels for the five statuses. |
| `headings` | [headings](#headings) | | This page's titles and ledes for the four sections. |
| `grid` | [grid](#grid) | yes | The grid's columns and wording. |
| `kinds` | list of [kinds](#kind) | | Finding kinds for the findings-by-kind bars. Without it the page skips that section. |
| `rows` | list of [rows](#row) | yes | The items under review, in display order. At least one. |
| `top` | list of [top findings](#top-finding) | | At most five, most important first. Without it the page skips that section, and `--check` warns. |
| `footer` | text | | A last line: how and when the page was built, and anything a reader should know about its sources. |

## Tile

| Field | Type | Required | What it is |
|---|---|---|---|
| `value` | number or text | yes | The figure, shown large. |
| `label` | text | yes | What it counts. |

## Statuses

All five keys are required. The colors, icons and order are fixed; the page names them.

| Key | Icon | Fill | Example labels |
|---|---|---|---|
| `good` | ✓ | green | current · plausible · done |
| `watch` | ! | amber | unverifiable · questionable · in progress |
| `problem` | ✕ | red | stale · implausible · blocked |
| `out` | – | gray | flag only · not applicable · n/a |
| `pending` | ○ | dashed outline, no fill | not yet read · not yet checked · not started |

Each value is an object:

| Field | Type | Required | What it is |
|---|---|---|---|
| `label` | text | yes | The word on every chip and cell tooltip, such as `stale`. Keep it to one or two words. |
| `means` | text | | What the label means on this page, shown beside it in the legend. |

## Headings

Each key is optional, and each value is `{"title": text, "lede": text}` with both fields optional.

| Key | Default title |
|---|---|
| `grid` | Inventory |
| `kinds` | Findings by kind |
| `top` | The top findings |
| `details` | Detail |

## Grid

| Field | Type | Required | What it is |
|---|---|---|---|
| `columns` | list of [columns](#column) | yes | The checks, in display order. At least one. |
| `row_header` | text | | The label over the row names, such as `Repo` or `Module`. |
| `cell_note` | text | | One sentence under the legend saying what a cell's number or state means. |
| `empty` | text | | What a cell with nothing in it shows. Default `none`. |

## Column

| Field | Type | Required | What it is |
|---|---|---|---|
| `id` | id | yes | Unique among columns; rows key their cells by it. |
| `label` | text | yes | The column heading. |
| `note` | text | | A small second line under the heading. |

## Kind

At most eight kinds take a color, in the dataviz skill's categorical order. Fold the rest into one kind marked `other`, which goes last and is drawn in gray.

| Field | Type | Required | What it is |
|---|---|---|---|
| `id` | id | yes | Unique among kinds; rows count their findings by it. |
| `label` | text | yes | The legend label, such as `Wrong number`. |
| `other` | true/false | | Draw this kind in gray as the catch-all. |

## Row

| Field | Type | Required | What it is |
|---|---|---|---|
| `id` | id | yes | Unique among rows. The row's detail section is at `#row-<id>`. |
| `label` | text | yes | The row name in the grid, the bars and the detail heading. |
| `note` | text | | A small second line under the name. |
| `cells` | object | | Column id → a [cell](#cell), or a list of cells for a column that holds several items (one chip per guide, per figure, per file). A missing column, or an empty list, shows the grid's `empty` text. |
| `findings` | object | | Kind id → how many findings of that kind this row has. Drives the row's bar. |
| `detail` | [detail](#detail) | | The row's detail section. Every row gets a section; this fills it. |

## Cell

A cell shows its status icon plus either a `count` or a short `state`, never both. With neither, it shows the icon alone.

| Field | Type | Required | What it is |
|---|---|---|---|
| `status` | status | yes | The cell's status, usually the worst finding in it. |
| `count` | whole number | | A number to show, such as the findings at that status. Say what it counts in `grid.cell_note`. |
| `state` | text | | A short state, such as `done`, `by Mon 11/9` or `awaiting review`. Under 32 characters; `--check` warns past that. |
| `label` | text | | The item's name, shown before the value. Use it in multi-item cells. |
| `tip` | text | | One sentence for the hover tooltip, after the row, column, status and value. |
| `link` | id | | A block id in this row's detail. A click jumps there; without it, a click jumps to the row's detail section. |

## Detail

| Field | Type | Required | What it is |
|---|---|---|---|
| `status` | status | | The chip on the section heading. Without it, the worst status among the row's cells, in the order problem, watch, pending, good, out. |
| `summary` | text | | A sentence or two on the row as a whole. |
| `blocks` | list of [blocks](#block) | | The figures and findings, in display order. |

## Block

A block is one figure, claim table or finding. Give it at least one of `story`, `image` or `table`.

| Field | Type | Required | What it is |
|---|---|---|---|
| `id` | id | | Unique within the row. Needed when a cell links to it; its anchor is `#row-<row id>.<id>`. |
| `title` | text | yes | The block heading. |
| `status` | status | | The block's chip. |
| `image` | [image](#image) | | A figure, shown full width on a light surface in both modes. |
| `story` | text | | Two or three plain sentences: what the figure or finding shows and why it has this status. |
| `table` | [table](#table) | | Claims, values or links, one per row. |

## Table

| Field | Type | Required | What it is |
|---|---|---|---|
| `columns` | list of text | yes | Column headings. |
| `rows` | list of lists | yes | Each row has one entry per column: text, a number, or `{"status": status, "text": text}` for a status chip (`text` overrides the page label). |

## Top finding

| Field | Type | Required | What it is |
|---|---|---|---|
| `title` | text | yes | The finding in a few plain words. |
| `status` | status | yes | Its chip. |
| `kind` | id | | One of the page's kinds; shown with its swatch. |
| `rows` | list of row ids | | The rows it touches; each links to its detail section. |
| `says` | text | yes | What it says, in plain words. |
| `evidence` | text | | What shows it. `--check` warns when a finding has neither evidence nor an image. |
| `image` | [image](#image) | | A thumbnail of the evidence; a click enlarges it. |
| `fix` | text | yes | The fix, written as the current state it should become. |
| `where` | text | yes | Where the fix goes: a PR, a flag to an owner, a later release. |

## Image

| Field | Type | Required | What it is |
|---|---|---|---|
| `src` | text | yes | A path relative to the input file's folder, or a `data:image/...;base64,` URI. URLs and absolute paths are errors: the page makes no external calls. |
| `alt` | text | yes | What the image shows, for screen readers and broken images. |
| `caption` | text | | A line under the image. |
| `embed` | true/false | | Read the file at render time and embed it in the page, so the page works on its own. Without it, the page links the file by a path relative to where the page is written, and `--check` warns if the file is missing. |

Embedding takes `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg` and `.webp` files. Embed when the page will be moved or sent on its own; link when figures are large or reused beside the page.
