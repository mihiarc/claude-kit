"""Tests for the kit-setup skill's script, in scratch HOMEs, never the real one.

    python3 -m unittest discover plugins/kit-setup/tests

Each test copies the kit into a fresh HOME and drives `kit_setup.py` the way the skill does:
stage a preview, then apply it. They check that staging writes nothing, that what the skill
installs equals what the kit's own renderer gives for the same answers, that a rerun backs up
what it replaces, and that the result passes the installer's empty-HOME checks.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[3]
SCRIPT_REL = Path("plugins/kit-setup/skills/kit-setup/scripts/kit_setup.py")
sys.path.insert(0, str(KIT / SCRIPT_REL.parent))
import kit_setup as ks  # noqa: E402


def tree(root: Path, skip=("src",)) -> dict:
    """Every path under root, less `skip`: a link's target or a file's hash."""
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not (Path(d) == root and x in skip)]
        for n in dirs + files:
            p = Path(d) / n
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = "-> " + os.readlink(p)
            elif p.is_file():
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
            else:
                out[rel] = "dir"
    return out


def copy_kit(dest: Path):
    """The kit as a clone would have it: tracked and new files, less local ones."""
    r = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=KIT, capture_output=True)
    if r.returncode != 0:
        shutil.copytree(KIT, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "CLAUDE.local.md", "worktrees"))
        return
    for f in filter(None, r.stdout.split(b"\0")):
        src = KIT / f.decode()
        if src.is_file() and src.name != "CLAUDE.local.md":
            (dest / f.decode()).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / f.decode())


GIT_PERSONAL = """I'm a data analyst. This computer is for work.

## Where things live
- Repos: `~/src`, under the GitHub owner `example-analyst`.
- Documents for me to read: `~/Documents/claude`.
"""

NO_GIT_PERSONAL = """I write grant applications for a land trust. This computer is personal.

## How I work
- I don't work in git. Every task takes start-task's no-repo path: a plain task folder with its notes, and no worktree, branch or PR.
- Task folders go in `~/claude-tasks/<task>`.

## Where things live
- Documents for me to read: `~/Documents/claude`.
"""


class Scratch(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="kit-setup-")).resolve()
        self.work = Path(tempfile.mkdtemp(prefix="kit-setup-stage-")).resolve()
        self.kit = self.home / "src" / "claude-kit"
        copy_kit(self.kit)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        # No real `claude` on the PATH: a test that needs one writes a fake into self.bin.
        path = [str(self.bin), "/usr/bin", "/bin", "/usr/sbin", "/sbin", str(Path(sys.executable).parent)]
        git = shutil.which("git")
        if git:
            path.append(str(Path(git).parent))
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL", "ZDOTDIR", "GOTCHAS_FILE", "CLAUDECODE")}
        # SETUP_CHECK_NO_REFRESH: the setup-check hook starts no background lookup in a test HOME.
        self.env.update(HOME=str(self.home), SHELL="/bin/zsh", PATH=os.pathsep.join(path), SETUP_CHECK_NO_REFRESH="1")
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def run_script(self, *args, ok=True):
        r = subprocess.run([sys.executable, "-I", str(self.kit / SCRIPT_REL), *args],
                           env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def stage(self, answers: dict, personal: str, ok=True):
        self.n += 1
        d = self.work / f"s{self.n}"
        d.mkdir()
        (d / "answers.json").write_text(json.dumps(answers))
        (d / "personal.md").write_text(personal)
        r = self.run_script("stage", "--kit", str(self.kit), "--answers", str(d / "answers.json"),
                            "--personal", str(d / "personal.md"), "--out", str(d / "stage"), ok=ok)
        return (json.loads(r.stdout) if r.returncode == 0 else r), d / "stage"

    def apply(self, stage: Path, ok=True):
        return self.run_script("apply", "--stage", str(stage), ok=ok)

    def render(self) -> Path:
        out = self.work / f"render{self.n}"
        r = subprocess.run([sys.executable, "-I", str(self.kit / "installer" / "kit_install.py"), "render",
                            "--profile", str(self.home / ".claude" / "me" / "profile"), "--out", str(out)],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return out

    def settings(self) -> dict:
        return json.loads((self.home / ".claude" / "settings.json").read_text())

    def assert_safe_defaults(self):
        s = self.settings()
        perms = s.get("permissions", {})
        self.assertEqual(perms.get("allow", []), [])
        for k in ("model", "effortLevel"):
            self.assertNotIn(k, s)
        self.assertNotIn("defaultMode", perms)

    def assert_equals_render(self):
        out = self.render()
        for n in ("CLAUDE.md", "settings.json"):
            self.assertEqual((self.home / ".claude" / n).read_bytes(), (out / n).read_bytes(), n)

    def assert_hooks_idle(self):
        events = {
            "PreToolUse": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            "PostToolUse": {"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": ""}},
            "PostToolUseFailure": {"tool_name": "Bash", "tool_input": {"command": "ls"}, "error": "boom"},
            "SessionStart": {"source": "compact"},
        }
        ran = 0
        for event, groups in self.settings()["hooks"].items():
            for g in groups:
                for h in g["hooks"]:
                    payload = dict(events[event], hook_event_name=event, session_id="t", cwd=str(self.home))
                    r = subprocess.run(["/bin/sh", "-c", h["command"]], input=json.dumps(payload),
                                       env=self.env, capture_output=True, text=True, timeout=60)
                    self.assertEqual(r.returncode, 0, (h["command"], r.stderr))
                    if event != "SessionStart":
                        self.assertEqual(r.stdout + r.stderr, "", h["command"])
                    ran += 1
        self.assertGreaterEqual(ran, 4)


GIT_ANSWERS = {"plugins": ["start-task", "chief-of-staff", "verify-setup", "papercuts"], "shell": "zsh",
               "statusline": True, "papercuts": "~/.claude/me/papercuts.md"}
NO_GIT_ANSWERS = {"plugins": ["start-task", "chief-of-staff", "papercuts"], "shell": "none",
                  "statusline": False, "papercuts": None}


class TestNewcomers(Scratch):
    def test_stage_writes_nothing(self):
        before = tree(self.home)
        info, stage = self.stage(GIT_ANSWERS, GIT_PERSONAL)
        self.assertEqual(tree(self.home), before)
        self.assertEqual({f["status"] for f in info["files"]}, {"new"})
        self.assertTrue(info["dry_run"])
        self.assertTrue(all(l.startswith("would ") for l in info["dry_run"]))
        # Even when a setup is already there: a "no" leaves it exactly as it was.
        self.apply(stage)
        before = tree(self.home)
        self.stage(dict(GIT_ANSWERS, shell="none", statusline=False), "changed\n")
        self.assertEqual(tree(self.home), before)

    def test_git_newcomer(self):
        info, stage = self.stage(GIT_ANSWERS, GIT_PERSONAL)
        self.assertEqual(info["settings"]["allow_rules"], [])
        self.assertEqual(info["settings"]["model_effort_or_mode"], [])
        out = self.apply(stage).stdout
        self.assertIn("ok a second run would change nothing", out)
        c = self.home / ".claude"
        self.assertEqual((c / "me" / "CLAUDE.md").read_text(), GIT_PERSONAL)
        self.assertEqual(sorted(p.name for p in (c / "skills").iterdir()),
                         ["chief-of-staff", "papercut-sweep", "start-task", "verify-setup"])
        self.assertIn("statusLine", self.settings())
        self.assertIn('source "$HOME/src/claude-kit/extras/zsh/claude-kit.zsh"', (self.home / ".zshrc").read_text())
        self.assertTrue((c / "me" / "papercuts.md").is_file())
        self.assert_equals_render()
        self.assert_safe_defaults()
        self.assert_hooks_idle()
        # The same answers again: everything unchanged, and applying changes nothing.
        info, stage = self.stage(GIT_ANSWERS, GIT_PERSONAL)
        self.assertEqual({f["status"] for f in info["files"]}, {"unchanged"})
        self.assertEqual(info["dry_run"], [])
        before = tree(self.home)
        self.apply(stage)
        self.assertEqual(tree(self.home), before)

    def test_no_git_newcomer(self):
        _, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.apply(stage)
        c = self.home / ".claude"
        self.assertIn("I don't work in git", (c / "me" / "CLAUDE.md").read_text())
        self.assertNotIn("statusLine", self.settings())
        self.assertEqual(json.loads((c / "me" / "settings.overrides.json").read_text()), {"statusLine": None})
        self.assertFalse((self.home / ".zshrc").exists())
        self.assertFalse((c / "me" / "papercuts.md").exists())
        self.assertEqual(sorted(p.name for p in (c / "skills").iterdir()),
                         ["chief-of-staff", "papercut-sweep", "start-task"])
        self.assert_equals_render()
        self.assert_safe_defaults()
        self.assert_hooks_idle()
        before = tree(self.home)
        _, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.apply(stage)
        self.assertEqual(tree(self.home), before)

    def test_rerun_backs_up_each_replaced_file(self):
        _, stage = self.stage(GIT_ANSWERS, GIT_PERSONAL)
        self.apply(stage)
        c = self.home / ".claude"
        old = {p: p.read_text() for p in (c / "settings.json", c / "me" / "CLAUDE.md", c / "me" / "profile")}
        info, stage = self.stage(dict(GIT_ANSWERS, statusline=False), GIT_PERSONAL + "- One more rule.\n")
        status = {f["path"]: f["status"] for f in info["files"]}
        self.assertEqual(status, {str(c / "CLAUDE.md"): "unchanged", str(c / "settings.json"): "replaced",
                                  str(c / "me" / "CLAUDE.md"): "replaced", str(c / "me" / "profile"): "unchanged",
                                  str(c / "me" / "settings.overrides.json"): "new"})
        self.apply(stage)
        for p, text in old.items():
            if p.read_text() != text:
                baks = list(p.parent.glob(p.name + ".bak-*"))
                self.assertEqual([b.read_text() for b in baks], [text], p)
        self.assertEqual(list(c.glob("CLAUDE.md.bak-*")), [])
        self.assertNotIn("statusLine", self.settings())
        self.assert_equals_render()

    def test_existing_own_claude_md(self):
        c = self.home / ".claude"
        c.mkdir()
        (c / "CLAUDE.md").write_text("Always answer in British English.\n")
        (c / "settings.json").write_text(json.dumps({"model": "opus", "permissions": {"allow": ["Bash(git push*)"]}}))
        info, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.assertTrue(any("not in your new CLAUDE.md" in n for n in info["notes"]))
        carried = NO_GIT_PERSONAL + "\n## Carried over\n- Always answer in British English.\n"
        info, stage = self.stage(NO_GIT_ANSWERS, carried)
        self.assertEqual(info["notes"], [])
        self.apply(stage)
        self.assertEqual([b.read_text() for b in c.glob("CLAUDE.md.bak-*")], ["Always answer in British English.\n"])
        self.assertEqual(len(list(c.glob("settings.json.bak-*"))), 1)
        self.assert_safe_defaults()
        self.assert_equals_render()

    def test_named_override_only(self):
        _, stage = self.stage(dict(NO_GIT_ANSWERS, overrides={"permissions": {"allow": ["Bash(ls)"]}}), NO_GIT_PERSONAL)
        self.apply(stage)
        self.assertEqual(self.settings()["permissions"]["allow"], ["Bash(ls)"])
        self.assertIn("Bash(git push --force*)", self.settings()["permissions"]["ask"])
        self.assert_equals_render()

    def test_plugin_settings_carried(self):
        """/plugin install writes enabledPlugins and the marketplace into settings.json; a guided
        setup keeps both, and lists anything else it drops."""
        c = self.home / ".claude"
        c.mkdir()
        mkt = {"claude-kit": {"source": {"source": "directory", "path": str(self.kit)}}}
        (c / "settings.json").write_text(json.dumps({"extraKnownMarketplaces": mkt,
                                                     "enabledPlugins": {"kit-setup@claude-kit": True},
                                                     "theme": "dark"}))
        info, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.assertEqual(info["carried"], {"enabledPlugins": ["kit-setup@claude-kit"],
                                           "extraKnownMarketplaces": ["claude-kit"]})
        self.assertEqual(info["dropped"], ['theme = "dark"'])
        self.apply(stage)
        s = self.settings()
        self.assertEqual(s["enabledPlugins"], {"kit-setup@claude-kit": True})
        self.assertEqual(s["extraKnownMarketplaces"], mkt)
        self.assertNotIn("theme", s)
        self.assert_safe_defaults()
        self.assert_equals_render()
        # A plugin removed with /plugin later stays removed on a rerun: settings.json is the truth.
        s["enabledPlugins"] = {}
        (c / "settings.json").write_text(json.dumps(s))
        info, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.assertNotIn("enabledPlugins", info["carried"])
        self.apply(stage)
        self.assertNotIn("enabledPlugins", self.settings())
        self.assertIn("extraKnownMarketplaces", self.settings())

    def test_symlinked_settings_keeps_plugin_entries(self):
        """settings.json linked into a dotfiles copy: the /plugin entries are read through the
        link and kept; the link is backed up and the copy it points to is left alone."""
        c = self.home / ".claude"
        c.mkdir()
        dots = self.home / "dotfiles"
        dots.mkdir()
        mkt = {"claude-kit": {"source": {"source": "directory", "path": str(self.kit)}}}
        text = json.dumps({"enabledPlugins": {"kit-setup@claude-kit": True}, "extraKnownMarketplaces": mkt})
        (dots / "settings.json").write_text(text)
        (c / "settings.json").symlink_to(dots / "settings.json")
        info, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.assertEqual(info["carried"], {"enabledPlugins": ["kit-setup@claude-kit"],
                                           "extraKnownMarketplaces": ["claude-kit"]})
        self.assertTrue(any("is a link to" in n for n in info["notes"]))
        self.apply(stage)
        s = self.settings()
        self.assertEqual(s["enabledPlugins"], {"kit-setup@claude-kit": True})
        self.assertEqual(s["extraKnownMarketplaces"], mkt)
        self.assertFalse((c / "settings.json").is_symlink())
        self.assertEqual((dots / "settings.json").read_text(), text)
        self.assert_equals_render()

    def test_change_after_preview_refused(self):
        """A plugin enabled with /plugin between the preview and the yes: apply refuses and writes
        nothing, rather than turning it off."""
        _, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.apply(stage)
        _, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        c = self.home / ".claude"
        s = self.settings()
        s["enabledPlugins"] = {"speaker-prep@claude-kit": True}
        (c / "settings.json").write_text(json.dumps(s))
        before = tree(self.home)
        r = self.apply(stage, ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("changed since the preview", r.stderr)
        self.assertIn("settings.json", r.stderr)
        self.assertEqual(tree(self.home), before)
        # Staged again, the preview shows the plugin kept, and apply keeps it.
        info, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.assertEqual(info["carried"], {"enabledPlugins": ["speaker-prep@claude-kit"]})
        self.apply(stage)
        self.assertEqual(self.settings()["enabledPlugins"], {"speaker-prep@claude-kit": True})

    def test_kit_change_after_preview_refused(self):
        """The kit's base settings move between the preview and the yes: apply refuses."""
        _, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        base = self.kit / "starter" / "settings.json"
        s = json.loads(base.read_text())
        s["permissions"]["ask"].append("Bash(rm -rf*)")
        base.write_text(json.dumps(s, indent=2))
        before = tree(self.home)
        r = self.apply(stage, ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the kit changed since the preview", r.stderr)
        self.assertEqual(tree(self.home), before)

    def test_secrets_not_shown(self):
        """Old settings that hold a token: the preview's dropped list and `show` hide the values."""
        c = self.home / ".claude"
        c.mkdir()
        secret = "ghp_" + "A1b2C3d4" * 5
        (c / "settings.json").write_text(json.dumps({
            "env": {"GITHUB_TOKEN": secret, "EDITOR": "vim"}, "model": "opus", "apiKeyHelper": "/bin/echo x",
            "mcpServers": {"x": {"headers": {"Authorization": "Bearer " + secret}}},
            "permissions": {"allow": ["Bash(git push*)"]}}))
        r = self.run_script("stage", "--kit", str(self.kit), "--answers", str(self._write("a.json", NO_GIT_ANSWERS)),
                            "--personal", str(self._write("p.md", NO_GIT_PERSONAL)), "--out", str(self.work / "st"))
        self.assertNotIn(secret[4:], r.stdout + r.stderr)
        info = json.loads(r.stdout)
        self.assertIn('env = "<hidden>"', info["dropped"])
        self.assertIn('model = "opus"', info["dropped"])
        self.assertIn('permissions.allow = ["Bash(git push*)"]', info["dropped"])
        self.assertIn('apiKeyHelper = "<hidden>"', info["dropped"])
        # A token the person put in their own overrides stays out of `show`, which still shows the hooks.
        over = {"env": {"API_TOKEN": secret}, "statusLine": None}
        r = self.run_script("stage", "--kit", str(self.kit), "--answers",
                            str(self._write("b.json", dict(NO_GIT_ANSWERS, overrides=over))),
                            "--personal", str(self.work / "p.md"), "--out", str(self.work / "st2"))
        shown = self.run_script("show", "--stage", str(self.work / "st2")).stdout
        self.assertNotIn(secret[4:], shown)
        self.assertIn("gotcha_hints.py", shown)
        # Kept by name, the token goes file to file: in the new settings, never in the output.
        r = self.run_script("stage", "--kit", str(self.kit), "--answers",
                            str(self._write("k.json", dict(NO_GIT_ANSWERS, keep=["env.GITHUB_TOKEN"]))),
                            "--personal", str(self.work / "p.md"), "--out", str(self.work / "st3"))
        self.assertNotIn(secret[4:], r.stdout)
        out = self.apply(self.work / "st3").stdout
        self.assertNotIn(secret[4:], out)
        self.assertEqual(self.settings()["env"], {"GITHUB_TOKEN": secret})
        self.assertNotIn("EDITOR", self.settings()["env"])
        self.assert_safe_defaults()
        r = self.run_script("stage", "--kit", str(self.kit), "--answers",
                            str(self._write("k2.json", dict(NO_GIT_ANSWERS, keep=["env.NOPE"]))),
                            "--personal", str(self.work / "p.md"), "--out", str(self.work / "st4"), ok=False)
        self.assertIn("not in your current settings.json", r.stderr)

    def test_no_bytecode_in_kit(self):
        self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.assertEqual([str(p) for p in self.kit.rglob("__pycache__")], [])

    def _write(self, name, obj) -> Path:
        p = self.work / name
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
        return p

    def test_refusals(self):
        r, _ = self.stage(dict(GIT_ANSWERS, plugins=["nope"]), GIT_PERSONAL, ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown plugin", r.stderr)
        r, _ = self.stage(dict(GIT_ANSWERS, overrides={"permissions": None}), GIT_PERSONAL, ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.home / ".claude").exists())
        (self.work / "a.json").write_text("{}")
        (self.work / "p.md").write_text("x")
        r = self.run_script("stage", "--kit", str(self.kit), "--answers", str(self.work / "a.json"),
                            "--personal", str(self.work / "p.md"), "--out", str(self.home / ".claude" / "x"), ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.home / ".claude").exists())


class TestFindKit(Scratch):
    def fake_claude(self, marketplaces: list, plugins: list = ()):
        f = self.bin / "claude"
        f.write_text("#!/bin/sh\n"
                     f"if [ \"$2\" = marketplace ]; then cat <<'EOF'\n{json.dumps(marketplaces)}\nEOF\n"
                     f"else cat <<'EOF'\n{json.dumps(list(plugins))}\nEOF\nfi\n")
        f.chmod(0o755)

    def find(self) -> dict:
        return json.loads(self.run_script("find-kit").stdout)

    def test_marketplace_copy(self):
        self.assertIsNone(self.find()["kit"])
        self.fake_claude([{"name": "other", "installLocation": str(self.work)},
                          {"name": "claude-kit", "source": "github", "installLocation": str(self.kit)}])
        d = self.find()
        self.assertEqual((d["kit"], d["how"]), (str(self.kit), "marketplace claude-kit"))
        self.assertTrue(d["repository"].startswith("https://"))

    def test_stale_copy(self):
        stale = self.work / "stale"
        (stale / "plugins" / "kit-setup" / ".claude-plugin").mkdir(parents=True)
        (stale / "plugins" / "kit-setup" / ".claude-plugin" / "plugin.json").write_text("{}")
        self.fake_claude([{"name": "claude-kit", "installLocation": str(stale)}])
        d = self.find()
        self.assertIsNone(d["kit"])
        self.assertEqual(d["stale"], [{"marketplace": "claude-kit", "path": str(stale)}])

    def test_earlier_install_wins(self):
        other = self.work / "other-kit"
        copy_kit(other)
        self.fake_claude([{"name": "claude-kit", "installLocation": str(other)}])
        _, stage = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.apply(stage)
        self.assertEqual(self.find()["kit"], str(self.kit))

    def test_switch_from_unusable_earlier_kit(self):
        """An earlier install from an older clone without kit-setup: find-kit says it passed it
        over, and the setup moves the profile and the shell line to the new kit, removing the old one."""
        old = self.home / "old-kit"
        copy_kit(old)
        shutil.rmtree(old / "plugins" / "kit-setup")
        me = self.home / ".claude" / "me"
        me.mkdir(parents=True)
        (me / "profile").write_text(f"kit = {old}\nshell = zsh\n")
        old_line = f'source "{old}/extras/zsh/claude-kit.zsh"'
        (self.home / ".zshrc").write_text(f"export A=1\n\n# Claude Code (claude-kit)\n{old_line}\n")
        self.fake_claude([{"name": "claude-kit", "installLocation": str(self.kit)}])
        d = self.find()
        self.assertEqual(d["kit"], str(self.kit))
        self.assertEqual(d["switched_from"], {"path": str(old), "state": "no"})
        info, stage = self.stage(dict(GIT_ANSWERS), GIT_PERSONAL)
        self.assertEqual(info["old_shell_lines"], {str(self.home / ".zshrc"): [old_line]})
        self.assertIn("kit = ~/src/claude-kit", (stage / "layer" / "profile").read_text())
        self.apply(stage)
        rc = (self.home / ".zshrc").read_text()
        self.assertNotIn(old_line, rc)
        self.assertIn('source "$HOME/src/claude-kit/extras/zsh/claude-kit.zsh"', rc)
        self.assertIn("export A=1", rc)
        self.assertEqual([b.read_text().count(old_line) for b in self.home.glob(".zshrc.bak-*")], [1])
        self.assertEqual(self.find()["kit"], str(self.kit))
        self.assert_equals_render()

    def test_duplicates(self):
        self.fake_claude([{"name": "claude-kit", "installLocation": str(self.kit)}],
                         [{"id": "start-task@claude-kit"}, {"id": "kit-setup@claude-kit"},
                          {"id": "speaker-prep@claude-kit"}, {"id": "start-task@elsewhere"}])
        info, _ = self.stage(NO_GIT_ANSWERS, NO_GIT_PERSONAL)
        self.assertEqual(info["duplicates"], ["start-task@claude-kit"])


class TestProfileText(unittest.TestCase):
    def test_set_key(self):
        text = "# a profile\n# shell = zsh\nplugins = a\n"
        self.assertEqual(ks.set_key(text, "shell", "none"), "# a profile\nshell = none\nplugins = a\n")
        self.assertEqual(ks.set_key(text, "plugins", "b c"), "# a profile\n# shell = zsh\nplugins = b c\n")
        self.assertEqual(ks.set_key(text, "plugins", None), "# a profile\n# shell = zsh\n# plugins = a\n")
        self.assertEqual(ks.set_key(text, "papercuts", "~/p #1"), text + 'papercuts = "~/p #1"\n')


if __name__ == "__main__":
    unittest.main()
