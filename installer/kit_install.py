#!/usr/bin/env python3
"""Install claude-kit into ~/.claude from a profile.

    kit_install.py install [--profile P] [--skip-repos] [--dry-run]
    kit_install.py render  [--profile P] --out DIR

`install` links the chosen plugins' skills, writes ~/.claude/CLAUDE.md and ~/.claude/settings.json,
sets up the personal layer, the gotchas file, the global gitignore and the shell, and clones the
profile's repos. `render` writes only the CLAUDE.md and settings.json that `install` would write,
into DIR, so another route (such as a setup skill) can show them and install the same files.

Safe to rerun: a file or link it replaces is first moved aside as <file>.bak-<timestamp>.
Standard library only; runs on the python3 that ships with macOS (3.9).
"""
from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
STARTER = KIT / "starter"
STAMP = "kit-install.json"  # in ~/.claude: what the settings were built from, read by the setup check
OVERRIDES = "settings.overrides.json"  # in the personal layer, unless the profile names another file
DEFAULT_PLUGINS = ["start-task", "chief-of-staff", "verify-setup", "papercuts", "setup-check"]
RETIRED_PLUGINS = ("stacked-pr-guard", "downloads-tidy", "disk-cleanup-inventory")  # no longer shipped; a profile naming one gets a note
SHELLS = ("zsh", "bash", "none")
KEYS = ("kit", "me", "plugins", "shell", "shell_file", "settings", "gotchas", "papercuts", "repos_dir", "repos")
GITIGNORE = ("CLAUDE.local.md", "**/.claude/settings.local.json", ".playwright-mcp/", ".claude/worktrees/")
PAPERCUTS_HEADER = (
    "# Papercuts\n\nOpen problems that slowed sessions down. "
    "One `- ` bullet each: date · symptom · fix · project.\n\n"
)


class ProfileError(Exception):
    pass


# ---------------------------------------------------------------- profile

def home() -> Path:
    return Path(os.environ["HOME"])


def expand(value: str, base: Path) -> Path:
    """~ and $HOME expand; a relative path is taken from the profile's folder."""
    h = str(home())
    if value == "~" or value.startswith("~/"):
        value = h + value[1:]
    value = re.sub(r"^\$(HOME\b|\{HOME\})", lambda _: h, value)
    p = Path(value)
    return Path(os.path.normpath(p if p.is_absolute() else base / p))


def parse_profile(text: str) -> dict:
    """`key = value` lines; # starts a comment, at the start of a line or after a space;
    a value may be quoted; a blank value means the default."""
    out = {}
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            raise ProfileError(f"line {n}: expected `key = value`, got {s!r}")
        k, v = (x.strip() for x in s.split("=", 1))
        if v[:1] in ("'", '"'):
            end = v.find(v[0], 1)
            rest = v[end + 1:].strip() if end > 0 else "x"
            if rest and not rest.startswith("#"):
                raise ProfileError(f"line {n}: unmatched quote or text after the quoted value: {v!r}")
            v = v[1:end]
        else:
            v = "" if v.startswith("#") else re.split(r"\s#", v, maxsplit=1)[0].strip()
        if k not in KEYS:
            raise ProfileError(f"line {n}: unknown key {k!r} (known: {', '.join(KEYS)})")
        if k in out:
            raise ProfileError(f"line {n}: {k!r} is set twice")
        if v:
            out[k] = v
    return out


def all_plugins() -> list:
    return sorted(p.name for p in (KIT / "plugins").iterdir() if (p / ".claude-plugin").is_dir())


def resolve(profile_path: Path | None) -> dict:
    """The profile with every default filled in and every path absolute."""
    raw, base = {}, home()
    if profile_path is not None:
        raw = parse_profile(profile_path.read_text())
        base = profile_path.parent
    cfg = {"profile": profile_path}

    kit = KIT
    if "kit" in raw and expand(raw["kit"], base).resolve() != KIT:
        raise ProfileError(f"the profile's kit is {raw['kit']}, but this installer is in {KIT}; run that kit's install.sh")
    cfg["kit"] = kit

    cfg["me"] = expand(raw.get("me", "~/.claude/me"), base)

    names = raw.get("plugins", " ".join(DEFAULT_PLUGINS)).replace(",", " ").split()
    known = all_plugins()
    if names == ["all"]:
        names = known
    cfg["retired"] = [n for n in dict.fromkeys(names) if n in RETIRED_PLUGINS]
    names = [n for n in names if n not in RETIRED_PLUGINS]
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ProfileError(f"unknown plugin(s) {', '.join(unknown)} (known: all, {', '.join(known)})")
    cfg["plugins"] = list(dict.fromkeys(names))

    shell = raw.get("shell") or os.path.basename(os.environ.get("SHELL", ""))
    cfg["shell"] = shell if shell in SHELLS else "none"
    if "shell" in raw and raw["shell"] not in SHELLS:
        raise ProfileError(f"shell must be one of {', '.join(SHELLS)}, got {raw['shell']!r}")
    cfg["shell_file"] = expand(raw["shell_file"], base) if "shell_file" in raw else None

    if "settings" in raw:
        cfg["settings"] = expand(raw["settings"], base)
        if not cfg["settings"].is_file():
            raise ProfileError(f"settings overrides file {cfg['settings']} does not exist")
    else:
        own = cfg["me"] / OVERRIDES
        cfg["settings"] = own if own.is_file() else None

    cfg["gotchas"] = expand(raw.get("gotchas", "~/.claude/gotchas.md"), base)
    cfg["papercuts"] = expand(raw["papercuts"], base) if "papercuts" in raw else None
    cfg["repos_dir"] = expand(raw["repos_dir"], base) if "repos_dir" in raw else None
    cfg["repos"] = expand(raw["repos"], base) if "repos" in raw else None
    if cfg["repos"] and not cfg["repos_dir"]:
        raise ProfileError("the profile names a repos list but no repos_dir to clone them into")

    # The kit path goes inside double quotes in hook commands, and both paths go in @imports.
    if re.search(r'["$`\\\s]', str(kit)):
        raise ProfileError(f"the kit's path {kit} holds a space, quote, $, backtick or backslash; move the kit")
    if re.search(r"\s", str(cfg["me"])):
        raise ProfileError(f"the personal layer's path {cfg['me']} holds a space, which an @import can't read")
    # ~/.claude/CLAUDE.md imports <me>/CLAUDE.md, so the layer can't be ~/.claude or a folder holding it.
    dot, me = os.path.realpath(home() / ".claude"), os.path.realpath(cfg["me"])
    if dot == me or dot.startswith(me.rstrip("/") + "/"):
        raise ProfileError(f"the personal layer {cfg['me']} is ~/.claude or holds it; use a folder of its own, such as ~/.claude/me")
    # shell_file goes inside double quotes in a `source` line that runs at every shell start.
    if cfg["shell_file"] and re.search(r'["$`\\\n]', str(cfg["shell_file"])):
        raise ProfileError(f"shell_file {cfg['shell_file']} holds a quote, $, backtick or backslash; rename or move it")
    return cfg


# ---------------------------------------------------------------- render

def tilde(p: Path) -> str:
    """A path under HOME written with ~, as CLAUDE.md imports read it."""
    s = str(p)
    for h in dict.fromkeys((str(home()), os.path.realpath(home()))):
        if s.startswith(h + "/"):
            return "~/" + s[len(h) + 1:]
    return s


def render_claude_md(cfg: dict) -> str:
    text = (STARTER / "CLAUDE.md.template").read_text()
    return text.replace("__KIT__", tilde(cfg["kit"])).replace("__ME__", tilde(cfg["me"]))


def substitute(obj, subs: dict):
    if isinstance(obj, str):
        for k, v in subs.items():
            obj = obj.replace(k, v)
        return obj
    if isinstance(obj, list):
        return [substitute(x, subs) for x in obj]
    if isinstance(obj, dict):
        return {k: substitute(v, subs) for k, v in obj.items()}
    return obj


# The kit's safe defaults live under these keys, so an override can add to them but never remove them.
PROTECTED = ("permissions", "hooks")
STRING_LISTS = ("permissions.allow", "permissions.deny", "permissions.ask", "permissions.additionalDirectories")


def kind(v) -> str:
    return "an object" if isinstance(v, dict) else "a list" if isinstance(v, list) else "null" if v is None else "a value"


def merge(base, over, path: str = ""):
    """Dicts merge key by key, lists are added together without repeats (base first), and other
    values take the override. An override must have the base's type where the base has the key;
    null removes a base key, except anywhere under permissions or hooks."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = copy.deepcopy(base)
        for k, v in over.items():
            p = f"{path}.{k}" if path else k
            if v is None:
                if p.split(".")[0] in PROTECTED and k in out:
                    raise ProfileError(f"settings overrides: {p} is null, which would remove the kit's base {p}; "
                                       f"base permission rules and hooks can't be removed")
                out.pop(k, None)
            elif k in out:
                out[k] = merge(out[k], v, p)
            else:
                out[k] = copy.deepcopy(v)
        return out
    if isinstance(base, list) and isinstance(over, list):
        out = copy.deepcopy(base)
        for x in over:
            if x not in out:
                out.append(copy.deepcopy(x))
        return out
    if kind(base) != kind(over):
        raise ProfileError(f"settings overrides: {path} is {kind(over)}, where the base settings have {kind(base)}")
    return copy.deepcopy(over)


def check_overrides(over, where: Path):
    """Shapes Claude Code requires, checked where the base has nothing to compare with."""
    if not isinstance(over, dict):
        raise ProfileError(f"settings overrides {where} must hold a JSON object")
    perms = over.get("permissions")
    if perms is not None and not isinstance(perms, dict):
        raise ProfileError(f"settings overrides: permissions is {kind(perms)}, not an object")
    for p in STRING_LISTS:
        v = (perms or {}).get(p.split(".")[1])
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ProfileError(f"settings overrides: {p} must be a list of rule strings")
    hooks = over.get("hooks")
    if hooks is not None and not (isinstance(hooks, dict) and all(isinstance(v, list) for v in hooks.values())):
        raise ProfileError("settings overrides: hooks must be an object of lists, one per event")
    env = over.get("env")
    if env is not None and not (isinstance(env, dict) and all(isinstance(v, str) for v in env.values())):
        raise ProfileError("settings overrides: env must be an object of strings")


def load_json(path: Path, what: str):
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ProfileError(f"{what} {path} is not valid JSON: {e}") from None


def render_settings(cfg: dict) -> str:
    kit = str(cfg["kit"])
    s = substitute(load_json(STARTER / "settings.json", "base settings"), {"__KIT__": kit})
    derived = {}
    if cfg["gotchas"] != home() / ".claude" / "gotchas.md":
        derived["env"] = {"GOTCHAS_FILE": str(cfg["gotchas"])}
    s = merge(s, derived)
    if cfg["settings"]:
        over = load_json(cfg["settings"], "settings overrides")
        check_overrides(over, cfg["settings"])
        subs = {"__KIT__": kit, "__ME__": str(cfg["me"]), "__HOME__": str(home())}
        s = merge(s, substitute(over, subs))
    return json.dumps(s, indent=2, ensure_ascii=False) + "\n"


def rc_lines(cfg: dict) -> list:
    if cfg["shell"] == "none":
        return []
    ext = {"zsh": "zsh", "bash": "bash"}[cfg["shell"]]
    files = [cfg["kit"] / "extras" / cfg["shell"] / f"claude-kit.{ext}"]
    if cfg["shell_file"]:
        files.append(cfg["shell_file"])
    out = []
    for f in files:
        s = tilde(f)
        out.append(f'source "$HOME/{s[2:]}"' if s.startswith("~/") else f'source "{s}"')
    return out


def rc_file(cfg: dict) -> Path | None:
    if cfg["shell"] == "zsh":
        return Path(os.environ.get("ZDOTDIR") or home()) / ".zshrc"
    if cfg["shell"] == "bash":
        return home() / ".bashrc"
    return None


# ---------------------------------------------------------------- filesystem

class Installer:
    def __init__(self, cfg: dict, dry: bool = False):
        self.cfg, self.dry = cfg, dry
        # Everything that can fail on the profile's content is built before anything is written.
        self.claude_md_text = render_claude_md(cfg)
        self.settings_text = render_settings(cfg)
        self.repo_list = read_repos(cfg)
        self.stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.notes = []
        self.taken = set()

    # The plain form of each past-tense verb, for a dry run's "would <verb>".
    PLANNED = {"wrote": "write", "linked": "link", "unlinked": "unlink", "backed up": "back up",
               "ignored": "ignore", "appended": "append", "cloned": "clone"}

    def say(self, verb: str, what: str):
        what = what.replace(str(home()) + "/", "~/")
        if self.dry and verb in self.PLANNED:
            print(f"{'would ' + self.PLANNED[verb]:<16} {what}")
        else:
            print(f"{verb:<10} {what}")

    def mkdir(self, p: Path):
        if not self.dry:
            p.mkdir(parents=True, exist_ok=True)

    def aside(self, dest: Path):
        """Move dest to a backup name that no file has yet. Backups of skills go outside
        ~/.claude/skills, where Claude Code would load them as skills."""
        folder = dest.parent
        if folder == home() / ".claude" / "skills":
            folder = home() / ".claude" / "kit-backups" / "skills"
            if not self.dry:
                folder.mkdir(parents=True, exist_ok=True)
        bak, n = folder / f"{dest.name}.bak-{self.stamp}", 1
        while os.path.lexists(bak) or bak in self.taken:
            n += 1
            bak = folder / f"{dest.name}.bak-{self.stamp}-{n}"
        self.taken.add(bak)
        if not self.dry:
            os.rename(dest, bak)
        self.say("backed up", f"{dest} -> {bak}")
        return bak

    def put(self, dest: Path, content: str) -> Path | None:
        """Write content to dest unless it is already there; a different file is moved aside first."""
        bak = None
        if dest.is_symlink() or dest.exists():
            if not dest.is_symlink() and dest.is_file() and dest.read_text() == content:
                self.say("unchanged", str(dest))
                return None
            bak = self.aside(dest)
        if not self.dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        self.say("wrote", str(dest))
        return bak

    def create(self, dest: Path, content: str):
        """Write dest only if nothing is there: the person's own file from then on."""
        if dest.is_symlink() or dest.exists():
            self.say("present", str(dest))
            return
        if not self.dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
        self.say("wrote", str(dest))

    def link(self, dest: Path, target: Path):
        if not target.exists():
            raise ProfileError(f"missing link target: {target}")
        if dest.is_symlink() and os.readlink(dest) == str(target):
            self.say("unchanged", str(dest))
            return
        if dest.is_symlink() or dest.exists():
            self.aside(dest)
        if not self.dry:
            dest.symlink_to(target)
        self.say("linked", f"{dest} -> {target}")

    # ------------------------------------------------------------ steps

    def skills(self):
        cfg, skills = self.cfg, home() / ".claude" / "skills"
        self.mkdir(skills)
        wanted = {}
        for p in cfg["plugins"]:
            d = cfg["kit"] / "plugins" / p / "skills"
            for s in sorted(d.iterdir()) if d.is_dir() else []:
                if (s / "SKILL.md").is_file():
                    wanted[s.name] = s
        for name, target in wanted.items():
            self.link(skills / name, target)
        # A skill dropped from the plugin set: remove only links that point into this kit's plugins.
        plugins_dir = str(cfg["kit"] / "plugins") + "/"
        for l in sorted(skills.iterdir()) if skills.is_dir() else []:
            if l.is_symlink() and l.name not in wanted and os.readlink(l).startswith(plugins_dir):
                if not self.dry:
                    l.unlink()
                self.say("unlinked", f"{l} (its plugin is not in the profile)")

    def personal_layer(self):
        """The layer's CLAUDE.md starts from the template, or from the rules in an existing
        ~/.claude/CLAUDE.md, which the next step replaces with the two imports."""
        me, old = self.cfg["me"], home() / ".claude" / "CLAUDE.md"
        self.mkdir(me)
        mine = me / "CLAUDE.md"
        carry = (not os.path.lexists(mine) and old.is_file() and not old.is_symlink()
                 and old.read_text() != self.claude_md_text and "starter/core.md" not in old.read_text())
        if carry:
            self.create(mine, old.read_text())
            self.notes.append(f"Your previous ~/.claude/CLAUDE.md is now {tilde(mine)}, imported after the kit's core. "
                              "If it imports files by relative paths, make them absolute or ~ paths.")
        else:
            self.create(mine, (STARTER / "personal.md.template").read_text())

    def claude_md(self):
        bak = self.put(home() / ".claude" / "CLAUDE.md", self.claude_md_text)
        if bak and not any("previous ~/.claude/CLAUDE.md" in n for n in self.notes):
            self.notes.append(f"Your previous ~/.claude/CLAUDE.md is at {tilde(bak)}. Copy any rules you want "
                              f"to keep into {tilde(self.cfg['me'] / 'CLAUDE.md')}.")

    def settings(self):
        dest = home() / ".claude" / "settings.json"
        new = self.settings_text
        old = None
        if dest.is_file() and not dest.is_symlink():
            try:
                old = json.loads(dest.read_text())
            except json.JSONDecodeError:
                old = None
        bak = self.put(dest, new)
        if bak and isinstance(old, dict):
            lost = dropped(old, json.loads(new))
            if lost:
                where = self.cfg["settings"] or self.cfg["me"] / OVERRIDES
                self.notes.append(
                    f"Your previous settings.json is at {tilde(bak)}. These settings in it are not in the new one; "
                    f"to keep any, add them to {tilde(where)} and rerun:\n      " + "\n      ".join(lost))

    def record_install(self):
        """Record what the settings were built from, so the setup check can tell when the kit
        has moved since. Kit-owned state: rewritten in place, never backed up."""
        cfg, dest = self.cfg, home() / ".claude" / STAMP
        if self.dry:
            return  # bookkeeping, not setup: a preview doesn't list it
        commit = dirty = None
        if shutil.which("git"):
            r = subprocess.run(["git", "-C", str(cfg["kit"]), "rev-parse", "HEAD"], capture_output=True, text=True)
            if r.returncode == 0:
                commit = r.stdout.strip()
                r = subprocess.run(["git", "-C", str(cfg["kit"]), "status", "--porcelain", "--untracked-files=no"],
                                   capture_output=True, text=True)
                dirty = bool(r.stdout.strip()) if r.returncode == 0 else None
        # A first run with no profile writes the default one, all defaults: the same settings, so name it.
        profile = cfg["profile"] or (default_profile() if default_profile().is_file() else None)
        text = json.dumps({"kit": str(cfg["kit"]), "commit": commit, "dirty": dirty,
                           "profile": str(profile) if profile else None,
                           "me": str(cfg["me"])}, indent=2) + "\n"
        if dest.is_file() and not dest.is_symlink() and dest.read_text() == text:
            self.say("unchanged", str(dest))
            return
        if not self.dry:
            if dest.is_symlink():
                dest.unlink()
            dest.write_text(text)
        self.say("wrote", str(dest))

    def gotchas(self):
        self.create(self.cfg["gotchas"], (STARTER / "gotchas.md").read_text())

    def papercuts(self):
        if self.cfg["papercuts"]:
            self.create(self.cfg["papercuts"], PAPERCUTS_HEADER)

    def gitignore(self):
        if not shutil.which("git"):
            self.notes.append("git isn't installed, so the global gitignore entries were skipped.")
            return
        r = subprocess.run(["git", "config", "--global", "core.excludesfile"], capture_output=True, text=True)
        gi = r.stdout.strip() or os.path.join(os.environ.get("XDG_CONFIG_HOME") or str(home() / ".config"), "git", "ignore")
        gi = Path(str(home()) + gi[1:] if gi.startswith("~/") else gi)
        have = gi.read_text().splitlines() if gi.is_file() else []
        missing = [p for p in GITIGNORE if p not in have]
        if missing and not self.dry:
            gi.parent.mkdir(parents=True, exist_ok=True)
            text = gi.read_text() if gi.is_file() else ""
            if text and not text.endswith("\n"):
                text += "\n"
            gi.write_text(text + "".join(p + "\n" for p in missing))
        for p in missing:
            self.say("ignored", f"{p} (in {gi})")

    def shell(self):
        rc, lines = rc_file(self.cfg), rc_lines(self.cfg)
        if rc is None:
            self.notes.append("No shell set up (shell = none, or a shell other than zsh or bash).")
            return
        have = rc.read_text().splitlines() if rc.is_file() else []
        missing = [l for l in lines if l not in have]
        if missing and not self.dry:
            text = rc.read_text() if rc.is_file() else ""
            if text and not text.endswith("\n"):
                text += "\n"
            rc.write_text(text + "\n# Claude Code (claude-kit)\n" + "".join(l + "\n" for l in missing))
        for l in missing:
            self.say("appended", f"{l} (to {tilde(rc)})")
        if not missing:
            self.say("unchanged", str(rc))
        if self.cfg["shell"] == "bash" and platform.system() == "Darwin":
            bp = home() / ".bash_profile"
            if not (bp.is_file() and ".bashrc" in bp.read_text()):
                self.notes.append(
                    "On macOS a new Terminal window runs bash as a login shell, which reads ~/.bash_profile, "
                    "not ~/.bashrc. If yours doesn't already, add this line to ~/.bash_profile: "
                    '[ -f ~/.bashrc ] && . ~/.bashrc'
                )

    def repos(self, skip: bool):
        if skip:
            return
        gh = shutil.which("gh")
        for slug, dest in self.repo_list:
            if (dest / ".git").exists():
                self.say("present", str(dest))
                continue
            if not self.dry:
                dest.parent.mkdir(parents=True, exist_ok=True)
                cmd = ([gh, "repo", "clone", slug, str(dest), "--", "-q"] if gh
                       else ["git", "clone", "-q", f"https://github.com/{slug}.git", str(dest)])
                if subprocess.run(cmd).returncode != 0:
                    self.notes.append(f"Couldn't clone {slug}; rerun once you have access.")
                    continue
            self.say("cloned", f"{slug} -> {dest}")

    def checks(self):
        for tool, why in (("jq", "the status line needs it"),):
            if not shutil.which(tool):
                self.notes.append(f"{tool} isn't installed: {why}.")
        if self.cfg["retired"]:
            self.notes.append(f"The kit no longer ships {', '.join(self.cfg['retired'])}; "
                              "remove it from your profile's plugins line, and the installer skips it meanwhile.")

    def run(self, skip_repos: bool = False):
        self.mkdir(home() / ".claude")
        self.personal_layer()
        self.skills()
        self.claude_md()
        self.settings()
        self.record_install()
        self.gotchas()
        self.papercuts()
        self.gitignore()
        self.shell()
        self.repos(skip_repos)
        self.checks()


def read_repos(cfg: dict) -> list:
    """(owner/repo, destination) for each line of the profile's repo list."""
    if not cfg["repos"]:
        return []
    if not cfg["repos"].is_file():
        raise ProfileError(f"the repo list {cfg['repos']} does not exist")
    out = []
    for n, line in enumerate(cfg["repos"].read_text().splitlines(), 1):
        parts = line.split("#", 1)[0].split()
        if not parts:
            continue
        if len(parts) > 2 or not re.fullmatch(r"[\w.-]+/[\w.-]+", parts[0]):
            raise ProfileError(f"{cfg['repos']} line {n}: expected `<owner/repo> [path]`, got {line!r}")
        out.append((parts[0], cfg["repos_dir"] / (parts[1] if len(parts) > 1 else parts[0].split("/")[1])))
    return out


def dropped(old, new, path: str = "") -> list:
    """Every setting in old that new doesn't carry, at any depth: a key, a list item or a changed value."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k, v in old.items():
            p = f"{path}.{k}" if path else k
            out += dropped(v, new[k], p) if k in new else [f"{p} = {json.dumps(v, ensure_ascii=False)}"]
        return out
    if isinstance(old, list) and isinstance(new, list):
        return [f"{path}[] {json.dumps(x, ensure_ascii=False)}" for x in old if x not in new]
    if old != new:
        return [f"{path} = {json.dumps(old, ensure_ascii=False)} (now {json.dumps(new, ensure_ascii=False)})"]
    return []


# ---------------------------------------------------------------- main

def default_profile() -> Path:
    return home() / ".claude" / "me" / "profile"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="install.sh", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("install", help="install into ~/.claude")
    i.add_argument("--profile", type=Path, help="profile file (default ~/.claude/me/profile)")
    i.add_argument("--skip-repos", action="store_true", help="don't clone the profile's repos")
    i.add_argument("--dry-run", action="store_true", help="say what would change and change nothing")
    r = sub.add_parser("render", help="write the CLAUDE.md and settings.json install would write")
    r.add_argument("--profile", type=Path)
    r.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    profile, wrote_profile = a.profile, False
    if profile is None and default_profile().is_file():
        profile = default_profile()
    if profile is not None:
        profile = Path(os.path.abspath(os.path.expanduser(str(profile))))
        if not profile.is_file():
            print(f"no profile at {profile}", file=sys.stderr)
            return 2
    try:
        cfg = resolve(profile)
        if a.cmd == "render":
            md, settings = render_claude_md(cfg), render_settings(cfg)
            a.out.mkdir(parents=True, exist_ok=True)
            (a.out / "CLAUDE.md").write_text(md)
            (a.out / "settings.json").write_text(settings)
            print(f"wrote {a.out / 'CLAUDE.md'} and {a.out / 'settings.json'}")
            return 0
        inst = Installer(cfg, dry=a.dry_run)
        print(f"profile    {profile or 'none: defaults'}\nkit        {cfg['kit']}\n")
        if profile is None and cfg["me"] == default_profile().parent:
            inst.mkdir(cfg["me"])
            inst.create(default_profile(), (KIT / "installer" / "profile.example").read_text())
            wrote_profile = True
        inst.run(skip_repos=a.skip_repos)
    except ProfileError as e:
        print(f"install.sh: {e}", file=sys.stderr)
        return 1
    if inst.notes:
        print("\nNotes:")
        for n in inst.notes:
            print(f"  - {n}")
    me = tilde(cfg["me"])
    print(f"\n{'Dry run: nothing changed.' if a.dry_run else 'Done.'} Next, by hand:")
    if wrote_profile:
        print(f"  - your profile is {me}/profile, all defaults; edit it and rerun install.sh to change them")
    print(f"  - fill in {me}/CLAUDE.md, your own rules, which ~/.claude/CLAUDE.md imports after the kit's core")
    if cfg["shell"] != "none":
        print(f"  - open a new terminal (or `source {tilde(rc_file(cfg))}`), then run `claude`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
