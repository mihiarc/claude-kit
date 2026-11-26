#!/usr/bin/env python3
"""The mechanics behind the kit-setup skill: find the kit, stage a preview, apply it.

    kit_setup.py find-kit
    kit_setup.py stage --kit K --answers A.json --personal P.md --out DIR
    kit_setup.py apply --stage DIR

`stage` writes nothing outside DIR. It builds the person's profile, settings overrides and own
CLAUDE.md in DIR, then has the kit's own installer render ~/.claude/CLAUDE.md and settings.json
from them (`kit_install.py render`) and list what an install would change (`--dry-run`).
`apply` writes the three personal-layer files, backing up any it replaces, runs the kit's
installer, then checks that the installed CLAUDE.md and settings.json equal a fresh render and
the previewed one, and that a second run would change nothing.

This script never writes ~/.claude/CLAUDE.md or settings.json itself: only the kit's installer
does, so the guided route and install.sh give the same files.

Answers (JSON): {"plugins": [names], "shell": "zsh|bash|none", "statusline": true|false,
"papercuts": "<path>" | null, "overrides": {settings the person named},
"keep": ["<dotted.path>" of a current setting the person named to keep]}. A key left out keeps
what the profile and overrides file already say.
Standard library only; runs on the python3 that ships with macOS (3.9).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = "kit-setup"
PATH_KEYS = ("kit", "me", "shell_file", "settings", "gotchas", "papercuts", "repos_dir", "repos")
CARRIED = ("enabledPlugins", "extraKnownMarketplaces")  # settings Claude Code's /plugin writes
# A setting whose value is printed in a preview: anything else that is a string is shown hidden, and
# so is anything under env or with a secret-like name, because the preview goes into a chat.
SHOWN_STRINGS = ("model", "effortLevel", "theme", "outputStyle", "defaultMode")
SECRETISH = re.compile(r"token|secret|passw|key|auth|credential|cookie|session|bearer", re.I)
TOKENISH = re.compile(r"(ghp_|gho_|ghs_|github_pat_|sk-|xox[abps]-|AKIA)[\w-]{6,}|[A-Za-z0-9+_=-]{32,}")
SHELL_LINE = re.compile(r'^source "(.+)/extras/(zsh|bash)/claude-kit\.(zsh|bash)"\s*$')


class SetupError(Exception):
    pass


def home() -> Path:
    return Path(os.environ["HOME"])


def tilde(p) -> str:
    s, h = str(p), str(home())
    return "~" + s[len(h):] if s == h or s.startswith(h + "/") else s


# ---------------------------------------------------------------- find the kit

def kit_state(path: Path) -> str:
    """`ok`, `stale` (holds this plugin but no installer: an old copy) or `no` (not this kit)."""
    if not (path / "plugins" / PLUGIN / ".claude-plugin" / "plugin.json").is_file():
        return "no"
    if not ((path / "installer" / "kit_install.py").is_file() and (path / "starter" / "core.md").is_file()):
        return "stale"
    return "ok"


def installed_kit() -> Path | None:
    """The kit an earlier install used: the profile's `kit`, or the core import in ~/.claude/CLAUDE.md."""
    prof = home() / ".claude" / "me" / "profile"
    if prof.is_file():
        m = re.search(r"^\s*kit\s*=\s*['\"]?([^'\"#\n]+?)['\"]?\s*(?:#.*)?$", prof.read_text(), re.M)
        if m:
            v = m.group(1).strip()
            p = Path(str(home()) + v[1:] if v.startswith("~/") else v)
            return p if p.is_absolute() else prof.parent / p
    md = home() / ".claude" / "CLAUDE.md"
    if md.is_file():
        m = re.search(r"^@(\S+)/starter/core\.md\s*$", md.read_text(), re.M)
        if m:
            v = m.group(1)
            return Path(str(home()) + v[1:] if v.startswith("~/") else v)
    return None


def marketplaces() -> list:
    """(name, folder) for each marketplace `claude plugin marketplace list --json` reports."""
    exe = shutil.which("claude")
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "plugin", "marketplace", "list", "--json"], capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout) if r.returncode == 0 else []
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []
    return [(m.get("name", ""), Path(m["installLocation"])) for m in data
            if isinstance(m, dict) and m.get("installLocation")]


def own_repository() -> str:
    """The kit's repository URL, from this plugin's own manifest."""
    manifest = Path(__file__).resolve().parents[3] / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text()).get("repository", "")
    except (OSError, json.JSONDecodeError):
        return ""


def find_kit() -> dict:
    """The kit to install from, in order: the kit an earlier install used, then the marketplace's
    copy that holds this plugin. A copy that holds this plugin but no installer is stale."""
    out = {"kit": None, "how": None, "stale": [], "considered": [], "repository": own_repository(),
           "claude_cli": bool(shutil.which("claude"))}
    prior = installed_kit()
    if prior is not None:
        state = kit_state(prior)
        out["considered"].append({"path": str(prior), "from": "earlier install", "state": state})
        if state == "ok":
            out.update(kit=str(prior), how="earlier install")
            return out
        out["switched_from"] = {"path": str(prior), "state": state}
    for name, loc in marketplaces():
        state = kit_state(loc)
        if state == "no":
            continue
        out["considered"].append({"path": str(loc), "from": f"marketplace {name}", "state": state})
        if state == "stale":
            out["stale"].append({"marketplace": name, "path": str(loc)})
        elif out["kit"] is None:
            out.update(kit=str(loc), how=f"marketplace {name}", marketplace=name)
    return out


# ---------------------------------------------------------------- the kit's installer

def load_installer(kit: Path):
    if kit_state(kit) != "ok":
        raise SetupError(f"{kit} is not a claude-kit checkout with an installer")
    sys.dont_write_bytecode = True  # never write __pycache__ into the kit, which may be under ~/.claude
    spec = importlib.util.spec_from_file_location("kit_install", kit / "installer" / "kit_install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_installer(kit: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", "-B", str(kit / "installer" / "kit_install.py"), *args],
                          capture_output=True, text=True)


# ---------------------------------------------------------------- profile text

def quote(v: str) -> str:
    return f'"{v}"' if "#" in v or v != v.strip() else v


def set_key(text: str, key: str, value: str | None) -> str:
    """Set key in profile text, in place of its live line or its commented-out default line;
    value None turns a live line back into a comment (the default)."""
    lines = text.splitlines()
    live = [i for i, l in enumerate(lines) if re.match(rf"\s*{key}\s*=", l)]
    if value is None:
        for i in live:
            lines[i] = "# " + lines[i].lstrip()
        return "\n".join(lines) + "\n"
    new = f"{key} = {quote(value)}"
    if live:
        lines[live[0]] = new
    else:
        dflt = [i for i, l in enumerate(lines) if re.match(rf"\s*#\s*{key}\s*=", l)]
        if dflt:
            lines[dflt[0]] = new
        else:
            lines.append(new)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- what the preview shows

def masked(path: str, value, strict: bool = True):
    """A setting's value as a preview may print it. Always hidden: anything under env, under a
    secret-like name, or that looks like a token. Strict (settings of unknown origin, such as the
    person's old file) also hides every other string but permission rules and a few plain names."""
    parts = path.replace("[]", "").split(".")
    if parts[0] == "env" or any(SECRETISH.search(x) for x in parts):
        return "<hidden>"
    if isinstance(value, (dict, list)):
        return mask_tree(value, path, strict)
    if isinstance(value, str):
        if TOKENISH.search(value) and parts[0] != "permissions":
            return "<hidden>"
        if strict and parts[0] != "permissions" and parts[-1] not in SHOWN_STRINGS:
            return "<hidden>"
    return value


def mask_tree(obj, path: str = "", strict: bool = True):
    if isinstance(obj, dict):
        return {k: masked(f"{path}.{k}" if path else k, v, strict) for k, v in obj.items()}
    if isinstance(obj, list):
        return [masked(path + "[]", v, strict) for v in obj]
    return masked(path, obj, strict)


def dropped_masked(old, new, path: str = "") -> list:
    """Every setting in old that new doesn't carry, with values masked as `masked` says."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k, v in old.items():
            p = f"{path}.{k}" if path else k
            out += dropped_masked(v, new[k], p) if k in new else [f"{p} = {json.dumps(masked(p, v))}"]
        return out
    if isinstance(old, list) and isinstance(new, list):
        return [f"{path}[] {json.dumps(masked(path + '[]', x))}" for x in old if x not in new]
    if old != new:
        return [f"{path} = {json.dumps(masked(path, old))} (now {json.dumps(masked(path, new))})"]
    return []


def fingerprint(p: Path) -> str:
    """What is at p now: absent, a file's hash, or a link and its target's hash."""
    if not os.path.lexists(p):
        return "absent"
    head = f"link {os.readlink(p)} " if p.is_symlink() else ""
    if p.is_file():
        return head + hashlib.sha256(p.read_bytes()).hexdigest()
    return head + "not a file"


def old_shell_lines(kit: Path) -> dict:
    """Lines in ~/.zshrc and ~/.bashrc that source another kit's shell file: {rc: [lines]}."""
    out = {}
    for rc in (home() / ".zshrc", home() / ".bashrc"):
        if not rc.is_file():
            continue
        stale = []
        for line in rc.read_text().splitlines():
            m = SHELL_LINE.match(line.strip())
            if not m:
                continue
            where = m.group(1).replace("$HOME", str(home())).replace("${HOME}", str(home()))
            if where.startswith("~/"):
                where = str(home()) + where[1:]
            if os.path.realpath(where) != os.path.realpath(kit):
                stale.append(line)
        if stale:
            out[str(rc)] = stale
    return out


# ---------------------------------------------------------------- stage

def stage(kit: Path, answers: dict, personal: str, out: Path) -> dict:
    ki = load_installer(kit)
    out.mkdir(parents=True, exist_ok=True)
    layer, rendered = out / "layer", out / "rendered"
    layer.mkdir(exist_ok=True)

    profile_path = home() / ".claude" / "me" / "profile"
    text = profile_path.read_text() if profile_path.is_file() else (kit / "installer" / "profile.example").read_text()
    raw = ki.parse_profile(text)
    me = ki.expand(raw.get("me", "~/.claude/me"), profile_path.parent)
    if me != profile_path.parent:
        raise SetupError(f"your profile at {tilde(profile_path)} puts the personal layer at {tilde(me)}; "
                         "kit-setup keeps the profile inside the layer, so run install.sh with that profile instead")

    if "kit" in raw and os.path.realpath(ki.expand(raw["kit"], me)) != os.path.realpath(kit):
        text = set_key(text, "kit", tilde(kit))  # find-kit said why the earlier kit is passed over
    if "plugins" in answers:
        known = ki.all_plugins()
        names = list(dict.fromkeys(answers["plugins"]))
        bad = [n for n in names if n not in known]
        if bad:
            raise SetupError(f"unknown plugin(s) {', '.join(bad)} (known: {', '.join(known)})")
        text = set_key(text, "plugins", " ".join(names))
    if "shell" in answers:
        if answers["shell"] not in ki.SHELLS:
            raise SetupError(f"shell must be one of {', '.join(ki.SHELLS)}")
        text = set_key(text, "shell", answers["shell"])
    if "papercuts" in answers:
        text = set_key(text, "papercuts", tilde(Path(os.path.expanduser(answers["papercuts"])))
                       if answers["papercuts"] else None)
    raw = ki.parse_profile(text)

    # The overrides file: the profile's own, or settings.overrides.json in the layer.
    target = ki.expand(raw["settings"], me) if "settings" in raw else me / ki.OVERRIDES
    over = {}
    if target.is_file():
        over = json.loads(target.read_text())
        if not isinstance(over, dict):
            raise SetupError(f"{tilde(target)} is not a JSON object")
    # Claude Code itself keeps the plugins the person installed with /plugin, and the marketplaces
    # they come from, in ~/.claude/settings.json, which the installer rebuilds from the base and the
    # overrides. Carry them into the overrides, or the rebuild would turn kit-setup off and drop the
    # marketplace that holds the kit. The current settings.json is the truth for these keys.
    current = {}
    settings_path = home() / ".claude" / "settings.json"
    if settings_path.is_file():  # follows a link, such as one into a dotfiles repo
        try:
            current = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            current = {}
        current = current if isinstance(current, dict) else {}
        for k in CARRIED:
            if isinstance(current.get(k), dict) and current[k]:
                over[k] = current[k]
            else:
                over.pop(k, None)
    if "statusline" in answers:
        if answers["statusline"]:
            if over.get("statusLine", 0) is None:
                del over["statusLine"]
        else:
            over["statusLine"] = None
    for path in answers.get("keep", []):
        # A setting of the current settings.json the person chose to keep, by name: copied file to
        # file, so a value the preview hides never has to pass through the chat.
        node, parts = current, path.split(".")
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                raise SetupError(f"keep: {path} is not in your current settings.json")
            node = node[part]
        extra = node
        for part in reversed(parts):
            extra = {part: extra}
        over = ki.merge(over, extra) if over else extra
    if answers.get("overrides"):
        # Only what the person named, merged by the installer's own rules (lists add up).
        if not isinstance(answers["overrides"], dict):
            raise SetupError("overrides must be a JSON object")
        over = ki.merge(over, answers["overrides"]) if over else dict(answers["overrides"])
    write_over = bool(over) or target.is_file()

    (layer / "CLAUDE.md").write_text(personal if personal.endswith("\n") else personal + "\n")
    (layer / "profile").write_text(text)
    staged_over = layer / "settings.overrides.json"
    if write_over:
        staged_over.write_text(json.dumps(over, indent=2, ensure_ascii=False) + "\n")
    elif staged_over.exists():
        staged_over.unlink()

    # The same profile with every path absolute and the overrides pointing at the staged copy, so
    # the render here equals what the installed profile renders.
    stext = text
    for k in PATH_KEYS:
        if k in raw and k != "settings":
            stext = set_key(stext, k, str(ki.expand(raw[k], me)))
    stext = set_key(stext, "me", str(me))
    stext = set_key(stext, "settings", str(staged_over) if write_over else None)
    (out / "staged-profile").write_text(stext)

    r = run_installer(kit, "render", "--profile", str(out / "staged-profile"), "--out", str(rendered))
    if r.returncode != 0:
        raise SetupError("the kit's installer refused these answers: " + (r.stderr or r.stdout).strip())
    dry = run_installer(kit, "install", "--dry-run", "--skip-repos", "--profile", str(out / "staged-profile"))
    if dry.returncode != 0:
        raise SetupError("the kit's installer refused these answers: " + (dry.stderr or dry.stdout).strip())

    old_lines = old_shell_lines(kit)
    pairs = [(home() / ".claude" / "CLAUDE.md", rendered / "CLAUDE.md"),
             (home() / ".claude" / "settings.json", rendered / "settings.json"),
             (me / "CLAUDE.md", layer / "CLAUDE.md"),
             (profile_path, layer / "profile")]
    if write_over:
        pairs.append((target, staged_over))
    for rc, lines in old_lines.items():
        kept = [l for l in Path(rc).read_text().splitlines() if l not in lines]
        staged_rc = layer / ("rc-" + Path(rc).name.lstrip("."))
        staged_rc.write_text("\n".join(kept) + "\n")
        pairs.append((Path(rc), staged_rc))
    files = []
    for dest, src in pairs:
        if os.path.lexists(dest):
            same = dest.is_file() and not dest.is_symlink() and dest.read_bytes() == src.read_bytes()
            status = "unchanged" if same else "replaced"
        else:
            status = "new"
        files.append({"path": str(dest), "staged": str(src), "status": status})

    notes = []
    if settings_path.is_symlink():
        notes.append(f"~/.claude/settings.json is a link to {tilde(os.readlink(settings_path))}; the link is backed up "
                     "and replaced by a file, and the file it points to is left as it is")
    for rc, lines in old_lines.items():
        notes.append(f"{tilde(rc)} also loads another copy of the kit; these lines are removed (the file is backed up "
                     "first): " + "; ".join(lines))
    old = home() / ".claude" / "CLAUDE.md"
    if (old.is_file() and not old.is_symlink() and "starter/core.md" not in old.read_text()
            and not (me / "CLAUDE.md").exists()):
        missing = [l for l in old.read_text().splitlines() if l.strip() and l.strip() not in personal]
        if missing:
            notes.append(f"{len(missing)} line(s) of your current ~/.claude/CLAUDE.md are not in your new CLAUDE.md; "
                         "it will be backed up, not carried over")
    settings = json.loads((rendered / "settings.json").read_text())
    perms = settings.get("permissions", {})
    summary = {
        "allow_rules": perms.get("allow", []),
        "ask_rules": len(perms.get("ask", [])),
        "deny_rules": len(perms.get("deny", [])),
        "hooks": sorted(settings.get("hooks", {})),
        "status_line": "statusLine" in settings,
        "model_effort_or_mode": [k for k in ("model", "effortLevel") if k in settings]
                                + (["permissions.defaultMode"] if "defaultMode" in perms else []),
    }
    dry_lines = [l for l in dry.stdout.splitlines()
                 if l.startswith("would ") and tilde(me / "CLAUDE.md") not in l]
    carried = {k: sorted(over[k]) for k in CARRIED if over.get(k)}
    dropped = dropped_masked(current, settings) if current else []
    watched = {str(d): fingerprint(d) for d, _ in pairs}
    info = {"kit": str(kit), "me": str(me), "profile": str(profile_path), "overrides": str(target),
            "write_overrides": write_over, "files": files, "dry_run": dry_lines, "notes": notes,
            "carried": carried, "dropped": dropped, "old_shell_lines": old_lines, "watched": watched,
            "settings": summary, "duplicates": duplicate_plugins(kit, raw, ki)}
    (out / "stage.json").write_text(json.dumps(info, indent=2))
    return info


def duplicate_plugins(kit: Path, raw: dict, ki) -> list:
    """Kit plugins that are both linked by the profile and installed with /plugin."""
    exe = shutil.which("claude")
    if not exe:
        return []
    names = raw.get("plugins", " ".join(ki.DEFAULT_PLUGINS)).replace(",", " ").split()
    names = ki.all_plugins() if names == ["all"] else names
    mkts = {n for n, loc in marketplaces() if loc.resolve() == kit.resolve()} or {"claude-kit"}
    try:
        r = subprocess.run([exe, "plugin", "list", "--json"], capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout) if r.returncode == 0 else []
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return []
    out = []
    for p in data:
        pid = p.get("id", "") if isinstance(p, dict) else ""
        name, _, mkt = pid.partition("@")
        if mkt in mkts and name in names and name != PLUGIN:
            out.append(pid)
    return out


# ---------------------------------------------------------------- apply

def without_values(text: str) -> str:
    """The installer's output with its list of dropped settings taken out: that list prints values
    verbatim, and this output goes into a chat. The preview listed them with values hidden."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if skipping and line.startswith("      "):
            continue
        skipping = False
        if "These settings in it are not in the new one" in line:
            out.append(line.split(" These settings")[0] + " The settings it had that the new one doesn't "
                       "are the ones the preview listed as not kept.\n")
            skipping = True
            continue
        out.append(line)
    return "".join(out)


def apply(out: Path) -> int:
    info = json.loads((out / "stage.json").read_text())
    kit, me = Path(info["kit"]), Path(info["me"])
    ki = load_installer(kit)
    cfg = ki.resolve(out / "staged-profile")

    # The preview must still describe the person's files: refuse if any changed since (a plugin
    # installed with /plugin, a hand edit), so a yes never applies something they didn't see.
    moved = [tilde(p) for p, fp in info["watched"].items() if fingerprint(Path(p)) != fp]
    if moved:
        raise SetupError("these files changed since the preview: " + ", ".join(moved) + "; run the preview again")
    # The preview must still be what the kit renders: refuse if the kit or the answers moved.
    with tempfile.TemporaryDirectory() as t:
        r = run_installer(kit, "render", "--profile", str(out / "staged-profile"), "--out", t)
        if r.returncode != 0 or any(Path(t, n).read_bytes() != (out / "rendered" / n).read_bytes()
                                    for n in ("CLAUDE.md", "settings.json")):
            raise SetupError("the kit changed since the preview; run the preview again")

    # The personal layer's files, each backed up first if it is replaced (the installer's own rule).
    inst = ki.Installer(cfg)
    inst.mkdir(me)
    layer = out / "layer"
    inst.put(me / "CLAUDE.md", (layer / "CLAUDE.md").read_text())
    inst.put(Path(info["profile"]), (layer / "profile").read_text())
    if info["write_overrides"]:
        inst.put(Path(info["overrides"]), (layer / "settings.overrides.json").read_text())
    for rc in info["old_shell_lines"]:
        inst.put(Path(rc), (layer / ("rc-" + Path(rc).name.lstrip("."))).read_text())

    r = run_installer(kit, "install", "--skip-repos", "--profile", info["profile"])
    print(without_values(r.stdout), end="")
    if r.returncode != 0:
        print(r.stderr, end="", file=sys.stderr)
        return r.returncode

    problems = []
    with tempfile.TemporaryDirectory() as t:
        r = run_installer(kit, "render", "--profile", info["profile"], "--out", t)
        if r.returncode != 0:
            problems.append("render from the installed profile failed: " + r.stderr.strip())
        else:
            for n in ("CLAUDE.md", "settings.json"):
                installed = (home() / ".claude" / n).read_bytes()
                if installed != Path(t, n).read_bytes():
                    problems.append(f"~/.claude/{n} differs from what the kit renders for your profile")
                if installed != (out / "rendered" / n).read_bytes():
                    problems.append(f"~/.claude/{n} differs from the preview")
    again = run_installer(kit, "install", "--dry-run", "--skip-repos", "--profile", info["profile"])
    changes = [l for l in again.stdout.splitlines() if l.startswith("would ")]
    if again.returncode != 0 or changes:
        problems.append("a second run would still change: " + "; ".join(changes or [again.stderr.strip()]))
    print("\nChecks:")
    if problems:
        for p in problems:
            print(f"  FAILED {p}")
        return 3
    print("  ok ~/.claude/CLAUDE.md and settings.json equal the preview and the kit's render of your profile")
    print("  ok a second run would change nothing")
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kit_setup.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("find-kit", help="say where the kit is")
    s = sub.add_parser("stage", help="build the preview in a scratch folder; writes nothing else")
    s.add_argument("--kit", type=Path, required=True)
    s.add_argument("--answers", type=Path, required=True)
    s.add_argument("--personal", type=Path, required=True, help="the person's own CLAUDE.md, as drafted")
    s.add_argument("--out", type=Path, required=True)
    w = sub.add_parser("show", help="print the previewed settings.json with secret values hidden")
    w.add_argument("--stage", type=Path, required=True)
    a = sub.add_parser("apply", help="write what `stage` previewed")
    a.add_argument("--stage", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "find-kit":
            print(json.dumps(find_kit(), indent=2))
            return 0
        if args.cmd == "stage":
            out = args.out.resolve()
            if str(out) == str(home()) or str(out).startswith(str(home() / ".claude")):
                raise SetupError("stage into a scratch folder, not your home or ~/.claude")
            answers = json.loads(args.answers.read_text())
            info = stage(args.kit.resolve(), answers, args.personal.read_text(), out)
            print(json.dumps(info, indent=2))
            return 0
        if args.cmd == "show":
            settings = json.loads((args.stage / "rendered" / "settings.json").read_text())
            print(json.dumps(mask_tree(settings, strict=False), indent=2, ensure_ascii=False))
            return 0
        return apply(args.stage.resolve())
    except SetupError as e:
        print(f"kit-setup: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # the installer's ProfileError and friends
        if type(e).__name__ == "ProfileError":
            print(f"kit-setup: {e}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
