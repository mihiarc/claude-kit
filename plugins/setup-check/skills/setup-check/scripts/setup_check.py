#!/usr/bin/env python3
"""Setup check: whether this machine's Claude Code setup has fallen behind or drifted.

    setup_check.py [report] [--offline] [--json]   look up the latest versions, compare, print the report
    setup_check.py refresh                         the same lookup, writing only the snapshot (no output)
    setup_check.py hook                            SessionStart hook: one warning line, or nothing

Versions: the Claude Code CLI against the npm registry (on the auto-update channel the settings
name), each installed plugin against the local copy of its marketplace, and the kit itself (the
kit commit the installed settings were built from, the kit checkout and its origin). Drift: what
~/.claude holds that neither the kit nor the personal layer does, with secrets redacted.

It only reports: it never runs `claude update`, `/plugin update`, `git pull` or the installer.
The last run is kept in ~/.claude/setup-check/snapshot.json, so the next report can say what
changed. The hook never touches the network: it re-reads the cheap local facts against the
snapshot's latest versions, and starts a detached refresh when the snapshot is over a day old.
Plain code, standard library only; runs on the python3 that ships with macOS (3.9).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

DIST_TAGS_URL = "https://registry.npmjs.org/-/package/@anthropic-ai/claude-code/dist-tags"
STAMP = "kit-install.json"          # written by the kit's installer in ~/.claude
STATE = "setup-check"               # folder in ~/.claude for the snapshot and its lock
IGNORE = "drift-ignore.md"          # in the personal layer
KIT_MARKETPLACE = "claude-kit"
REFRESH_AFTER = datetime.timedelta(days=1)
LOCK_STALE = datetime.timedelta(minutes=10)
NET_TIMEOUT = 8
VERSION_RE = re.compile(r"^\d+(\.\d+)+([-+.][0-9A-Za-z.-]+)?$")

# Folders where setup lives. Every entry in them should be a link into the kit or the personal layer.
SETUP_DIRS = ("skills", "agents", "hooks", "commands", "output-styles", "rules")
# Managed by Claude Code itself: the Anthropic skills it syncs from the claude.ai account.
SKIP = {"skills/synced"}
# Top-level setup files the installer doesn't write; one of them here is outside both.
UNMANAGED_FILES = ("settings.local.json", "keybindings.json")
# The default marketplace and the kit's own; others are drift unless the rendered settings name them.
MARKETPLACES = ("claude-plugins-official", KIT_MARKETPLACE)
LIST_ITEM_CHARS = 160
# Secrets that could sit in a hook command or a permission rule. Each match is replaced by "…".
SECRET_RES = [
    re.compile(r"(?i)\b(bearer|basic|token|authorization|password|passwd|secret|api[_-]?key)(\s*[:=]?\s*)[^\s'\",)]+"),
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=[^\s'\",)]+"),           # NAME=value
    re.compile(r"\b(?:gh[pousr]_|github_pat_|sk-|xox[abpr]-|AKIA)[A-Za-z0-9_-]+"),
    # A long opaque string with both letters and digits (a token or key, not a tool name like mcp__x__y).
    re.compile(r"(?=[A-Za-z0-9_+/=-]*\d)(?=[A-Za-z0-9_+/=-]*[A-Za-z])[A-Za-z0-9_+/=-]{20,}"),
]


# ---------------------------------------------------------------- small helpers

def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def load(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def git(repo, *args, timeout=10):
    """stdout of a git command in repo, stripped, or None when it fails."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def vkey(v: str):
    """A version as a tuple to order by, or None when it isn't dotted numbers."""
    m = re.match(r"^(\d+(?:\.\d+)*)", v or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def older(installed, latest) -> bool | None:
    """True when installed is behind latest, False when not, None when they can't be compared."""
    if not installed or not latest:
        return None
    a, b = vkey(installed), vkey(latest)
    if a is None or b is None:
        return installed != latest
    return a < b


def short(sha) -> str:
    return (sha or "?")[:7]


def when(iso) -> str:
    try:
        return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except (AttributeError, ValueError):
        return "an unknown time"


def redact(s: str) -> str:
    s = SECRET_RES[0].sub(lambda m: m.group(1) + m.group(2) + "…", s)
    s = SECRET_RES[1].sub(lambda m: m.group(1) + "=…", s)
    for r in SECRET_RES[2:]:
        s = r.sub("…", s)
    return s


def tilde(p) -> str:
    s, h = str(p), str(home())
    return "~" + s[len(h):] if s == h or s.startswith(h + "/") else s


# ---------------------------------------------------------------- where things are

def install_record(h: Path) -> dict:
    """The kit's install stamp, or what can be read from a CLAUDE.md written before stamps existed.
    Keys: kit, commit, dirty, profile, me (any may be None); {} when the kit wasn't installed by install.sh."""
    st = load(h / ".claude" / STAMP)
    if isinstance(st, dict) and st.get("kit"):
        return {k: st.get(k) for k in ("kit", "commit", "dirty", "profile", "me")}
    try:
        md = (h / ".claude" / "CLAUDE.md").read_text()
    except OSError:
        return {}
    m = re.search(r"^@(\S+)/starter/core\.md\s*$", md, re.M)
    if not m:
        return {}
    kit = m.group(1)
    kit = str(h) + kit[1:] if kit.startswith("~/") else kit
    me = re.search(r"^@(\S+)/CLAUDE\.md\s*$", md, re.M)
    me = me.group(1) if me else None
    me = str(h) + me[1:] if me and me.startswith("~/") else me
    return {"kit": kit, "commit": None, "dirty": None, "profile": None, "me": me, "unstamped": True}


def cli_installed(h: Path, slow_ok: bool):
    """The running or linked Claude Code version, cheapest source first."""
    for p in (os.environ.get("CLAUDE_CODE_EXECPATH"), h / ".local" / "bin" / "claude"):
        if not p:
            continue
        try:
            name = os.path.basename(os.path.realpath(str(p)))
        except OSError:
            continue
        if VERSION_RE.match(name):
            return name
    if slow_ok:
        try:
            r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=15,
                               stdin=subprocess.DEVNULL)
            m = re.search(r"\d+\.\d+\.\d+\S*", r.stdout)
            if r.returncode == 0 and m:
                return m.group(0)
        except (OSError, subprocess.SubprocessError):
            pass
    return None


# ---------------------------------------------------------------- latest versions (network)

def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "claude-kit-setup-check", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=NET_TIMEOUT) as r:  # noqa: S310 (fixed https URL, or a test's file URL)
        return json.loads(r.read().decode())


def lookup_latest(rec: dict) -> dict:
    """The network half: the CLI's npm dist-tags and the kit origin's default-branch commit.
    A failed lookup leaves its value None; nothing is ever updated."""
    out = {"cli": None, "kit_origin": None, "looked_up": now().isoformat()}
    try:
        tags = fetch_json(os.environ.get("SETUP_CHECK_DIST_TAGS_URL", DIST_TAGS_URL))
        if isinstance(tags, dict):
            out["cli"] = {k: v for k, v in tags.items() if isinstance(v, str)}
    except Exception:  # noqa: BLE001 — offline, refused, slow or malformed: all mean "unknown"
        pass
    kit = rec.get("kit")
    if kit and Path(kit).is_dir():
        line = git(kit, "ls-remote", "--symref", "origin", "HEAD", timeout=NET_TIMEOUT + 2) or ""
        m = re.search(r"^([0-9a-f]{40})\s+HEAD$", line, re.M)
        out["kit_origin"] = m.group(1) if m else None
    return out


# ---------------------------------------------------------------- rows (local, cheap)

def row(key, label, state, installed=None, latest=None, detail="", fix=""):
    return {"key": key, "label": label, "state": state, "installed": installed, "latest": latest,
            "detail": detail, "fix": fix}


def cli_rows(h: Path, latest: dict, snap_installed, slow_ok: bool) -> list:
    installed = cli_installed(h, slow_ok) or snap_installed
    settings = load(h / ".claude" / "settings.json")
    channel = settings.get("autoUpdatesChannel") if isinstance(settings, dict) else None
    channel = channel if channel in ("stable", "latest") else "latest"
    target = ((latest or {}).get("cli") or {}).get(channel)
    behind = older(installed, target)
    if installed is None:
        r = row("cli", "Claude Code", "unknown", None, target, "couldn't read the installed version")
    elif target is None:
        r = row("cli", "Claude Code", "unknown", installed, None,
                f"{installed}; the latest on the {channel} channel isn't known yet (needs the network)")
    elif behind:
        r = row("cli", "Claude Code", "behind", installed, target,
                f"{installed}, the {channel} channel has {target}", "claude update")
    else:
        r = row("cli", "Claude Code", "ok", installed, target, f"{installed}, the {channel} channel's latest")
    out = [r]
    last = load(h / ".claude" / ".last-update-result.json")
    if isinstance(last, dict) and last.get("outcome") == "failed":
        stale = last.get("version_from") and installed and last.get("version_from") != installed
        if not stale:
            why = last.get("status") or last.get("outcome")
            tail = " You're on the latest, so nothing is behind." if r["state"] == "ok" else ""
            out.append(row("cli-update", "Claude Code auto-update", "failed", installed, None,
                           f"the last auto-update, {when(last.get('timestamp'))}, failed ({why}).{tail}"))
    return out


def marketplace_version(loc: Path, name: str):
    """A plugin's version in a local marketplace copy: its marketplace entry, else its plugin.json."""
    mk = load(loc / ".claude-plugin" / "marketplace.json")
    for p in (mk or {}).get("plugins", []) if isinstance(mk, dict) else []:
        if isinstance(p, dict) and p.get("name") == name:
            if isinstance(p.get("version"), str):
                return p["version"]
            src = p.get("source")
            if isinstance(src, str) and not os.path.isabs(src):
                pj = load(loc / src / ".claude-plugin" / "plugin.json")
                if isinstance(pj, dict) and isinstance(pj.get("version"), str):
                    return pj["version"]
            return None
    return None


def plugin_rows(h: Path) -> list:
    inst = load(h / ".claude" / "plugins" / "installed_plugins.json")
    inst = inst.get("plugins", inst) if isinstance(inst, dict) else {}
    known = load(h / ".claude" / "plugins" / "known_marketplaces.json")
    known = known if isinstance(known, dict) else {}
    out = []
    for full, entries in sorted(inst.items()):
        name, _, market = full.rpartition("@")
        m = known.get(market) if isinstance(known.get(market), dict) else {}
        loc = m.get("installLocation")
        updated = when(m.get("lastUpdated")) if m.get("lastUpdated") else "an unknown time"
        latest = marketplace_version(Path(loc), name) if loc else None
        for e in entries if isinstance(entries, list) else []:
            if not isinstance(e, dict):
                continue
            scope = e.get("scope") or "user"
            where = f" ({scope}: {os.path.basename(str(e.get('projectPath', '')))})" if e.get("projectPath") else \
                (f" ({scope})" if scope != "user" else "")
            label = f"plugin {full}{where}"
            v = e.get("version") if isinstance(e.get("version"), str) else None
            if v and not VERSION_RE.match(v):
                v = None  # an unversioned plugin is recorded by commit; there's nothing to compare
            b = older(v, latest)
            if b is None:
                out.append(row("plugin:" + full + where, label, "unknown", v, latest,
                               f"{v or 'no version'}; its marketplace copy gives no version to compare"))
            elif b:
                out.append(row("plugin:" + full + where, label, "behind", v, latest,
                               f"{v}, its marketplace copy (updated {updated}) has {latest}",
                               f"/plugin update {full}"))
            else:
                out.append(row("plugin:" + full + where, label, "ok", v, latest,
                               f"{v}, as in its marketplace copy (updated {updated})"))
    return out


def kit_rows(rec: dict, latest: dict) -> list:
    if not rec:
        return []
    kit = rec["kit"]
    if not Path(kit).is_dir():
        return [row("kit", "claude-kit", "unknown", detail=f"the kit folder {tilde(kit)} named at install is gone")]
    head = git(kit, "rev-parse", "HEAD")
    out = []
    reinstall = f"{tilde(kit)}/install.sh" + (f" --profile {tilde(rec['profile'])}" if rec.get("profile") else "")
    if rec.get("unstamped"):
        out.append(row("kit", "claude-kit", "unknown", None, head,
                       "installed before install.sh recorded its commit, so the settings' kit version isn't known",
                       reinstall))
    elif head is None:
        out.append(row("kit", "claude-kit", "unknown", rec.get("commit"), None,
                       f"{tilde(kit)} isn't a git checkout, so its version can't be compared"))
    elif rec.get("commit") and rec["commit"] != head:
        n = git(kit, "rev-list", "--count", f"{rec['commit']}..{head}")
        ahead = f"{n} commit{'s' if n != '1' else ''}" if n and n != "0" else "a different commit"
        out.append(row("kit", "claude-kit", "behind", rec["commit"], head,
                       f"settings built from {short(rec['commit'])}; the kit checkout is {ahead} ahead, at {short(head)}",
                       reinstall))
    else:
        dirty = " (from uncommitted changes)" if rec.get("dirty") else ""
        out.append(row("kit", "claude-kit", "ok", rec.get("commit"), head,
                       f"settings built from the checkout's commit, {short(head)}{dirty}"))
    origin = (latest or {}).get("kit_origin")
    if head and origin and origin != head:
        if git(kit, "merge-base", "--is-ancestor", origin, head) is None:
            n = git(kit, "rev-list", "--count", f"{head}..{origin}")
            gap = f"{n} commit{'s' if n != '1' else ''}" if n else "commits"
            out.append(row("kit-origin", "claude-kit origin", "behind", head, origin,
                           f"origin's default branch has {gap} this checkout doesn't",
                           f"git -C {tilde(kit)} pull, then {reinstall}"))
    return out


def version_rows(h: Path, rec: dict, latest: dict, snap: dict | None, slow_ok: bool) -> list:
    snap_cli = next((r.get("installed") for r in (snap or {}).get("rows", []) if r.get("key") == "cli"), None)
    return cli_rows(h, latest, snap_cli, slow_ok) + plugin_rows(h) + kit_rows(rec, latest)


# ---------------------------------------------------------------- drift (local, slower)

def _tracked(repo: str, cache: dict) -> set:
    """Every path git tracks on the repo's main lines (HEAD, main, origin's), with its folders."""
    if repo not in cache:
        paths = set()
        for ref in ("HEAD", "main", "master", "origin/HEAD", "origin/main"):
            out = git(repo, "ls-tree", "-r", "--name-only", "-z", ref)
            for f in (out or "").split("\0"):
                while f:
                    paths.add(f)
                    f = os.path.dirname(f)
        cache[repo] = paths
    return cache[repo]


def held(target: str, roots: list, cache: dict) -> bool:
    """True when target is a file or folder a root holds: tracked by git when the root is a repo,
    anything under it when it isn't. A link into an untracked folder of a checkout is not held."""
    for r, is_repo in roots:
        if target == r or target.startswith(r + os.sep):
            if not is_repo or os.path.relpath(target, r) in _tracked(r, cache):
                return True
    return False


def roots_of(rec: dict) -> list:
    """(path, is_repo) for the kit and for the personal layer's repo, or the layer itself outside a repo."""
    out = []
    for p in (rec.get("kit"), rec.get("me")):
        if not p or not Path(p).is_dir():
            continue
        top = git(p, "rev-parse", "--show-toplevel")
        root = (os.path.realpath(top), True) if top else (os.path.realpath(p), False)
        if root not in out:
            out.append(root)
    return out


def _short(x) -> str:
    """A list entry's shape: a string with its values redacted, or a dict's keys and its matcher."""
    if isinstance(x, dict):
        m = f", matcher {redact(str(x['matcher']))}" if isinstance(x.get("matcher"), str) else ""
        s = "an entry with keys " + ", ".join(sorted(map(str, x))) + m
    else:
        s = redact(x if isinstance(x, str) else json.dumps(x, sort_keys=True))
    s = " ".join(s.split())
    return s if len(s) <= LIST_ITEM_CHARS else s[:LIST_ITEM_CHARS - 1] + "…"


def link_items(h: Path, roots: list) -> list:
    """Entries in the setup folders, and a ~/.claude/statusline.sh, that aren't links into a root."""
    out, cache = [], {}
    claude = h / ".claude"
    sl = claude / "statusline.sh"
    entries = [sl] if sl.is_symlink() or sl.exists() else []
    for d in SETUP_DIRS:
        if (claude / d).is_dir():
            entries += sorted(p for p in (claude / d).iterdir() if not p.name.startswith("."))
    for p in entries:
        rel = str(p.relative_to(claude))
        if rel in SKIP:
            continue
        if not p.is_symlink():
            out.append(f"{rel}: a {'folder' if p.is_dir() else 'file'} here, not a link into the kit or your personal layer")
        elif not p.exists():
            out.append(f"{rel}: a broken link")
        elif not held(os.path.realpath(p), roots, cache):
            out.append(f"{rel}: a link to something the kit and your personal layer don't track")
    return out


def settings_items(live, tmpl, path: str = "") -> list:
    """Keys and list entries in the live settings that the rendered settings don't hold. Values are never
    printed (env may hold a token): only key paths, and list entries by their shape with anything
    that looks like a value or a secret redacted."""
    out = []
    for k in sorted(live):
        p = f"{path}.{k}" if path else k
        if k not in tmpl:
            out.append(f"settings.json: {p} is set here, not in what the kit renders")
        elif live[k] == tmpl[k]:
            continue
        elif isinstance(live[k], dict) and isinstance(tmpl[k], dict):
            out += settings_items(live[k], tmpl[k], p)
        elif isinstance(live[k], list) and isinstance(tmpl[k], list):
            extra = [x for x in live[k] if x not in tmpl[k]]
            out += [f"settings.json: {p} has {_short(x)}, which the kit's render doesn't" for x in extra]
            if not extra:
                out.append(f"settings.json: {p} differs from what the kit renders (order or missing entries)")
        else:
            out.append(f"settings.json: {p} differs from what the kit renders")
    return out


def rendered(h: Path, rec: dict):
    """The CLAUDE.md text and parsed settings.json the kit's installer would write for this HOME
    from the profile it was installed with, by its own `render`; (None, None) when it can't."""
    inst = Path(rec.get("kit") or "/nonexistent") / "installer" / "kit_install.py"
    if not inst.is_file() or rec.get("unstamped"):
        return None, None
    args = [sys.executable, "-I", str(inst), "render"]
    if rec.get("profile"):
        if not Path(rec["profile"]).is_file():
            return None, None
        args += ["--profile", rec["profile"]]
    env = {k: v for k, v in os.environ.items() if k not in ("GOTCHAS_FILE", "ZDOTDIR")}
    env["HOME"] = str(h)
    with tempfile.TemporaryDirectory() as d:
        try:
            r = subprocess.run(args + ["--out", d], env=env, capture_output=True, text=True, timeout=60,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None, None
        md, settings = Path(d) / "CLAUDE.md", Path(d) / "settings.json"
        if r.returncode or not md.is_file():
            return None, None
        return md.read_text(), load(settings)


def drift(h: Path, rec: dict):
    """(items, notes): one plain line per thing in ~/.claude that neither the kit nor the personal
    layer holds, and notes on what couldn't be compared. ([], [why]) when the kit wasn't installed by install.sh."""
    if not rec:
        return [], ["the kit wasn't installed with install.sh here, so there's no install to compare with"]
    claude, notes = h / ".claude", []
    out = link_items(h, roots_of(rec))

    want_md, tmpl = rendered(h, rec)
    live_md, live = claude / "CLAUDE.md", load(claude / "settings.json")
    if want_md is None:
        why = ("installed before install.sh recorded its profile" if rec.get("unstamped")
               else "the kit couldn't render them from the profile it was installed with")
        notes.append(f"CLAUDE.md and settings.json weren't compared: {why}")
    else:
        if live_md.exists() and live_md.read_text() != want_md:
            extra = [l for l in live_md.read_text().splitlines() if l.strip() and l not in want_md.splitlines()]
            out.append(f"CLAUDE.md: differs from what the kit renders ({len(extra)} lines here that it doesn't hold)")
        if isinstance(live, dict) and isinstance(tmpl, dict):
            live = dict(live)  # the kit's own plugins are held by the kit
            if isinstance(live.get("enabledPlugins"), dict):
                live["enabledPlugins"] = {k: v for k, v in live["enabledPlugins"].items()
                                          if not str(k).endswith("@" + KIT_MARKETPLACE)}
            out += settings_items(live, tmpl)
    for name in UNMANAGED_FILES:
        if (claude / name).exists():
            out.append(f"{name}: exists here; neither the kit nor your personal layer holds it")

    enabled = set((tmpl or {}).get("enabledPlugins") or {})
    inst = load(claude / "plugins" / "installed_plugins.json")
    inst = inst.get("plugins", inst) if isinstance(inst, dict) else {}
    for name, rows in sorted(inst.items()):
        user = any(isinstance(r, dict) and r.get("scope") == "user" for r in (rows if isinstance(rows, list) else []))
        if user and name.rpartition("@")[2] != KIT_MARKETPLACE and name not in enabled and tmpl is not None:
            out.append(f"plugin {_short(name)}: installed for the user; neither the kit nor your personal layer names it")
    allowed = set(MARKETPLACES) | set((tmpl or {}).get("extraKnownMarketplaces") or {})
    known = load(claude / "plugins" / "known_marketplaces.json")
    for m in sorted(known) if isinstance(known, dict) else []:
        if m not in allowed:
            out.append(f"marketplace {_short(m)}: known here; neither the kit nor your personal layer names it")
    return out, notes


def ignore_entries(text: str) -> list:
    """The `quoted` item at the start of each "- " line of the ignore list; the rest is the reason."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^- `([^`]+)`", line.strip())
        if m:
            out.append(m.group(1).strip())
    return out


def ignored(line: str, entries: list) -> bool:
    """An ignore entry names the start of a line: its path, or a settings key path."""
    return any(line == e or (line.startswith(e) and line[len(e)] in ": ") for e in entries)


def ignore_file(rec: dict):
    return Path(rec["me"]) / IGNORE if rec.get("me") else None


# ---------------------------------------------------------------- snapshot

def state_dir(h: Path) -> Path:
    return h / ".claude" / STATE


def read_snapshot(h: Path):
    s = load(state_dir(h) / "snapshot.json")
    return s if isinstance(s, dict) else None


def write_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=1)
        f.write("\n")
    os.replace(tmp, p)


def collect(h: Path, offline: bool, prev: dict | None) -> dict:
    rec = install_record(h)
    latest = (prev or {}).get("latest") or {}
    if not offline:
        fresh = lookup_latest(rec)
        # A failed lookup keeps the last known value, so being offline once doesn't hide a known gap.
        merged = {k: (fresh[k] if fresh.get(k) is not None else latest.get(k)) for k in ("cli", "kit_origin")}
        merged["looked_up"] = fresh["looked_up"] if fresh.get("cli") is not None else latest.get("looked_up")
        latest = merged
    items, notes = drift(h, rec)
    ign = ignore_file(rec)
    entries = ignore_entries(ign.read_text()) if ign and ign.is_file() else []
    shown = [redact(i) for i in items if not ignored(i, entries)]
    return {"checked_at": now().isoformat(), "latest": latest,
            "rows": version_rows(h, rec, latest, prev, slow_ok=True),
            "drift": shown, "drift_ignored": len(items) - len(shown), "drift_notes": notes,
            "ignore_file": tilde(ign) if ign else None}


def changes(prev: dict | None, cur: dict) -> list:
    if not prev:
        return []
    out, old = [], {r.get("key"): r for r in prev.get("rows", [])}
    for r in cur["rows"]:
        o = old.pop(r["key"], None)
        if o is None:
            out.append(f"new: {r['label']}: {r['detail']}")
            continue
        if o.get("installed") != r["installed"] and r["installed"]:
            a, b = o.get("installed"), r["installed"]
            fmt = short if r["key"].startswith("kit") else str
            out.append(f"{r['label']}: {fmt(a) if a else 'unknown'} → {fmt(b)}")
        elif o.get("latest") != r["latest"] and r["latest"] and o.get("latest"):
            fmt = short if r["key"].startswith("kit") else str
            what = "the kit checkout moved" if r["key"] == "kit" else "the latest moved"
            out.append(f"{r['label']}: {what} {fmt(o['latest'])} → {fmt(r['latest'])}")
        if o.get("state") != r["state"] and o.get("state") in ("behind", "failed") and r["state"] == "ok":
            out.append(f"{r['label']}: caught up")
    out += [f"gone: {o.get('label')}" for o in old.values()]
    was, now_ = set(prev.get("drift", [])), set(cur["drift"])
    out += [f"new drift: {d}" for d in cur["drift"] if d not in was]
    out += [f"drift resolved: {d}" for d in prev.get("drift", []) if d not in now_]
    return out


# ---------------------------------------------------------------- output

MARK = {"ok": "ok", "behind": "BEHIND", "failed": "FAILED", "unknown": "?"}


def report(snap: dict, prev: dict | None, offline: bool) -> str:
    lines = [f"Setup check, {when(snap['checked_at'])}"]
    looked = (snap.get("latest") or {}).get("looked_up")
    lines.append(f"Latest versions as of {when(looked)}" + (" (offline: not looked up this time)" if offline else "")
                 if looked else "Latest versions not known yet: the lookup needs the network")
    lines += ["", "Versions"]
    for r in snap["rows"]:
        lines.append(f"  {MARK.get(r['state'], r['state']):<7} {r['label']}: {r['detail']}")
    lines += ["", "Drift: what ~/.claude holds that neither the kit nor your personal layer does"]
    lines += [f"  {d}" for d in snap["drift"]] or ["  none"]
    if snap.get("drift_ignored"):
        lines.append(f"  ({snap['drift_ignored']} more left out by {snap.get('ignore_file')})")
    lines += [f"  note: {n}" for n in snap.get("drift_notes", [])]
    ch = changes(prev, snap)
    if prev:
        lines += ["", f"Since the last check, {when(prev.get('checked_at'))}"]
        lines += [f"  {c}" for c in ch] or ["  nothing changed"]
    fixes = list(dict.fromkeys(r["fix"] for r in snap["rows"] if r["state"] in ("behind", "unknown") and r["fix"]))
    if fixes:
        lines += ["", "To catch up (this check changes nothing itself):"] + [f"  {f}" for f in fixes]
    return "\n".join(lines) + "\n"


def warning(rows: list, drift_count: int) -> str | None:
    """The hook's one line, or None when nothing is behind and nothing has drifted."""
    behind = {r["key"]: r for r in rows if r["state"] == "behind"}
    parts = []
    if "cli" in behind:
        parts.append(f"Claude Code {behind['cli']['installed']} is behind {behind['cli']['latest']}")
    n = sum(1 for k in behind if k.startswith("plugin:"))
    if n:
        parts.append(f"{n} plugin{'s are' if n > 1 else ' is'} behind")
    if "kit" in behind:
        parts.append("the kit has moved since install.sh last ran")
    if "kit-origin" in behind:
        parts.append("the kit's origin has commits you haven't pulled")
    if drift_count:
        parts.append(f"{drift_count} setup item{'s' if drift_count > 1 else ''} outside the kit and your personal layer")
    if not parts:
        return None
    return "Setup check: " + "; ".join(parts) + "."


# ---------------------------------------------------------------- commands

def lock(h: Path) -> bool:
    """Take the refresh lock; False when another refresh holds a fresh one."""
    p = state_dir(h) / "refresh.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        age = now().timestamp() - p.stat().st_mtime
        if age < LOCK_STALE.total_seconds():
            return False
        p.unlink()
    except FileNotFoundError:
        pass
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def unlock(h: Path):
    try:
        (state_dir(h) / "refresh.lock").unlink()
    except FileNotFoundError:
        pass


def run_check(h: Path, offline: bool):
    prev = read_snapshot(h)
    snap = collect(h, offline, prev)
    write_json(state_dir(h) / "snapshot.json", snap)
    return prev, snap


def cmd_report(offline: bool, as_json: bool) -> int:
    h = home()
    prev, snap = run_check(h, offline)
    if as_json:
        print(json.dumps({"snapshot": snap, "changes": changes(prev, snap)}, indent=1))
    else:
        sys.stdout.write(report(snap, prev, offline))
    return 0


def cmd_refresh() -> int:
    h = home()
    if not lock(h):
        return 0
    try:
        run_check(h, offline=False)
    finally:
        unlock(h)
    return 0


def spawn_refresh(h: Path):
    """Start a refresh that outlives the hook, with its stdio closed so the hook returns at once."""
    p = state_dir(h) / "refresh.lock"
    try:
        if now().timestamp() - p.stat().st_mtime < LOCK_STALE.total_seconds():
            return
    except FileNotFoundError:
        pass
    if os.environ.get("SETUP_CHECK_NO_REFRESH"):
        return
    subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "refresh"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, start_new_session=True, cwd=str(h))


def details_hint(h: Path) -> str:
    if os.environ.get("CLAUDE_PLUGIN_ROOT") or (h / ".claude" / "skills" / "setup-check").exists():
        return "Run /setup-check for details."
    return f"Details: python3 -I {tilde(os.path.abspath(__file__))}"


def cmd_hook() -> int:
    h = home()
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    snap = read_snapshot(h)
    try:
        age = now() - datetime.datetime.fromisoformat(snap["checked_at"]) if snap else None
    except (KeyError, TypeError, ValueError):
        age = None
    if age is None or age > REFRESH_AFTER:
        spawn_refresh(h)
    if not snap:
        return 0
    # The hook can be wired twice (install.sh's settings and /plugin install); say it once per session.
    sid = str(data.get("session_id") or "") if isinstance(data, dict) else ""
    shown = state_dir(h) / "shown"
    if sid:
        try:
            if shown.read_text() == sid:
                return 0
        except OSError:
            pass
    rows = version_rows(h, install_record(h), snap.get("latest") or {}, snap, slow_ok=False)
    line = warning(rows, len(snap.get("drift") or []))
    if not line:
        return 0
    line = f"{line} {details_hint(h)}"
    if sid:
        try:
            shown.write_text(sid)
        except OSError:
            pass
    print(json.dumps({"systemMessage": line,
                      "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": line}}))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv and not argv[0].startswith("-") else "report"
    if cmd == "hook":
        try:
            return cmd_hook()
        except Exception:  # noqa: BLE001 — a session start must never fail on this
            return 0
    if cmd == "refresh":
        return cmd_refresh()
    if cmd == "report":
        bad = [a for a in argv if a not in ("--offline", "--json")]
        if bad:
            print(__doc__.split("\n\n")[1], file=sys.stderr)
            return 2
        return cmd_report("--offline" in argv, "--json" in argv)
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
