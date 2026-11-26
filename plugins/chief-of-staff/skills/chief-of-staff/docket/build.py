#!/usr/bin/env python3
"""Build Docket, a local, interactive view of the chief-of-staff questions file.

The questions file is `$COS_QUESTIONS`, or `~/.claude/chief-of-staff/questions.md`. Everything
generated (the page, the answer inbox, the page's key) goes in a `docket/` folder beside that
file, never beside this script: the questions file may hold confidential detail, so the page is
served from this machine only and never published.

Optional: `COS_GITHUB_ORG=<org>` turns "<repo> #<n>" in the text into links to that org's PRs.
`COS_DOCKET_PORT` (default 8765) is the port server.py listens on and `--open` opens (in Google
Chrome on macOS when it is installed, otherwise the default browser).

Usage: python3 -I build.py [--open]
"""
import os
import datetime as dt
import hashlib
import html
import json
import re
import subprocess
import sys
from pathlib import Path

SOURCE = Path(os.environ.get("COS_QUESTIONS", "~/.claude/chief-of-staff/questions.md")).expanduser()
HERE = SOURCE.parent / "docket"
HERE.mkdir(exist_ok=True)
OUT = HERE / "index.html"
ORG = os.environ.get("COS_GITHUB_ORG", "")

# The work types are the board's own `### ` subheadings under `## By work type`, in order, so a
# user renames or adds a type by editing the board. set_types() reads them; a `[tag]` that names
# no subheading becomes a type of its own. Colours are assigned by position: (light, dark).
TYPES: list = []
TYPE_LABEL: dict = {}
PALETTE = [("#7a5af5", "#a78bfa"), ("#c2410c", "#fb923c"), ("#0e7490", "#22d3ee"), ("#4d7c0f", "#a3e635"),
           ("#be185d", "#f472b6"), ("#1d4ed8", "#60a5fa"), ("#78716c", "#a8a29e"), ("#b45309", "#fbbf24"),
           ("#0f766e", "#2dd4bf"), ("#9333ea", "#c084fc")]
COLUMNS = [("you", "Waiting on you"), ("others", "Waiting on others"), ("someday", "Someday"), ("done", "Done")]
DONE_DAYS = 7  # the Done column shows what closed in the last week


def type_label(head: str) -> str:
    """A subheading is `<Name> (<what it covers>)`, or `<Group>: <Name> (…)` to group types.
    The label is <Name>: `Building: data & science (estimators, …)` -> `Data & science`,
    `Admin (…)` -> `Admin`. Its key, and so its `[tag]`, is the first word of <Name>."""
    label = re.sub(r"\s*\(.*$", "", head).strip()
    label = label.split(":", 1)[1].strip() if ":" in label else label
    return label[:1].upper() + label[1:] if label else "Other"


def _add_type(label: str) -> str:
    words = re.findall(r"[a-z0-9]+", label.lower()) or ["other"]
    key = words[0] if words[0] not in TYPE_LABEL else "-".join(words)
    while key in TYPE_LABEL:
        key += "x"
    TYPES.append((key, label))
    TYPE_LABEL[key] = label
    return key


def set_types(by_work_type: str) -> None:
    """Reset the types to the `### ` subheadings of the By work type section."""
    TYPES.clear()
    TYPE_LABEL.clear()
    for head, _ in split_h3(by_work_type):
        _add_type(type_label(head))


def type_key(text: str) -> str:
    """The type a `[tag]` or a subheading names, tried in order across all types: its key, its
    exact label, then its key as a word in a longer name. An empty tag, or a template
    placeholder like `<type>`, is the first type; an unknown one becomes a new type."""
    t = text.lower().strip()
    if not t or re.fullmatch(r"<[^>]*>", t):
        return TYPES[0][0] if TYPES else _add_type("Other")
    if t in TYPE_LABEL:
        return t
    label = type_label(text).lower()
    for key, lab in TYPES:
        if label == lab.lower():
            return key
    for key, _ in TYPES:
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", label):
            return key
    return _add_type(type_label(text))


def type_css(dark: bool) -> str:
    return ";".join(f"--t-{k}:{PALETTE[i % len(PALETTE)][dark]}" for i, (k, _) in enumerate(TYPES))


def open_page(url: str, platform: str = sys.platform, run=subprocess.run) -> str:
    """Open the page: Google Chrome on macOS when it is installed, else the default browser.
    Returns what it used, so a test can force the platform."""
    if platform == "darwin" and run(["open", "-a", "Google Chrome", url]).returncode == 0:
        return "chrome"
    import webbrowser
    webbrowser.open(url)
    return "default"


# ---------- repo links ----------

def _repos() -> set[str]:
    if not ORG:
        return set()
    cache = HERE / ".repos.json"
    try:
        if cache.exists() and dt.datetime.now().timestamp() - cache.stat().st_mtime < 86400:
            return set(json.loads(cache.read_text()))
        out = subprocess.run(["gh", "repo", "list", ORG, "--limit", "300", "--json", "name", "-q", ".[].name"],
                             capture_output=True, text=True, timeout=30).stdout.split()
        if out:
            cache.write_text(json.dumps(out))
        return set(out)
    except Exception:
        return set()


REPOS = _repos()


def link_prs(html_text: str) -> str:
    def sub(m):
        repo, n = m.group(1), m.group(2)
        if repo not in REPOS:
            return m.group(0)
        return f'<a href="https://github.com/{ORG}/{repo}/pull/{n}" target="_blank" rel="noopener">{repo} #{n}</a>'
    return re.sub(r"(?<![/\w-])([a-z0-9][a-z0-9-]+)\s#(\d+)\b", sub, html_text)


# ---------- tiny markdown ----------

def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', out)
    out = re.sub(r'(?<![">=])(https?://[^\s<)]+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', out)
    return link_prs(out)


def md(text: str) -> str:
    lines = text.strip("\n").split("\n")
    parts, para, items, kind, code = [], [], [], None, None
    blank = False  # a blank line inside a list ends it only if a non-list line follows

    def flush_para():
        if para:
            parts.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    def flush_list():
        nonlocal kind
        if items:
            tag = "ol" if kind == "ol" else "ul"
            parts.append(f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{tag}>")
            items.clear()
        kind = None

    for line in lines:
        if code is not None:
            if line.strip().startswith("```"):
                parts.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
                code = None
            else:
                code.append(line)
            continue
        if line.strip().startswith("```"):
            flush_para(); flush_list(); code = []
            continue
        m_ul = re.match(r"^\s*- (.*)", line)
        m_ol = re.match(r"^\s*\d+\. (.*)", line)
        if m_ul or m_ol:
            flush_para()
            k = "ul" if m_ul else "ol"
            if kind and kind != k:
                flush_list()
            kind = k
            items.append((m_ul or m_ol).group(1))
            blank = False
        elif not line.strip():
            flush_para(); blank = True
        elif line.startswith("|"):
            continue
        else:
            if items and line.startswith("  ") and not blank:
                items[-1] += " " + line.strip()
            else:
                flush_list()
                para.append(line.strip())
            blank = False
    flush_para(); flush_list()
    return "\n".join(parts)


# ---------- parse questions.md ----------

def sections(text: str) -> dict:
    out, name, buf = {}, "_head", []
    for line in text.split("\n"):
        m = re.match(r"^## (.+)", line)
        if m:
            out[name] = "\n".join(buf)
            name, buf = m.group(1).strip(), []
        else:
            buf.append(line)
    out[name] = "\n".join(buf)
    return out


def split_h3(text: str) -> list[tuple[str, str]]:
    blocks, head, buf = [], None, []
    for line in text.split("\n"):
        m = re.match(r"^### (.+)", line)
        if m:
            if head is not None:
                blocks.append((head, "\n".join(buf)))
            head, buf = m.group(1).strip(), []
        elif head is not None:
            buf.append(line)
    if head is not None:
        blocks.append((head, "\n".join(buf)))
    return blocks


def project_of(text: str) -> str:
    m = re.search(r"\.\s+([A-Z][\w &/.()-]{1,40})\.\s*$", text.strip())
    return m.group(1).strip() if m else ""


def field(body: str, name: str) -> str:
    m = re.search(r"\*\*" + re.escape(name) + r":\*\*\s*(.+)", body)
    return m.group(1).strip() if m else ""


def block(body: str, name: str) -> str:
    m = re.search(r"^\*\*" + re.escape(name) + r"\*\*\s*\n(.*?)(?=^\*\*[A-Z][^*]*\*\*\s*$|^Refs:|\Z)", body, flags=re.M | re.S)
    return m.group(1).strip() if m else ""


def split_call(call: str) -> tuple[str, str, str]:
    """'<ask>. **Lean: (a)**, because <why>' -> (ask, lean key, reason)."""
    m = re.search(r"\*\*Lean:?\s*\(?([a-z0-9]+)?\)?[^*]*\*\*,?\s*(.*)", call)
    if not m:
        return call, "", ""
    return call[:m.start()].strip(), (m.group(1) or ""), m.group(2).strip()


def options(body: str) -> list[dict]:
    """'1. **(a) Label.** detail' lines, with indented continuation lines folded into the detail."""
    out = []
    for line in body.split("\n"):
        m = re.match(r"^\d+\.\s+\*\*\(([a-z])\)\s+(.+?)\*\*\s*(.*)$", line)
        if m:
            out.append({"key": m.group(1), "label": re.sub(r"\*\*", "", m.group(2)).strip(" .,;"), "detail": m.group(3).strip()})
        elif out and line.startswith("  ") and line.strip():
            out[-1]["detail"] = (out[-1]["detail"] + " " + line.strip()).strip()
        elif not line.strip() or re.match(r"^\d+\.\s", line):
            continue
        elif out:
            break
    for o in out:
        o["detailHtml"] = inline(o.pop("detail"))
    return out


def closed_on(body: str) -> str:
    """The date on an answered record's `**Answered** <date>` or `**Settled** <date>` line."""
    m = re.search(r"^\*\*(?:Answered|Settled|Dropped)\*\*\s*(\d{4}-\d{2}-\d{2})", body, flags=re.M)
    return m.group(1) if m else ""


def parse_questions(text: str, col: str = "you", since: str = "") -> list[dict]:
    """Question records. For Answered (`since` set), only those closed on or after `since`."""
    cards = []
    for head, body in split_h3(text):
        m = re.match(r"(\d+)\.\s+(?:\[([^\]]+)\]\s+)?(?:([^:]+):\s+)?(.*)", head)
        if not m:
            continue
        num, tag, project, title = m.groups()
        done = closed_on(body) if since else ""
        if since and done < since:
            continue
        opts = options(body)
        why = next((l.strip() for l in body.strip().split("\n") if l.strip() and not l.startswith("**") and not l.startswith("Refs:")), "")
        ask, lean, reason = split_call(field(body, "Your call"))
        lean_label = next((o["label"] for o in opts if o["key"] == lean), "")
        refs = re.search(r"^Refs:\s*(.+)", body, flags=re.M)
        cards.append({
            "kind": "question", "id": f"q{num}", "num": num, "type": type_key(tag or ""), "col": col, "done": done,
            "tag": tag or "", "project": (project or "").strip(), "title": title.strip(),
            "summary": why, "call": ask, "lean": lean, "leanLabel": lean_label, "leanWhy": reason,
            "options": opts,
            "parts": {
                "why": inline(why), "ask": inline(ask), "leanWhy": inline(reason),
                "rank": inline(field(body, "Rank")), "for": inline(field(body, "For")),
                "askedBy": inline(field(body, "Asked by")),
                "options": md(block(body, "Options")), "facts": md(block(body, "Facts")),
                "refs": inline(refs.group(1)) if refs else "",
            },
            "body": md(body),
        })
    return cards


def split_item(text: str) -> tuple[str, str]:
    """First sentence as the title, the rest as detail."""
    m = re.match(r"(.+?[.:;])\s+(.+)", text)
    if not m or len(m.group(1)) < 12:
        return text, ""
    return m.group(1).rstrip(".:;"), m.group(2)


def item_card(line: str, tkey: str, tag: str, col: str, ids: set, done: str = "") -> "dict | None":
    """One `- **Title.** State. Project.` line as a card, or None for a line that only points at
    numbered questions (they have their own cards)."""
    item = line.strip()
    head_part = re.split(r";\s+(?=\d+\b)", item)[0]
    if head_part != item:  # "<item>; 26 (Project)." points at questions after the item: keep the item
        item = head_part.rstrip(" .;") + "."
    if re.match(r"^\d+(\s*(,|to)\s*\d+)*\s*[.:(]", item):
        return None
    project = project_of(item)
    if project and item.rstrip().endswith(project + "."):
        item = item.rstrip()[: -len(project) - 1].rstrip()
    bm = re.match(r"\*\*(.+?)\*\*\s*(.*)$", item)
    ttl, rest = (bm.group(1).rstrip("."), bm.group(2)) if bm else split_item(item)
    cid = "i" + hashlib.sha1(ttl.encode()).hexdigest()[:10]
    while cid in ids:
        cid += "x"
    ids.add(cid)
    return {"kind": "item", "id": cid, "type": tkey, "tag": tag, "col": col, "done": done,
            "project": project, "title": ttl, "summary": rest, "call": "", "body": "",
            "parts": {"why": inline(rest)}}


def parse_work_types(text: str, ids: set) -> list[dict]:
    cards = []
    for head, body in split_h3(text):
        tkey = type_key(head)
        for line in body.split("\n"):
            m = re.match(r"^- (.+)", line)
            c = item_card(m.group(1), tkey, head, "you", ids) if m else None
            if c:
                cards.append(c)
    return cards


def parse_column(text: str, col: str, ids: set, since: str = "") -> list[dict]:
    """Waiting on others, Someday or Done: tagged items first (`- [type] **Title.** …`, or
    `- [type, done <date>] …` in Done), then any question records."""
    cards = []
    items = re.split(r"^### ", text, maxsplit=1, flags=re.M)[0]
    for line in items.split("\n"):
        m = re.match(r"^- \[([^\],]+)(?:,\s*done\s+(\d{4}-\d{2}-\d{2}))?\]\s+(.+)", line)
        if not m:
            continue
        tag, done, rest = m.groups()
        if since and (done or "") < since:
            continue
        c = item_card(rest, type_key(tag), tag, col, ids, done or "")
        if c:
            cards.append(c)
    return parse_questions(text, col) + cards


def parse_table(text: str) -> tuple[list[str], list[list[str]]]:
    rows = [l for l in text.split("\n") if l.startswith("|")]
    if len(rows) < 2:
        return [], []
    split = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
    return split(rows[0]), [split(r) for r in rows[2:]]


def parse_commands(text: str) -> list[dict]:
    out = []
    for h, b in split_h3(text):
        code = re.search(r"```[a-z]*\n(.*?)```", b, flags=re.S)
        cmd = code.group(1).strip() if code else ""
        rest = re.sub(r"```[a-z]*\n.*?```", "", b, flags=re.S)
        expect = re.search(r"\*\*Expect:\*\*\s*(.+)", rest)
        rest = re.sub(r"\*\*Expect:\*\*.*", "", rest)
        cid = re.match(r"(C\d+)\.", h)
        out.append({"title": h, "id": cid.group(1) if cid else h[:20], "cmd": cmd,
                    "deletes": bool(re.search(r"\b(rm|delete|drop|destroy|terminate)\b", cmd)),
                    "body": md(rest), "expect": inline(expect.group(1)) if expect else ""})
    return out


HEADLINE = ("now", "next", "status", "date", "dates", "waiting on you")


def parse_projects(text: str) -> list[dict]:
    """Per project: a status pill, the headline bullets (**Now:**, **Next:**, **Status:**, **Date:**),
    and everything else as collapsed reference."""
    out = []
    for head, body in split_h3(text):
        bullets, cur = [], None
        for line in body.split("\n"):
            if re.match(r"^- ", line):
                cur = line[2:].strip(); bullets.append(cur)
            elif line.startswith("  ") and bullets:
                bullets[-1] += " " + line.strip()
        lead, ref, status = [], [], ""
        for b in bullets:
            m = re.match(r"\*\*([^*:]+):\*\*\s*(.*)", b)
            key = m.group(1).strip().lower() if m else ""
            if key == "status":
                status = m.group(2).strip()
            elif key in HEADLINE:
                lead.append({"label": m.group(1).strip(), "html": inline(m.group(2))})
            else:
                ref.append(inline(b))
        name = re.sub(r"\s*\(.*\)\s*$", "", head).strip()
        out.append({"title": head, "name": name, "status": status, "lead": lead,
                    "ref": ref, "body": md(body)})
    return out


def live_sessions() -> list[dict]:
    try:
        raw = subprocess.run(["claude", "agents", "--json", "--all"], capture_output=True, text=True, timeout=20).stdout
        data = json.loads(raw)
    except Exception:
        return []
    data = data if isinstance(data, list) else data.get("agents", [])
    seen, out = set(), []
    for a in data:
        name = a.get("name") or ""
        status = a.get("status") or a.get("state") or ""
        if status in ("done", "stopped") or not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "status": status, "cwd": (a.get("cwd") or "").replace(str(Path.home()), "~"),
                    "kind": a.get("kind") or "", "sessionId": a.get("sessionId") or ""})
    return sorted(out, key=lambda s: s["name"])


# ---------- page ----------

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Docket</title>
<style>
:root{--bg:#faf9f5;--panel:#fff;--col:#f5f4ef;--ink:#141413;--ink2:#5c5c5a;--muted:#8c8c8a;--line:#e5e4df;--line2:#eeeee9;--accent:#d97757;--chip:#f5f4ef;--warn:#a5521b;
--shadow:rgba(20,20,19,.04);--shadow2:rgba(20,20,19,.08);
__TYPECSS_LIGHT__}
@media (prefers-color-scheme: dark){:root{--bg:#1a1918;--panel:#262523;--col:#201f1d;--ink:#f0eee6;--ink2:#c2c0b6;--muted:#9a988f;--line:#3a3935;--line2:#302f2c;--chip:#2c2b28;--accent:#e08a6d;--warn:#f59e0b;
--shadow:rgba(0,0,0,.2);--shadow2:rgba(0,0,0,.35);__TYPECSS_DARK__}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:14px 20px 10px}
h1{font-size:18px;margin:0 0 2px}.sub{color:var(--muted);font-size:13px}
.bar{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;align-items:center}
.chip{border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:999px;padding:4px 11px;font-size:13px;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
.chip .n{color:var(--muted);font-variant-numeric:tabular-nums}.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}.chip.on .n{color:inherit;opacity:.7}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
select,input[type=search]{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;padding:5px 9px;font-size:13px}
input[type=search]{min-width:200px;flex:1;max-width:320px}
nav{display:flex;gap:16px;margin-top:10px}nav button{background:none;border:0;color:var(--muted);font-size:14px;padding:4px 0;cursor:pointer;border-bottom:2px solid transparent}
nav button.on{color:var(--ink);border-color:var(--accent)}
main{padding:16px 20px 40px;max-width:1200px;margin:0 auto}main.wide{max-width:1560px}
.board{display:grid;grid-template-columns:repeat(4,minmax(260px,1fr));gap:18px;align-items:stretch;min-height:calc(100vh - 210px)}
.col{background:var(--col);border-radius:12px;display:flex;flex-direction:column;min-height:160px}
.colh{padding:14px 16px 10px;font-weight:600;font-size:12.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink2);display:flex;justify-content:space-between;align-items:center}
.colh .count{background:var(--panel);padding:2px 10px;border-radius:12px;font-size:12px;font-weight:500;color:var(--muted);letter-spacing:0}
.cards{flex:1;padding:0 10px 10px;min-height:80px;border-radius:10px;transition:background .12s}.cards.over{background:rgba(217,119,87,.09);outline:2px dashed var(--accent);outline-offset:-4px}
.sublbl{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600;margin:4px 4px 8px}.sublbl:not(:first-child){margin-top:14px}
.colempty{color:var(--muted);font-size:13px;padding:14px 6px;text-align:center}
.card{background:var(--panel);border:1px solid var(--line2);border-left:3px solid var(--c,var(--line));border-radius:10px;padding:12px 14px;cursor:pointer;margin-bottom:10px;box-shadow:0 1px 3px var(--shadow);transition:box-shadow .15s,border-color .15s;display:flex;gap:10px;align-items:flex-start}
.card:hover{box-shadow:0 4px 12px var(--shadow2);border-color:var(--line);border-left-color:var(--c)}.card[draggable=true]{cursor:grab}.card.dragging{opacity:.5;transform:rotate(1.5deg)}.card a{-webkit-user-drag:none}
.card .cb{flex:1;min-width:0}.card.closed .title{color:var(--muted);text-decoration:line-through}.card.pending{opacity:.75;border-style:dashed}
.tick{width:18px;height:18px;min-width:18px;margin-top:2px;border:2px solid var(--line);border-radius:5px;background:var(--panel);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;padding:0}
.tick:hover{border-color:var(--accent)}.tick.on{background:var(--accent);border-color:var(--accent);cursor:default}.tick.on::after{content:"";width:5px;height:9px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg);margin-bottom:2px}
.movb{color:var(--accent);font-weight:600}.moverow{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:12px 0 0}.moverow .chip.on{cursor:default}
@media (max-width:1100px){.board{grid-template-columns:repeat(2,minmax(260px,1fr));min-height:0}}
.meta{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--muted);margin-bottom:4px}
.num{font-weight:600;color:var(--ink)}.title{font-weight:600;font-size:15px;line-height:1.35}
.why{margin-top:6px;font-size:13.5px;color:var(--muted);line-height:1.45;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.lean{margin-top:8px;font-size:13px;line-height:1.4}.lk{display:inline-block;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);font-weight:700;margin-right:4px}
.call{margin-top:6px;font-size:13.5px;color:var(--muted)}
.call strong{color:var(--ink)}
section.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:12px}
section.panel h3{margin:0 0 6px;font-size:15px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}.bad{color:var(--warn);font-weight:600}
code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12.5px}pre{background:var(--chip);padding:10px;border-radius:8px;overflow-x:auto}pre code{background:none;padding:0}
a{color:var(--accent)}
dialog p,dialog li,dialog dd{line-height:1.55}dialog p{margin:0 0 10px}dialog ul,dialog ol{padding-left:20px;margin:4px 0 12px}dialog li{margin-bottom:6px}
dialog h4{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:16px 0 6px}
.lead{font-size:15.5px;color:var(--ink)}.askbox{border-left:3px solid var(--accent);background:var(--bg);border-radius:6px;padding:10px 12px;margin:10px 0}
.askbox .lbl{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:700;margin-bottom:3px}.leanline{margin-top:8px;font-size:14px}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;font-size:13.5px;margin:14px 0}.kv dt{color:var(--muted);font-weight:600}.kv dd{margin:0}
.refs{font-size:12.5px;color:var(--muted);margin-top:14px;word-break:break-word}.opts-detail ol{padding-left:18px}
code{word-break:break-word}
dialog{max-width:760px;width:calc(100% - 32px);border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--ink);padding:18px 22px}
dialog::backdrop{background:rgba(0,0,0,.45)}dialog h2{margin:0 0 4px;font-size:17px}.close{float:right;cursor:pointer;background:none;border:0;color:var(--muted);font-size:20px}
.sess{display:flex;gap:10px;align-items:center;padding:6px 0;border-bottom:1px solid var(--line);font-size:13px}.sess:last-child{border:0}
.attach{margin-left:auto;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:8px;padding:3px 10px;font-size:12.5px;cursor:pointer;white-space:nowrap}.attach:hover{border-color:var(--accent)}
.st{font-size:11px;padding:1px 7px;border-radius:999px;background:var(--chip)}.st.busy{background:var(--accent);color:var(--bg)}
.empty{color:var(--muted);padding:20px 0}
h2.grp{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink);margin:18px 0 10px;display:flex;gap:8px;align-items:baseline}h2.grp:first-child{margin-top:4px}h2.grp .n{color:var(--muted);font-variant-numeric:tabular-nums}h2.grp .gs{text-transform:none;letter-spacing:0;font-weight:400;color:var(--muted);font-size:12.5px}
.ans{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:10px 0 14px;background:var(--bg)}.opts{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.opts{flex-direction:column}.opt{text-align:left;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;width:100%;white-space:normal;line-height:1.4;padding:8px 11px;cursor:pointer;font:inherit;font-size:14px;display:flex;flex-direction:column;gap:3px}.opt:hover{border-color:var(--accent)}.opt.rec{border-color:var(--accent)}.opt .ol{font-weight:600}.opt .od{color:var(--muted);font-size:13px}.opt .od a{pointer-events:none}.opt.on{background:var(--accent);color:var(--bg);border-color:var(--accent)}.opt.on .od,.opt.on .lk{color:inherit}textarea{width:100%;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);padding:7px 9px;font:inherit;font-size:14px}
.row{display:flex;gap:10px;align-items:center;margin-top:8px}.send{background:var(--accent);color:var(--bg);border:0;border-radius:8px;padding:6px 14px;font-weight:600;cursor:pointer}
.sentb{color:var(--accent);font-weight:600}.notebar{margin:12px 0}
.proj .ph{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}.proj .ph h3{margin:0}.pw{margin-left:auto}.rf{white-space:nowrap}
.pill{font-size:11.5px;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--chip);color:var(--muted)}.pill.wait{background:#f59e0b22;color:var(--warn)}.pill.block{background:#dc262622;color:#ef4444}.pill.move{background:#16a34a22;color:var(--accent)}
.pl{margin:6px 0;line-height:1.5}.proj details{margin-top:10px;font-size:13.5px;color:var(--muted)}.proj summary{cursor:pointer;font-size:12.5px}.proj details ul{padding-left:18px}.proj details li{margin:5px 0}
pre.cmd{white-space:pre-wrap;word-break:break-all;font-size:12.5px;line-height:1.5}.cmdp .ph{display:flex;gap:10px;align-items:center}.cmdp .ph h3{margin:0}
.pra{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:10px 0}.pra .sub{margin-right:4px}td.acts{white-space:nowrap}td.acts .chip{padding:2px 9px;font-size:12px;margin-right:4px}
.droprow{border-top:1px solid var(--line);margin-top:16px;padding-top:12px;display:flex;gap:8px;justify-content:flex-end}.drop{background:none;border:1px solid var(--line);color:var(--warn);border-radius:8px;padding:5px 12px;font-size:13px;cursor:pointer}.drop:hover{border-color:var(--warn)}
dialog.cfm{max-width:420px}.cfmrow{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}.dropyes{background:var(--warn);color:#fff;border:0;border-radius:8px;padding:6px 14px;font-weight:600;cursor:pointer}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%) translateY(20px);background:var(--ink);color:var(--bg);padding:9px 16px;border-radius:999px;font-size:13.5px;opacity:0;transition:.2s;pointer-events:none;z-index:20}
#toast.show{opacity:1;transform:translateX(-50%)}
.hint{font-size:11.5px;color:var(--muted);margin-bottom:6px}
@media (max-width:600px){header,main{padding-left:16px;padding-right:16px}.board{grid-template-columns:1fr}}
</style></head><body>
<header>
 <h1>Docket</h1>
 <div class="sub">Built __BUILT__ from <code>__SOURCE__</code> · answer by number in the chief-of-staff session · local only</div>
 <div class="bar" id="types"></div>
 <div class="bar"><select id="proj"><option value="">All projects</option></select><input type="search" id="q" placeholder="Search"></div>
 <nav><button data-v="waiting" class="on">Board</button><button data-v="merges">Merges &amp; commands</button><button data-v="sessions">Sessions</button><button data-v="projects">Projects</button></nav>
</header>
<main class="wide">
 <div id="waiting"><div class="board" id="cards"></div></div>
 <div id="merges" hidden></div><div id="sessions" hidden></div><div id="projects" hidden></div>
</main>
<dialog id="dlg"><button class="close" onclick="dlg.close()">×</button><div id="dlgbody"></div></dialog>
<dialog id="cfm" class="cfm"><div id="cfmtext"></div><div class="cfmrow"><button class="chip" onclick="cfm.close()">Cancel</button><button class="dropyes" id="cfmyes">Drop</button></div></dialog>
<script>
const DATA = __DATA__;
const SERVED = location.protocol.startsWith("http");
const T = DATA.types, color = k => `var(--t-${k})`;
let state = {type:null, proj:"", q:""};
try { Object.assign(state, JSON.parse(localStorage.getItem("cos-filters")||"{}")); } catch(e) {}
if (state.type && !T.some(([k]) => k === state.type)) state.type = null;  // a saved type the board no longer has
const save = () => { try { localStorage.setItem("cos-filters", JSON.stringify(state)); } catch(e) {} };
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const all = DATA.cards;
const key = c => c.num||c.id;
function moved(){ try{ return JSON.parse(localStorage.getItem("cos-moved")||"{}"); }catch(e){ return {}; } }
function setMoved(d){ try{ localStorage.setItem("cos-moved",JSON.stringify(d)); }catch(e){} }
// A drag or tick shows at once in its target column, marked as moving, until a build puts it there.
function colOf(c){ const m=moved()[key(c)]; return m&&m.to!==c.col&&Date.now()-m.at<864e5?m.to:c.col; }
function pending(c){ return colOf(c)!==c.col; }
function prune(){ const d=moved(); let ch=false; for(const [k,m] of Object.entries(d)){ const c=all.find(x=>key(x)===k);
    if(!c||c.col===m.to||Date.now()-m.at>=864e5){ delete d[k]; ch=true; } } if(ch) setMoved(d); }
function matches(c, ignoreType){ if(!c.num&&dropped()[c.id]) return false; if(!ignoreType && state.type && c.type!==state.type) return false;
  if(state.proj && c.project!==state.proj) return false;
  if(state.q){ const t=(c.title+" "+c.summary+" "+c.call+" "+c.project+" "+(c.num||"")).toLowerCase(); if(!t.includes(state.q.toLowerCase())) return false; }
  return true; }
function renderTypes(){ const el=document.getElementById("types"); el.innerHTML="";
  const mk=(k,label)=>{ const n=all.filter(c=>(!k||c.type===k)&&colOf(c)!=="done"&&matches(c,true)).length; const b=document.createElement("button");
    b.className="chip"+(state.type===k?" on":""); b.innerHTML=(k?`<span class="dot" style="background:${color(k)}"></span>`:"")+esc(label)+` <span class="n">${n}</span>`;
    b.onclick=()=>{state.type=k; save(); render();}; el.appendChild(b); };
  mk(null,"All"); T.forEach(([k,l])=>mk(k,l)); }
const COLS = DATA.columns, COLNAME = Object.fromEntries(COLS);
function renderCards(){ const el=document.getElementById("cards"); const list=all.filter(c=>matches(c));
  el.innerHTML=COLS.map(([k,label])=>{ const cs=list.filter(c=>colOf(c)===k);
    const qs=cs.filter(c=>c.num), its=cs.filter(c=>!c.num); let body;
    if(!cs.length) body=`<div class="colempty">${k==="done"?"Nothing closed this week":"Nothing here"}</div>`;
    else if(k==="you") body=(qs.length?`<div class="sublbl">Decisions · highest rank first</div>`+qs.map(card).join(""):"")+(its.length?`<div class="sublbl">To-dos</div>`+its.map(card).join(""):"");
    else body=cs.map(card).join("");
    return `<section class="col" data-col="${k}"><div class="colh"><span>${esc(label)}</span><span class="count">${cs.length}</span></div><div class="cards" data-col="${k}">${body}</div></section>`; }).join("");
  el.querySelectorAll(".card").forEach(d=>{ const c=all.find(x=>x.id===d.dataset.id);
    d.onclick=()=>open(c);
    d.ondragstart=e=>{ e.dataTransfer.setData("text/plain",c.id); e.dataTransfer.effectAllowed="move"; d.classList.add("dragging"); dragging=true; };
    d.ondragend=()=>{ d.classList.remove("dragging"); dragging=false; if(stale){ stale=false; render(); } };
    const tk=d.querySelector(".tick:not(.on)"); if(tk) tk.onclick=e=>{ e.stopPropagation(); moveTo(c,"done"); }; });
  el.querySelectorAll(".cards").forEach(z=>{
    z.ondragover=e=>{ e.preventDefault(); z.classList.add("over"); };
    z.ondragleave=e=>{ if(!z.contains(e.relatedTarget)) z.classList.remove("over"); };
    z.ondrop=e=>{ e.preventDefault(); z.classList.remove("over"); const c=all.find(x=>x.id===e.dataTransfer.getData("text/plain")); if(c) moveTo(c,z.dataset.col); }; }); }
// A move sends one inbox entry: `move` to you/others/someday, `done` for a to-do, `drop` for a question.
async function moveTo(c,to){ if(!SERVED){ toast("Start the Docket server to move cards"); return; }
  const from=colOf(c); if(to===from) return;
  if(c.col==="done"&&c.num){ toast("An answered question can't be reopened here. Ask in chat."); return; }
  if(to==="done"&&c.num) return confirmDrop(c);
  const body=to==="done"?{num:"item",item:c.title.slice(0,300),action:"done"}:{num:c.num||"item",item:c.num?"":c.title.slice(0,300),action:"move",to};
  try{ const r=await post(body); if(!r.ok){ toast("Not moved ("+r.status+")"); return; }
    markMoved(c,to); if(dlg.open) dlg.close();
    toast(to==="done"?`Marked done. Chief-of-staff will move it to Done.`:`Moved to ${esc(COLNAME[to])}. Chief-of-staff will file it.`); render();
  }catch(e){ toast("Server not reachable"); } }
function markMoved(c,to){ const d=moved(); d[key(c)]={to,at:Date.now()}; setMoved(d); }
function card(c){ const col=colOf(c), pend=pending(c), drag=SERVED&&!(c.num&&c.col==="done");
  return `<div class="card${col==="done"?" closed":""}${pend?" pending":""}" style="--c:${color(c.type)}" data-id="${c.id}" draggable="${drag}">
   ${c.num?"":`<button class="tick${col==="done"?" on":""}" title="${col==="done"?"Done":"Mark done"}" aria-label="Mark done"></button>`}<div class="cb">
   <div class="meta"><span class="dot" style="background:${color(c.type)}"></span>${esc(DATA.typeLabel[c.type])}${c.project?" · "+esc(c.project):""}${c.num?` · <span class="num">#${c.num}</span>`:""}${pend?` · <span class="movb">moving</span>`:sent()[key(c)]?` · <span class="sentb">sent</span>`:""}${c.done&&col==="done"?` · ${esc(c.done)}`:""}</div>
   <div class="title">${c.titleHtml}</div>
   ${c.parts&&c.parts.why&&col!=="done"?`<div class="why">${c.parts.why}</div>`:""}
   ${c.lean&&col!=="done"?`<div class="lean"><span class="lk">Lean</span> (${esc(c.lean)}) ${esc(c.leanLabel||"")}</div>`:""}</div></div>`; }
function open(c){ document.getElementById("dlgbody").innerHTML=`<div class="meta"><span class="dot" style="background:${color(c.type)}"></span>${esc(DATA.typeLabel[c.type])}${c.project?" · "+esc(c.project):""}${c.num?" · #"+esc(c.num):""}</div>
  <h2>${c.num?"#"+c.num+" ":""}${c.titleHtml}</h2>${c.col==="done"?(c.num?c.body:detail(c)):detail(c)+prActions(c.prs)+answerForm(c)+more(c)}${moveRow(c)}${SERVED&&c.col!=="done"?`<div class="droprow">${c.num?"":`<button class="chip" id="rfbtn">↻ Refresh status</button>`}<button class="drop" id="dropbtn">Drop this ${c.num?"question":"item"}</button></div>`:""}`; dlg.showModal(); if(c.col!=="done"){ wireForm(c); wireDrop(c); } wirePr(document.getElementById("dlgbody"));
  document.querySelectorAll(".mv").forEach(b=>b.onclick=()=>moveTo(c,b.dataset.to));
  const rb=document.getElementById("rfbtn"); if(rb) rb.onclick=()=>{ rb.disabled=true; rb.textContent="↻ Asked"; refresh("item",c.title,"i:"+c.title); dlg.close(); }; }
function moveRow(c){ if(!SERVED||(c.num&&c.col==="done")) return ""; const cur=colOf(c);
  return `<div class="moverow"><span class="sub">Move to</span>${COLS.filter(([k])=>!(k==="done"&&c.num)).map(([k,l])=>`<button class="chip mv${k===cur?" on":""}" data-to="${k}"${k===cur?" disabled":""}>${k==="done"?"✓ Done":esc(l)}</button>`).join("")}</div>`; }
function confirmDrop(c){ document.getElementById("cfmtext").innerHTML=`Drop ${c.num?"#"+esc(c.num)+" ":""}<strong>${c.titleHtml}</strong>?<br><span class="sub">It moves to Answered as dropped. Nothing is deleted, and chief-of-staff can bring it back.</span>`;
  document.getElementById("cfmyes").onclick=async()=>{ cfm.close();
    try{ const r=await post({num:c.num||"item",item:c.num?"":c.title.slice(0,300),action:"drop"});
      if(!r.ok){ toast("Not dropped ("+r.status+")"); return; }
      if(c.num) markMoved(c,"done"); else { const d=JSON.parse(localStorage.getItem("cos-dropped")||"{}"); d[c.id]=DATA.built; try{localStorage.setItem("cos-dropped",JSON.stringify(d));}catch(e){} }
      if(dlg.open) dlg.close(); toast(`Dropped${c.num?" #"+esc(c.num):""}. Chief-of-staff will move it to Answered.`); render();
    }catch(e){ toast("Server not reachable"); } };
  cfm.showModal(); }
function wireDrop(c){ const b=document.getElementById("dropbtn"); if(b) b.onclick=()=>confirmDrop(c); }
function dropped(){ try{ const d=JSON.parse(localStorage.getItem("cos-dropped")||"{}"); return Object.fromEntries(Object.entries(d).filter(([k,v])=>v===DATA.built)); }catch(e){ return {}; } }
function detail(c){ const p=c.parts||{}; let h="";
  if(p.why) h+=`<p class="lead">${p.why}</p>`;
  if(p.ask) h+=`<div class="askbox"><div class="lbl">Your call</div><div>${p.ask}</div>${c.lean?`<div class="leanline"><span class="lk">Lean</span> <strong>(${esc(c.lean)}) ${esc(c.leanLabel||"")}</strong>${p.leanWhy?` — ${p.leanWhy}`:""}</div>`:""}</div>`;
  return h; }
function more(c){ const p=c.parts||{}; if(!c.num) return "";
  let h="";
  if(p.options&&!(c.options||[]).length) h+=`<h4>Options</h4><div class="opts-detail">${p.options}</div>`;
  const kv=[["Rank",p.rank],["For",p.for],["Asked by",p.askedBy]].filter(x=>x[1]);
  if(kv.length) h+=`<dl class="kv">${kv.map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
  if(p.facts) h+=`<h4>Facts</h4>${p.facts}`;
  if(p.refs) h+=`<div class="refs"><span class="lk">Refs</span> ${p.refs}</div>`;
  return h; }
function answerForm(c){ if(!SERVED) return `<p class="sub">Start the Docket server to answer here, or answer in chat.</p>`;
  if(!c.num) return `<div class="notebar"><button class="chip" id="notetoggle">Add a note for chief-of-staff</button></div><div class="ans" id="notebox" hidden><textarea id="anstext" rows="2" placeholder="A note or instruction about this item"></textarea><div class="row"><button class="send" id="anssend">Send note</button><span class="sub" id="ansmsg"></span></div></div>`;
  const opts=[...(c.options||[])].sort((a,b)=>(b.key===c.lean)-(a.key===c.lean));
  return `<div class="ans">${(c.options||[]).length?`<div class="hint">Click an option to send it</div>`:""}<div class="opts">${opts.map(o=>`<button class="opt${o.key===c.lean?" rec":""}" data-k="${o.key}"><span class="ol">(${o.key}) ${esc(o.label)}${o.key===c.lean?` <span class="lk">Lean</span>`:""}</span>${o.detailHtml?`<span class="od">${o.detailHtml}</span>`:""}</button>`).join("")}</div>
  <textarea id="anstext" rows="2" placeholder="${c.num?"Optional: add a comment first, then click an option, or write your own answer and Send":"A note or instruction about this item"}"></textarea>
  <div class="row"><button class="send" id="anssend">${c.num?"Send my own answer":"Send note"}</button><span class="sub" id="ansmsg"></span></div></div>`; }
function wireForm(c){ if(!SERVED) return;
  const tg=document.getElementById("notetoggle"); if(tg) tg.onclick=()=>{ document.getElementById("notebox").hidden=false; tg.parentNode.hidden=true; document.getElementById("anstext").focus(); };
  const msg=document.getElementById("ansmsg"), box=document.getElementById("anstext");
  async function send(pick){ const text=box.value.trim();
    if(!pick&&!text){msg.textContent="Pick an option or write an answer.";return;}
    document.querySelectorAll(".opt").forEach(x=>x.classList.toggle("on",x.dataset.k===pick));
    msg.textContent="Sending…";
    try{ const r=await fetch("/answer",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:DATA.token,num:c.num||"item",item:c.num?"":c.title.slice(0,300),choice:pick,text})});
      if(!r.ok){msg.textContent="Not sent ("+r.status+").";return;}
      toast(`Sent${c.num?" #"+esc(c.num):""}${pick?" <strong>("+esc(pick)+")</strong>":""}. Chief-of-staff will confirm it in chat.`);
      dlg.close();
      const k="cos-sent"; let s={}; try{s=JSON.parse(localStorage.getItem(k)||"{}");}catch(e){} s[c.num||c.id]=(pick?"("+pick+") ":"")+text; try{localStorage.setItem(k,JSON.stringify(s));}catch(e){} render();
    }catch(e){ msg.textContent="Server not reachable: "+e; } }
  document.querySelectorAll(".opt").forEach(b=>b.onclick=()=>send(b.dataset.k));
  document.getElementById("anssend").onclick=()=>send(null); }
function toast(html){ let t=document.getElementById("toast"); if(!t){t=document.createElement("div");t.id="toast";document.body.appendChild(t);}
  t.innerHTML=html; t.classList.add("show"); clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("show"),3500); }
async function post(body){ return fetch("/answer",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:DATA.token,choice:null,text:"",...body})}); }
async function refresh(kind,name,key){ try{ const r=await post({num:kind,item:name.slice(0,300),action:"refresh"});
  if(!r.ok){ toast("Not sent ("+r.status+")"); return; } let d={}; try{d=JSON.parse(localStorage.getItem("cos-refresh")||"{}");}catch(e){} d[key]=Date.now(); try{localStorage.setItem("cos-refresh",JSON.stringify(d));}catch(e){}
  toast("Asked chief-of-staff to refresh “"+esc(name.slice(0,60))+"”. The page reloads when it's done."); }catch(e){ toast("Server not reachable"); } }
function link(pr){ const [r,n]=pr.split(" #"); return `<a href="https://github.com/${DATA.org}/${esc(r)}/pull/${esc(n)}" target="_blank" rel="noopener">${esc(pr)}</a>`; }
function prActions(prs){ if(!SERVED||!prs||!prs.length) return "";
  return prs.map(pr=>`<div class="pra"><span class="sub">${esc(pr)}</span><button class="chip pa" data-a="merge" data-pr="${esc(pr)}">Merge</button><button class="chip pa" data-a="review" data-pr="${esc(pr)}">Review</button><button class="chip pa" data-a="discuss" data-pr="${esc(pr)}">Discuss</button></div>`).join(""); }
function wirePr(root){ root.querySelectorAll(".pa").forEach(b=>b.onclick=async()=>{ const a=b.dataset.a, pr=b.dataset.pr; b.disabled=true;
  try{ const r=await post({num:"pr",item:pr,action:a}); const what={merge:"check it and ask you in chat for the final word",review:"run an independent review",discuss:"bring it up in chat"}[a];
    toast(r.ok?`Sent: ${esc(pr)}. Chief-of-staff will ${what}.`:"Not sent ("+r.status+")"); if(r.ok&&dlg.open) dlg.close(); }catch(e){ toast("Server not reachable"); } }); }
function sent(){ try{return JSON.parse(localStorage.getItem("cos-sent")||"{}");}catch(e){return {};} }
// Redrawing the board mid-drag would remove the card being dragged, so a render waits for the drop.
let dragging=false, stale=false;
function render(){ if(dragging){ stale=true; return; } prune(); renderTypes(); renderCards(); }
const projs=[...new Set(all.map(c=>c.project).filter(Boolean))].sort();
const sel=document.getElementById("proj"); projs.forEach(p=>{const o=document.createElement("option");o.value=o.textContent=p;sel.appendChild(o);});
sel.value=state.proj; sel.onchange=()=>{state.proj=sel.value; save(); render();};
const qi=document.getElementById("q"); qi.value=state.q; qi.oninput=()=>{state.q=qi.value; save(); render();};
// merges & commands
(function(){ const m=DATA.merges; let h=`<section class="panel"><h3>PRs ready to merge</h3>`;
  if(m.rows.length){ h+=`<table><tr>${m.head.map(x=>`<th>${esc(x)}</th>`).join("")}${SERVED?"<th></th>":""}</tr>`+m.rows.map((r,ri)=>`<tr>${r.map((x,i)=>{const bad=/^(missing|none|no ci|fail)/i.test(x)&&/(Checks|Verified|Reviewed)/.test(m.head[i]||""); return `<td class="${bad?"bad":""}">${i===0&&m.prs[ri]?link(m.prs[ri]):esc(x)}</td>`;}).join("")}${SERVED&&m.prs[ri]?`<td class="acts">${["merge","review","discuss"].map(a=>`<button class="chip pa" data-a="${a}" data-pr="${esc(m.prs[ri])}">${a[0].toUpperCase()+a.slice(1)}</button>`).join("")}</td>`:""}</tr>`).join("")+`</table>`; }
  else h+=`<div class="empty">No PRs waiting.</div>`;
  h+=`</section>`+DATA.commands.map((c,i)=>`<section class="panel cmdp"><div class="ph"><h3>${esc(c.title)}</h3>${c.deletes?`<span class="pill block">Deletes data</span>`:""}</div>${c.body}
    ${c.cmd?`<pre class="cmd"><code>${esc(c.cmd)}</code></pre><div class="row"><button class="chip cp" data-i="${i}">Copy</button>${SERVED?`<button class="chip dn" data-i="${i}">Done — check it</button>`:""}<span class="sub">Paste it into the chief-of-staff session; the <code>!</code> runs it there.</span></div>`:""}
    ${c.expect?`<p class="sub"><strong>Expect:</strong> ${c.expect}</p>`:""}</section>`).join("");
  document.getElementById("merges").innerHTML=h; wirePr(document.getElementById("merges"));
  document.querySelectorAll(".cp").forEach(b=>b.onclick=async()=>{ const c=DATA.commands[+b.dataset.i];
    try{ await navigator.clipboard.writeText(c.cmd); toast("Copied "+esc(c.id)+". Paste it into the chief-of-staff session."); }catch(e){ toast("Couldn't copy: select the command instead"); } });
  document.querySelectorAll(".dn").forEach(b=>b.onclick=async()=>{ const c=DATA.commands[+b.dataset.i]; b.disabled=true;
    try{ const r=await post({num:"item",item:c.id+" "+c.title.slice(0,200),text:"done, check it",action:"refresh"}); toast(r.ok?"Asked chief-of-staff to check "+esc(c.id)+".":"Not sent ("+r.status+")"); }catch(e){ toast("Server not reachable"); } }); })();
// sessions
document.getElementById("sessions").innerHTML=`<section class="panel"><h3>Live sessions (${DATA.sessions.length})</h3>`+
  (DATA.sessions.map(s=>`<div class="sess"><span class="st ${esc(s.status)}">${esc(s.status)}</span><strong>${esc(s.name)}</strong><span class="sub">${esc(s.kind)} · ${esc(s.cwd)}</span>${SERVED&&DATA.attach&&s.sessionId&&s.name!=="chief-of-staff"?`<button class="attach" data-sid="${esc(s.sessionId)}">${s.kind==="background"?"Attach in Terminal":"Show its window"}</button>`:""}</div>`).join("")||`<div class="empty">None found.</div>`)+`</section>`;
document.querySelectorAll(".attach").forEach(b=>b.onclick=async()=>{ b.disabled=true;
  try{ const r=await fetch("/attach",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:DATA.token,sessionId:b.dataset.sid})});
    toast(r.ok?"Opening in Terminal…":"Couldn't attach: "+(await r.text())); }catch(e){ toast("Server not reachable"); }
  setTimeout(()=>b.disabled=false,1500); });
// projects
function pill(st){ const t=(st||"").toLowerCase(); const k=t.startsWith("waiting")?"wait":t.startsWith("blocked")?"block":t.startsWith("in progress")||t.startsWith("moving")?"move":"quiet";
  return st?`<span class="pill ${k}">${esc(st)}</span>`:""; }
document.getElementById("projects").innerHTML=DATA.projects.map(p=>{ const n=all.filter(c=>c.project&&colOf(c)==="you"&&(c.project===p.name||p.name.startsWith(c.project)||c.project.startsWith(p.name))).length;
  const lead=p.lead.length?p.lead.map(l=>`<div class="pl"><span class="lk">${esc(l.label)}</span> ${l.html}</div>`).join(""):"";
  return `<section class="panel proj"><div class="ph"><h3>${esc(p.title)}</h3>${pill(p.status)}${n?`<button class="chip pw" data-p="${esc(p.name)}">${n} waiting on you</button>`:""}${SERVED?`<button class="chip rf" data-p="${esc(p.title)}">↻ Refresh status</button>`:""}</div>
   ${lead||(p.ref.length?"":p.body)}${p.ref.length?`<details><summary>Reference (${p.ref.length})</summary><ul>${p.ref.map(r=>`<li>${r}</li>`).join("")}</ul></details>`:""}</section>`; }).join("");
document.querySelectorAll(".rf").forEach(b=>b.onclick=()=>{ b.disabled=true; b.textContent="↻ Asked"; refresh("project",b.dataset.p,"p:"+b.dataset.p); });
document.querySelectorAll(".pw").forEach(b=>b.onclick=()=>{ const name=b.dataset.p; const proj=projs.find(x=>x===name||name.startsWith(x)||x.startsWith(name))||"";
  state.proj=proj; state.type=null; save(); sel.value=proj; render(); document.querySelector('nav button[data-v="waiting"]').click(); });
// tabs
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{ document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("on",x===b));
  ["waiting","merges","sessions","projects"].forEach(v=>document.getElementById(v).hidden=v!==b.dataset.v); });
document.addEventListener("keydown",e=>{ if(e.key==="/"&&document.activeElement!==qi){e.preventDefault();qi.focus();} });
render();
if(SERVED){ let v=null; setInterval(async()=>{ try{ const t=await (await fetch("/version",{cache:"no-store"})).text();
  if(v&&t!==v){ if(!dlg.open&&!dragging&&!(document.getElementById("cfm")||{}).open&&document.activeElement!==qi) location.reload(); else toast("Updated. It reloads when you close this."); }
  v=v||t; if(v!==t&&!dlg.open) v=t; }catch(e){} }, 5000); }
</script></body></html>
"""


def main() -> int:
    text = SOURCE.read_text()
    secs = sections(text)
    ids: set = set()
    since = (dt.date.today() - dt.timedelta(days=DONE_DAYS)).isoformat()
    set_types(secs.get("By work type", ""))
    done = parse_column(secs.get("Done", ""), "done", ids, since) + parse_questions(secs.get("Answered", ""), "done", since)
    cards = (parse_questions(secs.get("Open, by rank", "")) + parse_work_types(secs.get("By work type", ""), ids)
             + parse_column(secs.get("Waiting on others", ""), "others", ids)
             + parse_column(secs.get("Someday", ""), "someday", ids)
             + sorted(done, key=lambda c: c["done"], reverse=True))
    for c in cards:
        text = " ".join([c.get("title", ""), c.get("summary", ""), c.get("call", "")])
        c["prs"] = list(dict.fromkeys(f"{r} #{n}" for r, n in re.findall(r"(?<![/\w-])([a-z0-9][a-z0-9-]+)\s#(\d+)\b", text) if r in REPOS))
        c["callHtml"] = inline(c["call"]) if c["call"] else ""
        c["titleHtml"] = inline(c["title"])
    head, rows = parse_table(secs.get("PRs ready to merge", ""))
    prrefs = [(re.match(r"([a-z0-9-]+)\s#(\d+)", r[0]) if r else None) for r in rows]
    prrefs = [f"{m.group(1)} #{m.group(2)}" if m and m.group(1) in REPOS else "" for m in prrefs]
    data = {
        "types": TYPES, "typeLabel": TYPE_LABEL, "cards": cards, "columns": COLUMNS,
        "merges": {"head": head, "rows": rows, "prs": prrefs}, "org": ORG,
        "attach": sys.platform == "darwin",  # Attach drives Terminal.app; server.py refuses it elsewhere
        "commands": parse_commands(secs.get("Commands for you to run", "")),
        "sessions": live_sessions(),
        "projects": parse_projects(secs.get("Where things stand", "")),
    }
    built = dt.datetime.now().strftime("%a %b %-d, %-I:%M %p")
    tok_file = HERE / ".token"
    if not tok_file.exists():
        import secrets
        tok_file.write_text(secrets.token_hex(16))
        tok_file.chmod(0o600)
    data["token"] = tok_file.read_text().strip()
    data["built"] = built
    page = PAGE.replace("__TYPECSS_LIGHT__", type_css(False)).replace("__TYPECSS_DARK__", type_css(True))
    page = page.replace("__DATA__", json.dumps(data).replace("</", "<\\/")).replace("__BUILT__", built).replace("__SOURCE__", html.escape(str(SOURCE).replace(str(Path.home()), "~")))
    OUT.write_text(page)
    print(f"Wrote {OUT} ({len(cards)} cards, {len(rows)} PRs, {len(data['sessions'])} live sessions)")
    if "--open" in sys.argv:
        open_page(f"http://127.0.0.1:{os.environ.get('COS_DOCKET_PORT', '8765')}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
