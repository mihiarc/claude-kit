#!/usr/bin/env python3
"""Render a visual-inventory page: one JSON file in, one self-contained HTML page out.

    python3 render.py inventory.json                 # writes index.html beside the input
    python3 render.py inventory.json -o report.html  # or wherever -o says
    python3 render.py inventory.json --check         # validate only; names every bad field
    python3 render.py inventory.json --open          # render, then open it in the browser

The page reads top to bottom: a legend and an items x checks grid on the fixed
five-status scale, findings by kind, the top five findings, then one detail
section per row. The input format is in ../references/input-schema.md.

Standard library only. The page makes no external calls: its styles and tooltip
script are inline, and each image is either embedded or a relative path.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import html
import json
import os
import re
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote

# The five statuses in their fixed order, with their icons. The colors are the
# dataviz skill's status palette (references/palette.md): its good, warning and
# critical steps for good, watch and problem; its chart chrome for out of scope
# (gridline fill, secondary ink) and pending (a muted-ink dashed outline).
STATUSES = ("good", "watch", "problem", "out", "pending")
ICONS = {"good": "✓", "watch": "!", "problem": "✕", "out": "–", "pending": "○"}
# The status a row's detail section shows when the input doesn't set one:
# the first of these found among the row's cells.
SEVERITY = ("problem", "watch", "pending", "good", "out")

# Finding kinds take the dataviz categorical slots in their fixed order, as
# (light, dark). A kind marked "other" is drawn in muted gray instead.
KIND_SLOTS = (
    ("#2a78d6", "#3987e5"),
    ("#eb6834", "#d95926"),
    ("#1baf7a", "#199e70"),
    ("#eda100", "#c98500"),
    ("#e87ba4", "#d55181"),
    ("#008300", "#008300"),
    ("#6250d6", "#9085e9"),
    ("#e34948", "#e66767"),
)
OTHER_KIND = "#898781"
MAX_TOP = 5
STATE_MAX = 32

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
DATA_URI = re.compile(r"^data:image/(png|jpeg|gif|svg\+xml|webp);base64,[A-Za-z0-9+/=\s]+$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

# Field specs: name -> (type, required).
PAGE = {
    "title": ("str", True),
    "lede": ("str", False),
    "tiles": ("list", False),
    "statuses": ("obj", True),
    "grid": ("obj", True),
    "kinds": ("list", False),
    "rows": ("list", True),
    "top": ("list", False),
    "headings": ("obj", False),
    "footer": ("str", False),
}
STATUS_LABEL = {"label": ("str", True), "means": ("str", False)}
TILE = {"value": ("str|num", True), "label": ("str", True)}
HEADINGS = {"grid": ("obj", False), "kinds": ("obj", False), "top": ("obj", False), "details": ("obj", False)}
HEADING = {"title": ("str", False), "lede": ("str", False)}
GRID = {
    "row_header": ("str", False),
    "columns": ("list", True),
    "cell_note": ("str", False),
    "empty": ("str", False),
}
COLUMN = {"id": ("id", True), "label": ("str", True), "note": ("str", False)}
KIND = {"id": ("id", True), "label": ("str", True), "other": ("bool", False)}
ROW = {
    "id": ("id", True),
    "label": ("str", True),
    "note": ("str", False),
    "cells": ("obj", False),
    "findings": ("obj", False),
    "detail": ("obj", False),
}
CELL = {
    "status": ("status", True),
    "count": ("int", False),
    "state": ("str", False),
    "label": ("str", False),
    "tip": ("str", False),
    "link": ("id", False),
}
DETAIL = {"status": ("status", False), "summary": ("str", False), "blocks": ("list", False)}
BLOCK = {
    "id": ("id", False),
    "title": ("str", True),
    "status": ("status", False),
    "story": ("str", False),
    "image": ("obj", False),
    "table": ("obj", False),
}
IMAGE = {"src": ("str", True), "alt": ("str", True), "caption": ("str", False), "embed": ("bool", False)}
TABLE = {"columns": ("list", True), "rows": ("list", True)}
TABLE_STATUS = {"status": ("status", True), "text": ("str", False)}
TOP = {
    "title": ("str", True),
    "status": ("status", True),
    "kind": ("id", False),
    "rows": ("list", False),
    "says": ("str", True),
    "evidence": ("str", False),
    "image": ("obj", False),
    "fix": ("str", True),
    "where": ("str", True),
}


# ---------------------------------------------------------------- validation


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "a list"
    return "an object"


def _at(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key


class Checker:
    """Collects every problem in the input, each named by its field path."""

    def __init__(self, in_dir: Path):
        self.in_dir = in_dir
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, path: str, msg: str) -> None:
        self.errors.append(f"{path or '(top level)'}: {msg}")

    def warn(self, path: str, msg: str) -> None:
        self.warnings.append(f"{path or '(top level)'}: {msg}")

    def fields(self, value: object, path: str, spec: dict) -> dict:
        """Check an object's keys and value types; return it, or {} if it isn't one."""
        if not isinstance(value, dict):
            self.error(path, f"must be an object, got {_type_name(value)}")
            return {}
        for key in value:
            if key not in spec:
                near = difflib.get_close_matches(key, list(spec), n=1)
                hint = f'did you mean "{near[0]}"?' if near else "allowed: " + ", ".join(spec)
                self.error(_at(path, key), f"unknown field; {hint}")
        ok = {}
        for key, (kind, required) in spec.items():
            if key not in value:
                if required:
                    self.error(_at(path, key), "missing; this field is required")
                continue
            if self.value(value[key], _at(path, key), kind):
                ok[key] = value[key]
        return ok

    def value(self, v: object, path: str, kind: str) -> bool:
        good = {
            "str": isinstance(v, str) and v.strip() != "",
            "str|num": (isinstance(v, str) and v.strip() != "")
            or (isinstance(v, (int, float)) and not isinstance(v, bool)),
            "int": isinstance(v, int) and not isinstance(v, bool) and v >= 0,
            "bool": isinstance(v, bool),
            "list": isinstance(v, list),
            "obj": isinstance(v, dict),
            "status": v in STATUSES,
            "id": isinstance(v, str) and bool(ID.match(v)),
        }[kind]
        if good:
            return True
        want = {
            "str": "a non-empty string",
            "str|num": "a number or a non-empty string",
            "int": "a whole number, 0 or more",
            "bool": "true or false",
            "list": "a list",
            "obj": "an object",
            "status": "one of " + ", ".join(STATUSES),
            "id": "an id of letters, digits, - and _ (starting with a letter or digit)",
        }[kind]
        shown = json.dumps(v, ensure_ascii=False) if isinstance(v, (str, int, float)) else _type_name(v)
        self.error(path, f"{shown} is not valid; use {want}")
        return False

    def unique(self, ids: list[tuple[str, str]], what: str) -> None:
        seen: dict[str, str] = {}
        for path, i in ids:
            if i in seen:
                self.error(path, f'{what} id "{i}" is already used at {seen[i]}')
            else:
                seen[i] = path

    def image(self, img: object, path: str) -> None:
        img = self.fields(img, path, IMAGE)
        src = img.get("src")
        if src is None:
            return
        at = _at(path, "src")
        if src.startswith("data:"):
            if not DATA_URI.match(src):
                self.error(at, "a data: URI must be a base64 png, jpeg, gif, svg+xml or webp image")
            return
        if SCHEME.match(src) or src.startswith("//"):
            self.error(at, "must be a path relative to the input file, or a data: URI; the page makes no external calls")
            return
        if os.path.isabs(src):
            self.error(at, "must be relative to the input file's folder, not absolute")
            return
        file = self.in_dir / src
        embed = img.get("embed", False)
        if embed and file.suffix.lower() not in IMAGE_TYPES:
            self.error(at, "can embed only " + ", ".join(sorted(IMAGE_TYPES)) + " files")
        elif not file.is_file():
            msg = f"no file at {file}"
            if embed:
                self.error(at, msg)
            else:
                self.warn(at, msg + "; the page will show a broken image until it exists")


def validate(data: object, in_dir: Path) -> Checker:
    c = Checker(in_dir)
    page = c.fields(data, "", PAGE)

    if "statuses" in page:
        statuses = c.fields(page["statuses"], "statuses", {s: ("obj", True) for s in STATUSES})
        for s, v in statuses.items():
            c.fields(v, _at("statuses", s), STATUS_LABEL)

    for i, t in enumerate(page.get("tiles", [])):
        c.fields(t, _at("tiles", i), TILE)

    headings = c.fields(page.get("headings", {}), "headings", HEADINGS)
    for k, v in headings.items():
        c.fields(v, _at("headings", k), HEADING)

    grid = c.fields(page["grid"], "grid", GRID) if "grid" in page else {}
    columns = grid.get("columns", [])
    if "columns" in grid and not columns:
        c.error("grid.columns", "needs at least one column")
    col_ids = []
    for i, col in enumerate(columns):
        col = c.fields(col, _at("grid.columns", i), COLUMN)
        if "id" in col:
            col_ids.append((_at(_at("grid.columns", i), "id"), col["id"]))
    c.unique(col_ids, "column")
    col_set = list(dict.fromkeys(i for _, i in col_ids))

    kinds = page.get("kinds", [])
    kind_ids = []
    others = []
    for i, k in enumerate(kinds):
        k = c.fields(k, _at("kinds", i), KIND)
        if "id" in k:
            kind_ids.append((_at(_at("kinds", i), "id"), k["id"]))
        if k.get("other"):
            others.append(i)
    c.unique(kind_ids, "kind")
    kind_set = list(dict.fromkeys(i for _, i in kind_ids))
    if len(kinds) - len(others) > len(KIND_SLOTS):
        c.error("kinds", f"at most {len(KIND_SLOTS)} kinds take a color; fold the rest into one kind marked \"other\": true")
    if len(others) > 1:
        c.error("kinds", "only one kind can be marked \"other\"")
    elif others and others[0] != len(kinds) - 1:
        c.error(_at("kinds", others[0]), "the \"other\" kind goes last")

    rows = page.get("rows", [])
    if "rows" in page and not rows:
        c.error("rows", "needs at least one row")
    row_ids = []
    for r, row in enumerate(rows):
        rp = _at("rows", r)
        row = c.fields(row, rp, ROW)
        if "id" in row:
            row_ids.append((_at(rp, "id"), row["id"]))

        block_ids = []
        detail = c.fields(row.get("detail", {}), _at(rp, "detail"), DETAIL)
        for b, block in enumerate(detail.get("blocks", [])):
            bp = _at(_at(rp, "detail.blocks"), b)
            block = c.fields(block, bp, BLOCK)
            if "id" in block:
                block_ids.append((_at(bp, "id"), block["id"]))
            if "image" in block:
                c.image(block["image"], _at(bp, "image"))
            if "table" in block:
                _check_table(c, block["table"], _at(bp, "table"))
            if not any(k in block for k in ("story", "image", "table")):
                c.warn(bp, "has no story, image or table")
        c.unique(block_ids, "block")
        block_set = [i for _, i in block_ids]

        for col_id, cell in row.get("cells", {}).items():
            cp = _at(_at(rp, "cells"), col_id)
            if col_id not in col_set:
                c.error(cp, "no column has this id; columns are " + ", ".join(col_set))
            items = cell if isinstance(cell, list) else [cell]
            for n, item in enumerate(items):
                ip = _at(cp, n) if isinstance(cell, list) else cp
                item = c.fields(item, ip, CELL)
                if "count" in item and "state" in item:
                    c.error(ip, "set count or state, not both")
                if len(item.get("state", "")) > STATE_MAX:
                    c.warn(_at(ip, "state"), f"keep a state to a few words (under {STATE_MAX} characters); put the rest in tip")
                if "link" in item and item["link"] not in block_set:
                    c.error(_at(ip, "link"), f'no block in this row\'s detail has id "{item["link"]}"')

        for kind_id, n in row.get("findings", {}).items():
            fp = _at(_at(rp, "findings"), kind_id)
            if not kinds:
                c.error(fp, "findings need a top-level kinds list")
            elif kind_id not in kind_set:
                c.error(fp, "no kind has this id; kinds are " + ", ".join(kind_set))
            c.value(n, fp, "int")
    c.unique(row_ids, "row")
    row_set = [i for _, i in row_ids]

    top = page.get("top", [])
    if len(top) > MAX_TOP:
        c.error("top", f"holds {len(top)} findings; the top findings are at most {MAX_TOP}")
    for t, item in enumerate(top):
        tp = _at("top", t)
        item = c.fields(item, tp, TOP)
        if "kind" in item and item["kind"] not in kind_set:
            c.error(_at(tp, "kind"), "no kind has this id" + ("; kinds are " + ", ".join(kind_set) if kind_set else ""))
        for n, rid in enumerate(item.get("rows", [])):
            if rid not in row_set:
                c.error(_at(_at(tp, "rows"), n), f"{json.dumps(rid)} is not a row id")
        if "image" in item:
            c.image(item["image"], _at(tp, "image"))
        if "evidence" not in item and "image" not in item:
            c.warn(tp, "has no evidence or image")
    if "top" not in page:
        c.warn("top", "no top findings; the page skips that section")
    return c


def _check_table(c: Checker, table: object, path: str) -> None:
    table = c.fields(table, path, TABLE)
    cols = table.get("columns", [])
    for i, col in enumerate(cols):
        c.value(col, _at(_at(path, "columns"), i), "str")
    for r, row in enumerate(table.get("rows", [])):
        rp = _at(_at(path, "rows"), r)
        if not isinstance(row, list):
            c.error(rp, f"must be a list of cells, got {_type_name(row)}")
            continue
        if cols and len(row) != len(cols):
            c.error(rp, f"has {len(row)} cells for {len(cols)} columns")
        for n, cell in enumerate(row):
            if isinstance(cell, dict):
                c.fields(cell, _at(rp, n), TABLE_STATUS)
            elif not isinstance(cell, (str, int, float)) or isinstance(cell, bool):
                c.error(_at(rp, n), f"must be text, a number, or a status object, got {_type_name(cell)}")


# ----------------------------------------------------------------- rendering


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def fmt(text: str) -> str:
    """Escape text, then render `code` spans and [label](target) links."""

    def link(m: re.Match) -> str:
        target = html.unescape(m.group(2))
        if SCHEME.match(target) and not target.startswith(("http://", "https://", "mailto:")):
            return m.group(0)
        return f'<a href="{esc(target)}">{m.group(1)}</a>'

    def code(m: re.Match) -> str:
        # Short spans stay on one line, so `--strict` never breaks at its hyphen.
        cls = ' class="nw"' if len(html.unescape(m.group(1))) <= 40 else ""
        return f"<code{cls}>{m.group(1)}</code>"

    return _LINK.sub(link, _CODE.sub(code, esc(text)))


def row_anchor(row_id: str, block_id: str | None = None) -> str:
    # Ids can't contain ".", so a block's anchor never collides with a row's.
    return f"row-{row_id}" + (f".{block_id}" if block_id else "")


class Page:
    def __init__(self, data: dict, in_dir: Path, out_dir: Path):
        self.d = data
        self.in_dir = in_dir
        self.out_dir = out_dir
        self.labels = {s: data["statuses"][s]["label"] for s in STATUSES}
        self.kinds = data.get("kinds", [])
        self.kind_var = {}
        slot = 0
        for k in self.kinds:
            if k.get("other"):
                self.kind_var[k["id"]] = "--k-other"
            else:
                slot += 1
                self.kind_var[k["id"]] = f"--k{slot}"
        self.rows = data["rows"]
        self.row_by_id = {r["id"]: r for r in self.rows}
        self.headings = data.get("headings", {})

    # small pieces

    def chip(self, status: str, text: str | None = None) -> str:
        label = self.labels[status] if text is None else text
        return (
            f'<span class="st st-{status}"><span class="ic" aria-hidden="true">{ICONS[status]}</span>'
            f"{esc(label)}</span>"
        )

    def heading(self, key: str, default: str) -> tuple[str, str]:
        h = self.headings.get(key, {})
        lede = f'<p class="lede">{fmt(h["lede"])}</p>' if h.get("lede") else ""
        return esc(h.get("title", default)), lede

    def image(self, img: dict, thumb: bool = False) -> str:
        src = img["src"]
        if not src.startswith("data:"):
            file = (self.in_dir / src).resolve()
            if img.get("embed"):
                mime = IMAGE_TYPES[file.suffix.lower()]
                src = f"data:{mime};base64," + base64.b64encode(file.read_bytes()).decode("ascii")
            else:
                src = quote(Path(os.path.relpath(file, self.out_dir)).as_posix())
        cap = f"<figcaption>{fmt(img['caption'])}</figcaption>" if img.get("caption") else ""
        attrs = (
            ' class="fig thumb" tabindex="0" role="button" aria-expanded="false" '
            'aria-label="Evidence image; press to enlarge"'
            if thumb
            else ' class="fig"'
        )
        return f'<figure{attrs}><img src="{esc(src)}" alt="{esc(img["alt"])}">{cap}</figure>'

    def row_status(self, row: dict) -> str:
        detail = row.get("detail", {})
        if detail.get("status"):
            return detail["status"]
        found = set()
        for cell in row.get("cells", {}).values():
            for item in cell if isinstance(cell, list) else [cell]:
                found.add(item["status"])
        return next((s for s in SEVERITY if s in found), "pending")

    # sections

    def header(self) -> str:
        d = self.d
        parts = [f"<h1>{esc(d['title'])}</h1>"]
        if d.get("lede"):
            parts.append(f'<p class="lede">{fmt(d["lede"])}</p>')
        if d.get("tiles"):
            tiles = "".join(
                f'<div class="tile"><b>{esc(t["value"])}</b><span>{fmt(t["label"])}</span></div>'
                for t in d["tiles"]
            )
            parts.append(f'<div class="tiles">{tiles}</div>')
        return "<header>" + "".join(parts) + "</header>"

    def legend(self) -> str:
        means = self.d["statuses"]
        items = "".join(
            f'<div class="lg" role="listitem">{self.chip(s)}'
            + (f'<span class="means">{fmt(means[s]["means"])}</span>' if means[s].get("means") else "")
            + "</div>"
            for s in STATUSES
        )
        return f'<div class="legend" role="list" aria-label="Status legend">{items}</div>'

    def cell(self, row: dict, col: dict, cell: dict, item: bool) -> str:
        status = cell["status"]
        name = cell.get("label")
        desc = f"{row['label']} · {col['label']}" + (f" · {name}" if name else "") + f": {self.labels[status]}"
        if "count" in cell:
            value = str(cell["count"])
            desc += f" ({value})"
        elif "state" in cell:
            value = cell["state"]
            desc += f", {value}"
        else:
            value = ""
        if cell.get("tip"):
            desc += f". {cell['tip']}"
        inner = f'<span class="ic" aria-hidden="true">{ICONS[status]}</span>'
        if name:
            inner += f'<span class="nm">{esc(name)}</span>'
        if value:
            inner += f'<span class="v">{esc(value)}</span>'
        cls = f"st st-{status} cell" + (" item" if item else "") + (" state" if "state" in cell else "")
        href = "#" + row_anchor(row["id"], cell.get("link"))
        return f'<a class="{cls}" href="{href}" data-tip="{esc(desc)}" aria-label="{esc(desc)}">{inner}</a>'

    def grid(self) -> str:
        g = self.d["grid"]
        cols = g["columns"]
        title, lede = self.heading("grid", "Inventory")
        head = f'<th scope="col">{esc(g.get("row_header", ""))}</th>' + "".join(
            f'<th scope="col">{esc(c["label"])}'
            + (f"<small>{esc(c['note'])}</small>" if c.get("note") else "")
            + "</th>"
            for c in cols
        )
        body = []
        for row in self.rows:
            cells = row.get("cells", {})
            tds = [
                f'<th scope="row"><a href="#{row_anchor(row["id"])}">{esc(row["label"])}</a>'
                + (f"<small>{esc(row['note'])}</small>" if row.get("note") else "")
                + "</th>"
            ]
            for col in cols:
                v = cells.get(col["id"])
                if isinstance(v, dict):
                    tds.append(f"<td>{self.cell(row, col, v, item=False)}</td>")
                elif v:
                    items = "".join(self.cell(row, col, x, item=True) for x in v)
                    tds.append(f'<td><div class="items">{items}</div></td>')
                else:
                    tds.append(f'<td class="empty">{esc(g.get("empty", "none"))}</td>')
            body.append("<tr>" + "".join(tds) + "</tr>")
        note = f'<p class="note">{fmt(g["cell_note"])}</p>' if g.get("cell_note") else ""
        table = (
            f'<div class="scroll"><table class="grid"><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table></div>"
        )
        return f'<section class="card" id="inventory"><h2>{title}</h2>{lede}{self.legend()}{note}{table}</section>'

    def kinds_section(self) -> str:
        if not self.kinds:
            return ""
        title, lede = self.heading("kinds", "Findings by kind")
        legend = "".join(
            f'<div class="lg" role="listitem"><span class="sw" style="background:var({self.kind_var[k["id"]]})"></span>'
            f"{esc(k['label'])}</div>"
            for k in self.kinds
        )
        totals = [sum(r.get("findings", {}).values()) for r in self.rows]
        scale = max(totals + [1])
        lines = []
        for row, total in zip(self.rows, totals):
            found = row.get("findings", {})
            if total:
                segs, said = [], []
                for k in self.kinds:
                    n = found.get(k["id"], 0)
                    if not n:
                        continue
                    said.append(f"{n} {k['label']}")
                    segs.append(
                        f'<span class="seg" style="flex-basis:{100 * n / scale:.2f}%;'
                        f'background:var({self.kind_var[k["id"]]})" '
                        f'data-tip="{esc(row["label"])} · {esc(k["label"])}: {n}"></span>'
                    )
                bar = (
                    f'<div class="bar" role="img" aria-label="{esc(row["label"])}: {esc(", ".join(said))}">'
                    + "".join(segs)
                    + "</div>"
                )
            else:
                bar = '<span class="none">none</span>'
            lines.append(
                f'<div class="krow"><a class="kname" href="#{row_anchor(row["id"])}">{esc(row["label"])}</a>'
                f'{bar}<span class="ktot">{total or ""}</span></div>'
            )
        head = "".join(f'<th scope="col" class="n">{esc(k["label"])}</th>' for k in self.kinds)
        trs = "".join(
            f'<tr><th scope="row">{esc(r["label"])}</th>'
            + "".join(f'<td class="n">{r.get("findings", {}).get(k["id"], 0)}</td>' for k in self.kinds)
            + f'<td class="n">{t}</td></tr>'
            for r, t in zip(self.rows, totals)
        )
        table = (
            '<details class="tv"><summary>Show as a table</summary><div class="scroll">'
            f'<table class="data"><thead><tr><th scope="col"></th>{head}<th scope="col" class="n">Total</th></tr></thead>'
            f"<tbody>{trs}</tbody></table></div></details>"
        )
        return (
            f'<section class="card" id="kinds"><h2>{title}</h2>{lede}'
            f'<div class="legend" role="list" aria-label="Kinds">{legend}</div>'
            f'<div class="kbars">{"".join(lines)}</div>{table}</section>'
        )

    def top(self) -> str:
        top = self.d.get("top", [])
        if not top:
            return ""
        title, lede = self.heading("top", "The top findings")
        kind_label = {k["id"]: k["label"] for k in self.kinds}
        cards = []
        for i, f in enumerate(top, 1):
            meta = []
            if f.get("kind"):
                meta.append(
                    f'<span class="lg"><span class="sw" style="background:var({self.kind_var[f["kind"]]})"></span>'
                    f"{esc(kind_label[f['kind']])}</span>"
                )
            if f.get("rows"):
                links = ", ".join(
                    f'<a href="#{row_anchor(r)}">{esc(self.row_by_id[r]["label"])}</a>' for r in f["rows"]
                )
                meta.append(f"<span>{links}</span>")
            facts = [("What it says", f["says"])]
            if f.get("evidence"):
                facts.append(("Evidence", f["evidence"]))
            facts += [("The fix", f["fix"]), ("Where the fix goes", f["where"])]
            dl = "".join(f"<dt>{t}</dt><dd>{fmt(v)}</dd>" for t, v in facts)
            fig = self.image(f["image"], thumb=True) if f.get("image") else ""
            cards.append(
                f'<li class="card tcard" id="top-{i}"><div class="thead"><span class="rank">{i}</span>'
                f"<h3>{fmt(f['title'])}</h3>{self.chip(f['status'])}</div>"
                + (f'<p class="tmeta">{"".join(meta)}</p>' if meta else "")
                + f'<div class="tbody{" has-fig" if fig else ""}">{fig}<dl class="facts">{dl}</dl></div></li>'
            )
        return f'<section id="top"><h2>{title}</h2>{lede}<ol class="tops">{"".join(cards)}</ol></section>'

    def table(self, t: dict) -> str:
        head = "".join(f'<th scope="col">{esc(c)}</th>' for c in t["columns"])
        rows = []
        for r in t["rows"]:
            cells = []
            for v in r:
                if isinstance(v, dict):
                    cells.append(f"<td>{self.chip(v['status'], v.get('text'))}</td>")
                else:
                    cells.append(f"<td>{fmt(str(v))}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        return (
            f'<div class="scroll"><table class="data"><thead><tr>{head}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )

    def details(self) -> str:
        title, lede = self.heading("details", "Detail")
        out = [f'<section id="details" class="dintro"><h2>{title}</h2>{lede}</section>']
        for row in self.rows:
            d = row.get("detail", {})
            parts = [
                f'<div class="dhead"><h3>{esc(row["label"])}</h3>{self.chip(self.row_status(row))}'
                '<a class="up" href="#inventory">↑ grid</a></div>'
            ]
            if row.get("note"):
                parts.append(f'<p class="dnote">{esc(row["note"])}</p>')
            if d.get("summary"):
                parts.append(f'<p class="summary">{fmt(d["summary"])}</p>')
            for b in d.get("blocks", []):
                bid = f' id="{row_anchor(row["id"], b["id"])}"' if b.get("id") else ""
                inner = f'<div class="bhead"><h4>{fmt(b["title"])}</h4>'
                inner += (self.chip(b["status"]) if b.get("status") else "") + "</div>"
                if b.get("image"):
                    inner += self.image(b["image"])
                if b.get("story"):
                    inner += f'<p class="story">{fmt(b["story"])}</p>'
                if b.get("table"):
                    inner += self.table(b["table"])
                parts.append(f'<div class="block"{bid}>{inner}</div>')
            out.append(f'<section class="card detail" id="{row_anchor(row["id"])}">{"".join(parts)}</section>')
        return "".join(out)

    def html(self) -> str:
        footer = f"<footer>{fmt(self.d['footer'])}</footer>" if self.d.get("footer") else ""
        body = self.header() + self.grid() + self.kinds_section() + self.top() + self.details() + footer
        return (
            '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="color-scheme" content="light dark"><link rel="icon" href="data:,">'
            f"<title>{esc(self.d['title'])}</title><style>{css()}</style></head>\n"
            f'<body><main>{body}</main><div id="tip" role="tooltip" hidden></div>'
            f"<script>{TIP_JS}</script></body></html>\n"
        )


def css() -> str:
    light = "".join(f"--k{i}:{c[0]};" for i, c in enumerate(KIND_SLOTS, 1))
    dark = "".join(f"--k{i}:{c[1]};" for i, c in enumerate(KIND_SLOTS, 1))
    dark_vars = DARK + dark
    return (
        ":root{color-scheme:light;" + LIGHT + light + "}"
        "@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){" + dark_vars + "}}"
        ":root[data-theme=dark]{" + dark_vars + "}" + CSS
    )


# Chart chrome and ink from the dataviz skill's palette; the five status colors
# exactly as the visual-inventory contract fixes them.
LIGHT = (
    "--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;"
    "--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--code:rgba(11,11,11,.06);--fig:#fcfcfb;"
    "--st-good:#0ca30c;--st-good-ink:#ffffff;--st-watch:#fab219;--st-watch-ink:#0b0b0b;"
    "--st-problem:#d03b3b;--st-problem-ink:#ffffff;--st-out:#e1e0d9;--st-out-ink:#52514e;"
    f"--st-pending-line:#898781;--k-other:{OTHER_KIND};"
)
# Dark keeps the three colored statuses (each clears 3:1 on the dark surface)
# and the figure surface (figures are drawn for a light background).
DARK = (
    "color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;"
    "--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--code:rgba(255,255,255,.08);"
    "--st-out:#383835;--st-out-ink:#c3c2b7;"
)

CSS = """
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:clamp(24px,3.6vw,32px);line-height:1.15;margin:0 0 8px;text-wrap:balance}
h2{font-size:19px;margin:0 0 6px}
h3{font-size:16px;margin:0}
h4{font-size:14px;margin:0}
p{margin:0}
a{color:inherit}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--code);padding:1px 4px;border-radius:4px;overflow-wrap:anywhere}
code.nw{white-space:nowrap}
.lede{color:var(--ink2);max-width:78ch;margin:0 0 12px}
header .lede{font-size:16px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:18px;margin:16px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:16px 0 0}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:24px;line-height:1.25}
.tile span{color:var(--ink2);font-size:13px}
.st{display:inline-flex;align-items:center;gap:6px;border:1.5px solid transparent;border-radius:6px;padding:2px 8px;font-size:12.5px;font-weight:600;line-height:1.35;white-space:nowrap;text-decoration:none}
.st .ic{font-weight:700;width:1em;text-align:center;flex:none}
.st-good{background:var(--st-good);color:var(--st-good-ink)}
.st-watch{background:var(--st-watch);color:var(--st-watch-ink)}
.st-problem{background:var(--st-problem);color:var(--st-problem-ink)}
.st-out{background:var(--st-out);color:var(--st-out-ink)}
.st-pending{background:transparent;color:var(--ink2);border:1.5px dashed var(--st-pending-line)}
a.st:hover,a.st:focus-visible{outline:2px solid var(--ink);outline-offset:1px}
.legend{display:flex;flex-wrap:wrap;gap:8px 20px;margin:4px 0 12px}
.lg{display:inline-flex;align-items:center;gap:7px;font-size:13px}
.lg .means{color:var(--ink2)}
.note{color:var(--ink2);font-size:13px;margin:0 0 10px}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px;flex:none}
.scroll{overflow-x:auto}
.grid{border-collapse:separate;border-spacing:3px;min-width:100%}
.grid th{font-size:12px;font-weight:600;color:var(--ink2);text-align:left;vertical-align:bottom;padding:4px 6px}
.grid th small{display:block;font-weight:400;color:var(--ink2)}
.grid thead th:first-child,.grid th[scope=row]{position:sticky;left:0;z-index:1;background:var(--surface)}
.grid th[scope=row]{font-size:14px;color:var(--ink);vertical-align:middle;padding:4px 12px 4px 0;min-width:8rem}
.grid th[scope=row] a{text-decoration:none}
.grid th[scope=row] a:hover{text-decoration:underline}
.grid td{padding:0;vertical-align:middle;min-width:5.5rem}
.grid td.empty{color:var(--ink2);font-size:12px;text-align:center}
.grid a.cell{display:flex;justify-content:center;width:100%;min-height:32px;font-size:13.5px;font-variant-numeric:tabular-nums}
.grid a.cell.state{justify-content:flex-start}
.items{display:flex;flex-wrap:wrap;gap:3px}
.grid a.cell.item{width:auto;min-height:28px;font-size:12.5px;justify-content:flex-start}
.cell .nm{font-weight:500}
.kbars{display:flex;flex-direction:column;gap:2px}
.krow{display:grid;grid-template-columns:minmax(6rem,14rem) minmax(0,1fr) 3ch;align-items:center;gap:12px;padding:4px 0}
.kname{font-size:13.5px;text-decoration:none}
.kname:hover{text-decoration:underline}
.bar{display:flex;gap:2px;height:14px}
.seg{flex:0 1 auto;min-width:3px;height:100%}
.seg:last-child{border-radius:0 4px 4px 0}
.ktot{font-size:13px;color:var(--ink2);text-align:right;font-variant-numeric:tabular-nums}
.none{color:var(--ink2);font-size:12px}
.tv{margin-top:12px;font-size:13px}
.tv summary{cursor:pointer;color:var(--ink2)}
.data{border-collapse:collapse;font-size:13px;width:100%;margin-top:4px}
.data th,.data td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
.data thead th{font-size:12px;color:var(--ink2);font-weight:600;border-bottom-color:var(--axis)}
.data .n{text-align:right;font-variant-numeric:tabular-nums}
#top{margin:28px 0 0}
.tops{list-style:none;margin:0;padding:0}
.tcard{margin:12px 0}
.thead{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px}
.rank{font-size:20px;font-weight:700;color:var(--ink2);min-width:1.2em}
.thead h3{flex:1 1 18rem}
.tmeta{display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px;color:var(--ink2);font-size:13px;margin:6px 0 0}
.tbody{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;margin-top:12px}
.tbody.has-fig{grid-template-columns:minmax(0,260px) minmax(0,1fr)}
.facts{display:grid;grid-template-columns:9.5rem minmax(0,1fr);gap:6px 14px;margin:0}
.facts dt{color:var(--ink2);font-size:13px;font-weight:600;padding-top:1px}
.facts dd{margin:0}
.fig{margin:0;background:var(--fig);border:1px solid var(--ring);border-radius:8px;padding:8px;max-width:820px}
.fig img{display:block;width:100%;height:auto}
.fig figcaption{color:#52514e;font-size:12px;margin-top:6px}
.fig figcaption code{background:rgba(11,11,11,.06)}
.fig.thumb{cursor:zoom-in}
.fig.thumb:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.tbody.open{grid-template-columns:minmax(0,1fr)}
.tbody.open .fig.thumb{cursor:zoom-out}
.dintro{margin:32px 0 0}
.detail{scroll-margin-top:12px}
.dhead{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px}
.dhead .up{margin-left:auto;font-size:12.5px;color:var(--ink2);text-decoration:none}
.dhead .up:hover{text-decoration:underline}
.dnote{color:var(--ink2);font-size:13px;margin-top:2px}
.summary{margin-top:8px;max-width:80ch}
.block{border-top:1px solid var(--grid);margin-top:16px;padding-top:14px;display:flex;flex-direction:column;gap:10px;scroll-margin-top:12px}
.bhead{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}
.story{max-width:80ch}
.detail:target,.block:target{outline:2px solid var(--ink);outline-offset:4px;border-radius:6px}
footer{color:var(--ink2);font-size:12.5px;margin-top:28px;border-top:1px solid var(--grid);padding-top:12px}
#tip{position:fixed;z-index:10;pointer-events:none;max-width:22rem;background:var(--ink);color:var(--page);font-size:12.5px;line-height:1.4;padding:5px 9px;border-radius:6px}
#tip[hidden]{display:none}
@media (max-width:720px){
.card{padding:14px}
.tbody.has-fig{grid-template-columns:minmax(0,1fr)}
.facts{grid-template-columns:minmax(0,1fr);gap:2px}
.facts dd{margin-bottom:8px}
.krow{grid-template-columns:minmax(0,6.5rem) minmax(0,1fr) 3ch;gap:8px}
}
@media (forced-colors:active){.st,.seg{border:1.5px solid CanvasText}}
"""

# A hover and keyboard-focus tooltip for anything with data-tip, and
# click-to-enlarge for the top findings' evidence thumbnails.
TIP_JS = """
(()=>{const tip=document.getElementById('tip');
function zoom(f){const open=f.closest('.tbody').classList.toggle('open');f.setAttribute('aria-expanded',open)}
document.addEventListener('click',e=>{const f=e.target.closest&&e.target.closest('.fig.thumb');if(f)zoom(f)});
document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches&&e.target.matches('.fig.thumb')){e.preventDefault();zoom(e.target)}});
function show(t,x,y){tip.textContent=t.dataset.tip;tip.hidden=false;
const w=tip.offsetWidth,h=tip.offsetHeight;
tip.style.left=Math.max(8,Math.min(x+12,innerWidth-w-8))+'px';
tip.style.top=Math.max(8,Math.min(y+14,innerHeight-h-8))+'px'}
document.addEventListener('pointermove',e=>{const t=e.target.closest&&e.target.closest('[data-tip]');
if(t)show(t,e.clientX,e.clientY);else tip.hidden=true});
document.addEventListener('focusin',e=>{const t=e.target.closest&&e.target.closest('[data-tip]');
if(!t){tip.hidden=true;return}const r=t.getBoundingClientRect();show(t,r.left,r.bottom)});
document.addEventListener('focusout',()=>{tip.hidden=true});
addEventListener('scroll',()=>{tip.hidden=true},{passive:true});})();
"""


# ---------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a visual-inventory page from one JSON file.")
    ap.add_argument("input", type=Path, help="the page's JSON input")
    ap.add_argument("-o", "--out", type=Path, help="where to write the page (default: index.html beside the input)")
    ap.add_argument("--check", action="store_true", help="validate the input and write nothing")
    ap.add_argument("--open", action="store_true", help="open the rendered page in the default browser")
    args = ap.parse_args(argv)

    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: {args.input}: no such file", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"error: {args.input}: not valid JSON: {e.msg} at line {e.lineno}, column {e.colno}", file=sys.stderr)
        return 1

    in_dir = args.input.resolve().parent
    checker = validate(data, in_dir)
    for w in checker.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if checker.errors:
        for e in checker.errors:
            print(f"error: {e}", file=sys.stderr)
        print(f"{len(checker.errors)} error(s) in {args.input}; nothing written", file=sys.stderr)
        return 1
    if args.check:
        cols = len(data["grid"]["columns"])
        print(
            f"ok: {args.input} · {len(data['rows'])} rows × {cols} columns · "
            f"{len(data.get('kinds', []))} kinds · {len(data.get('top', []))} top findings"
        )
        return 0

    out = (args.out or in_dir / "index.html").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(Page(data, in_dir, out.parent).html(), encoding="utf-8")
    print(out)
    if args.open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
