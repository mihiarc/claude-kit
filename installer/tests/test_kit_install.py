"""Tests for installer/kit_install.py and the shell files install.sh sources.

    python3 -m unittest discover installer/tests

The end-to-end tests copy the kit into a scratch HOME and run install.sh there, never in
the real HOME. They run once per shell (zsh, bash) that is installed.
"""
import hashlib
import json
import os
import pty
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT / "installer"))
import kit_install as ki  # noqa: E402

CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL", "ZDOTDIR", "GOTCHAS_FILE", "CLAUDECODE")}
# The setup-check hook starts no background lookup (network) in a test HOME.
CLEAN_ENV["SETUP_CHECK_NO_REFRESH"] = "1"


class ScratchHome(unittest.TestCase):
    """HOME points at a fresh temp folder for each test."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="kit-install-")).resolve()
        self._old = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        os.environ["HOME"] = self._old
        shutil.rmtree(self.home, ignore_errors=True)

    def profile(self, text: str) -> Path:
        p = self.home / "layer" / "profile"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p


class TestProfile(ScratchHome):
    def test_parse(self):
        self.assertEqual(ki.parse_profile("# c\n\nme = ~/x\nshell='zsh'\nplugins =\n"), {"me": "~/x", "shell": "zsh"})
        self.assertEqual(ki.parse_profile("me = ~/x   # mine\nshell = zsh# not a comment\nplugins = # all\n"),
                         {"me": "~/x", "shell": "zsh# not a comment"})
        self.assertEqual(ki.parse_profile('me = "~/a # b"  # c\n'), {"me": "~/a # b"})
        for bad in ("nokey\n", "colour = red\n", "me = a\nme = b\n", 'me = "a\n', 'me = "a" b\n'):
            with self.assertRaises(ki.ProfileError, msg=bad):
                ki.parse_profile(bad)

    def test_defaults(self):
        c = ki.resolve(None)
        self.assertEqual(c["me"], self.home / ".claude" / "me")
        self.assertEqual(c["plugins"], ki.DEFAULT_PLUGINS)
        self.assertEqual(c["gotchas"], self.home / ".claude" / "gotchas.md")
        self.assertIsNone(c["settings"])
        self.assertIsNone(c["papercuts"])
        self.assertIsNone(c["repos"])

    def test_paths(self):
        p = self.profile("me = .\nsettings = s.json\nrepos_dir = $HOME/src\nrepos = r.txt\ngotchas = ~/g.md\n")
        (p.parent / "s.json").write_text("{}")
        c = ki.resolve(p)
        self.assertEqual(c["me"], p.parent)
        self.assertEqual(c["settings"], p.parent / "s.json")
        self.assertEqual(c["repos_dir"], self.home / "src")
        self.assertEqual(c["repos"], p.parent / "r.txt")
        self.assertEqual(c["gotchas"], self.home / "g.md")

    def test_own_settings_found_in_layer(self):
        p = self.profile("me = .\n")
        (p.parent / "settings.overrides.json").write_text("{}")
        self.assertEqual(ki.resolve(p)["settings"], p.parent / "settings.overrides.json")

    def test_plugins(self):
        self.assertEqual(ki.resolve(self.profile("plugins = all\n"))["plugins"], ki.all_plugins())
        self.assertEqual(ki.resolve(self.profile("plugins = papercuts, start-task papercuts\n"))["plugins"],
                         ["papercuts", "start-task"])
        with self.assertRaises(ki.ProfileError):
            ki.resolve(self.profile("plugins = no-such-plugin\n"))

    def test_errors(self):
        for text in ("kit = /somewhere/else\n", "settings = missing.json\n", "repos = r.txt\n",
                     "shell = fish\n", "me = ~/my layer\n", "me = ~/.claude\n", "me = ~\n", "me = ~/.claude/\n",
                     "shell_file = ~/$(touch x).sh\n", 'shell_file = ~/a"b.sh\n', "shell_file = ~/a`b`.sh\n"):
            with self.assertRaises(ki.ProfileError, msg=text):
                ki.resolve(self.profile(text))
        ki.resolve(self.profile(f"kit = {KIT}\nme = ~/.claude/me\nshell_file = ~/my-shell.zsh\n"))

    def test_shell_from_login_shell(self):
        for login, want in (("/bin/zsh", "zsh"), ("/usr/local/bin/bash", "bash"), ("/usr/bin/fish", "none"), ("", "none")):
            os.environ["SHELL"] = login
            self.assertEqual(ki.resolve(None)["shell"], want, login)


def random_json(r: random.Random, depth=0):
    kind = r.choice(["s", "n", "b", "l", "d"] if depth < 3 else ["s", "n", "b"])
    if kind == "s":
        return r.choice(["a", "b", "c", "Bash(git push:*)"])
    if kind == "n":
        return r.randint(0, 3)
    if kind == "b":
        return r.choice([True, False])
    if kind == "l":
        return [random_json(r, depth + 1) for _ in range(r.randint(0, 3))]
    return {r.choice("pqrs"): random_json(r, depth + 1) for _ in range(r.randint(0, 3))}


def leaves(obj, path=()):
    """(path, list item) for every item of every list, and (path, scalar) for every scalar."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, path + (k,))
    elif isinstance(obj, list):
        for x in obj:
            yield path, json.dumps(x, sort_keys=True)
    else:
        yield path, json.dumps(obj)


class TestMerge(unittest.TestCase):
    def test_rules(self):
        base = {"a": 1, "p": {"allow": ["x"], "ask": ["y"]}, "h": {"E": [{"m": 1}]}, "gone": 1}
        over = {"a": 2, "p": {"allow": ["z", "x"]}, "h": {"E": [{"m": 2}, {"m": 1}]}, "gone": None, "new": [1]}
        self.assertEqual(ki.merge(base, over), {
            "a": 2, "p": {"allow": ["x", "z"], "ask": ["y"]}, "h": {"E": [{"m": 1}, {"m": 2}]}, "new": [1]})
        self.assertEqual(base["p"]["allow"], ["x"], "base was changed")
        self.assertEqual(ki.merge({"a": {"b": 1}}, {"a": {"b": None}}), {"a": {}})
        self.assertEqual(ki.merge({"statusLine": {"x": 1}}, {"statusLine": None}), {})
        self.assertEqual(ki.merge({"a": "x"}, {"a": 2}), {"a": 2})
        # A type the base doesn't have, or removing a base permission rule or hook, fails closed.
        for base, over in (({"a": [1]}, {"a": {"b": 1}}), ({"a": [1]}, {"a": "s"}), ({"a": {}}, {"a": 1}),
                           ({"permissions": {"ask": ["x"]}}, {"permissions": {"ask": None}}),
                           ({"permissions": {"ask": ["x"]}}, {"permissions": None}),
                           ({"permissions": {"ask": ["x"]}}, {"permissions": {"ask": "y"}}),
                           ({"hooks": {"E": []}}, {"hooks": None}), ({"hooks": {"E": []}}, {"hooks": {"E": None}})):
            with self.assertRaises(ki.ProfileError, msg=over):
                ki.merge(base, over)

    def test_override_shapes(self):
        for over in ([], {"permissions": []}, {"permissions": {"allow": "Bash(x)"}}, {"permissions": {"deny": [1]}},
                     {"hooks": {"Stop": {}}}, {"hooks": []}, {"env": {"A": 1}}):
            with self.assertRaises(ki.ProfileError, msg=over):
                ki.check_overrides(over, Path("o.json"))
        ki.check_overrides({"permissions": {"allow": ["Bash(x)"]}, "hooks": {"Stop": []}, "env": {"A": "1"}}, Path("o"))

    def test_dropped(self):
        old = {"model": "x", "theme": "dark", "enabledPlugins": {"a@b": True, "c@d": True},
               "hooks": {"Stop": [{"hooks": []}], "E": [1]}, "permissions": {"allow": ["Bash(ls)"], "ask": ["q"]}}
        new = {"theme": "light", "enabledPlugins": {"a@b": True}, "hooks": {"E": [1]}, "permissions": {"ask": ["q"]}}
        self.assertEqual(sorted(ki.dropped(old, new)), sorted([
            'model = "x"', 'theme = "dark" (now "light")', 'enabledPlugins.c@d = true',
            'hooks.Stop = [{"hooks": []}]', 'permissions.allow = ["Bash(ls)"]']))
        self.assertEqual(ki.dropped(new, new), [])

    def test_properties(self):
        r, merged = random.Random(4), 0
        for _ in range(10000):
            a, b = random_json(r), random_json(r)
            if not isinstance(a, dict) or not isinstance(b, dict):
                continue
            self.assertEqual(ki.merge(a, {}), a)
            self.assertEqual(ki.merge(a, a), a)
            try:
                m = ki.merge(a, b)
            except ki.ProfileError:
                continue  # a type the base doesn't have; test_rules checks that case
            merged += 1
            self.assertEqual(ki.merge(m, b), m, "merging the same overrides twice changes nothing")
            got = set(leaves(m))
            # Every override value is in the result.
            self.assertLessEqual(set(leaves(b)), got)
            # Every base list item is kept where the override also has a list there.
            for path, item in leaves(a):
                node_a, node_b = a, b
                for k in path:
                    node_a = node_a[k]
                    node_b = node_b.get(k) if isinstance(node_b, dict) else None
                if isinstance(node_a, list) and isinstance(node_b, list):
                    self.assertIn((path, item), got)
        self.assertGreater(merged, 200)

    def test_backups_never_overwrite(self):
        home = Path(tempfile.mkdtemp(prefix="kit-bak-")).resolve()
        old = os.environ["HOME"]
        os.environ["HOME"] = str(home)
        try:
            inst = ki.Installer(ki.resolve(None))
            inst.say = lambda *a: None
            inst.stamp = "20000101-000000"  # two runs in the same second
            f = home / "f"
            for text in ("first", "second", "third"):
                f.write_text(text)
                inst.taken.clear()
                inst.aside(f)
            baks = sorted(home.glob("f.bak-*"))
            self.assertEqual(sorted(b.read_text() for b in baks), ["first", "second", "third"])
            skill = home / ".claude" / "skills" / "s"
            skill.mkdir(parents=True)
            inst.aside(skill)
            self.assertEqual(list((home / ".claude" / "skills").iterdir()), [])
            self.assertTrue((home / ".claude" / "kit-backups" / "skills" / "s.bak-20000101-000000").is_dir())
        finally:
            os.environ["HOME"] = old
            shutil.rmtree(home, ignore_errors=True)


class TestRender(ScratchHome):
    def test_newcomer_settings(self):
        s = json.loads(ki.render_settings(ki.resolve(None)))
        text = json.dumps(s)
        for ph in ("__KIT__", "__ME__", "__HOME__"):
            self.assertNotIn(ph, text)
        self.assertNotIn("allow", s.get("permissions", {}))
        for k in ("model", "effortLevel", "env"):
            self.assertNotIn(k, s)
        self.assertNotIn("defaultMode", s["permissions"])
        self.assertIn(str(KIT) + "/plugins/papercuts/hooks/gotcha_hints.py", text)

    def test_overrides_and_gotchas(self):
        p = self.profile("me = .\ngotchas = g.md\n")
        (p.parent / "settings.overrides.json").write_text(json.dumps({
            "model": "opus", "env": {"X": "__ME__/x"},
            "permissions": {"allow": ["Bash(git push:*)"], "ask": ["Bash(git push --force*)", "mine"]},
            "statusLine": None}))
        s = json.loads(ki.render_settings(ki.resolve(p)))
        self.assertEqual(s["model"], "opus")
        self.assertEqual(s["env"], {"GOTCHAS_FILE": str(p.parent / "g.md"), "X": f"{p.parent}/x"})
        self.assertEqual(s["permissions"]["allow"], ["Bash(git push:*)"])
        ask = s["permissions"]["ask"]
        self.assertEqual(ask.count("Bash(git push --force*)"), 1)
        self.assertEqual(ask[-1], "mine")
        self.assertNotIn("statusLine", s)

    def test_claude_md(self):
        p = self.profile("me = .\n")
        md = ki.render_claude_md(ki.resolve(p))
        self.assertEqual(md.splitlines()[:2], [f"@{ki.tilde(KIT)}/starter/core.md", "@~/layer/CLAUDE.md"])
        self.assertNotIn("__KIT__", md)
        self.assertNotIn("__ME__", md)


def tree(root: Path) -> dict:
    """Every path under root: a link's target or a file's hash."""
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = Path(d) / n
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = "-> " + os.readlink(p)
            elif p.is_file():
                out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


SKIP_COPY = shutil.ignore_patterns(".git", "__pycache__", ".DS_Store", "CLAUDE.local.md", "worktrees", "*.bak-*")


def install_kit(home: Path, use_git: bool = True) -> Path:
    """Copy the kit into home/src/claude-kit as a clone would have it: its tracked and new files
    from a git checkout, or the whole tree less caches and local files from a plain copy."""
    dest = home / "src" / "claude-kit"
    r = (subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=KIT, capture_output=True)
         if use_git and shutil.which("git") else None)
    if r is None or r.returncode != 0:
        shutil.copytree(KIT, dest, ignore=SKIP_COPY)
        return dest
    dest.mkdir(parents=True)
    for f in filter(None, r.stdout.split(b"\0")):
        src = KIT / f.decode()
        if src.is_file() and src.name != "CLAUDE.local.md":
            (dest / f.decode()).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / f.decode())
    return dest


class EndToEnd:
    shell = ""

    def setUp(self):
        if not shutil.which(self.shell):
            self.skipTest(f"{self.shell} not installed")
        self.home = Path(tempfile.mkdtemp(prefix=f"kit-e2e-{self.shell}-")).resolve()
        self.kit = install_kit(self.home)
        self.env = dict(CLEAN_ENV, HOME=str(self.home), SHELL=f"/bin/{self.shell}")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def install(self, *args, ok=True):
        r = subprocess.run([str(self.kit / "install.sh"), *args], env=self.env, capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def rc(self) -> Path:
        return self.home / (".zshrc" if self.shell == "zsh" else ".bashrc")

    def test_second_run_changes_nothing(self):
        self.install("--skip-repos")
        first = tree(self.home)
        out = self.install("--skip-repos").stdout
        self.assertEqual(tree(self.home), first)
        self.assertFalse([k for k in first if ".bak-" in k])
        for verb in ("wrote ", "linked ", "backed up", "appended", "ignored"):
            self.assertNotIn(verb, out)

    def test_newcomer_result(self):
        self.install()
        c = self.home / ".claude"
        md = (c / "CLAUDE.md").read_text().splitlines()
        self.assertEqual(md[:2], ["@~/src/claude-kit/starter/core.md", "@~/.claude/me/CLAUDE.md"])
        self.assertTrue((c / "me" / "CLAUDE.md").is_file())
        self.assertTrue((c / "me" / "profile").is_file())
        self.assertEqual((c / "gotchas.md").read_text(), (self.kit / "starter" / "gotchas.md").read_text())
        links = sorted(p.name for p in (c / "skills").iterdir())
        self.assertEqual(links, sorted(["start-task", "chief-of-staff", "verify-setup", "papercut-sweep", "setup-check"]))
        stamp = json.loads((c / "kit-install.json").read_text())
        self.assertEqual((stamp["kit"], stamp["me"], stamp["profile"]),
                         (str(self.kit), str(c / "me"), str(c / "me" / "profile")))
        for l in (c / "skills").iterdir():
            self.assertTrue((l / "SKILL.md").is_file(), l)
        s = json.loads((c / "settings.json").read_text())
        perms = s.get("permissions", {})
        allow = " ".join(perms.get("allow", []))
        self.assertNotIn("git push", allow)
        self.assertNotIn("gh pr merge", allow)
        for k in ("model", "effortLevel"):
            self.assertNotIn(k, s)
        self.assertNotIn("defaultMode", perms)
        gi = (self.home / ".config" / "git" / "ignore").read_text().splitlines()
        self.assertLessEqual(set(ki.GITIGNORE), set(gi))

    def test_hooks_idle(self):
        """Each hook in the installed settings exits 0 and says nothing on an ordinary call."""
        self.install()
        s = json.loads((self.home / ".claude" / "settings.json").read_text())
        events = {
            "PreToolUse": {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            "PostToolUse": {"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": ""}},
            "PostToolUseFailure": {"tool_name": "Bash", "tool_input": {"command": "ls"}, "error": "boom"},
            "SessionStart": {"source": "compact"},
        }
        ran = 0
        for event, groups in s["hooks"].items():
            for g in groups:
                for h in g["hooks"]:
                    payload = dict(events[event], hook_event_name=event, session_id="t", cwd=str(self.home))
                    r = subprocess.run(["/bin/sh", "-c", h["command"]], input=json.dumps(payload),
                                       env=self.env, capture_output=True, text=True, timeout=60)
                    self.assertEqual(r.returncode, 0, (h["command"], r.stderr))
                    if event != "SessionStart":
                        self.assertEqual(r.stdout + r.stderr, "", h["command"])
                    ran += 1
        self.assertGreaterEqual(ran, 5)

    def test_shell(self):
        self.install()
        rc = self.rc()
        line = f'source "$HOME/src/claude-kit/extras/{self.shell}/claude-kit.{self.shell}"'
        self.assertIn(line, rc.read_text().splitlines())
        self.assertEqual(subprocess.run([self.shell, "-n", str(rc)], env=self.env).returncode, 0)
        probe = ("source ~/.zshrc; whence -w claude" if self.shell == "zsh"
                 else "source ~/.bashrc; type -t claude")
        flags = ["-fc"] if self.shell == "zsh" else ["--norc", "-c"]
        out = subprocess.run([self.shell, *flags, probe], env=self.env, capture_output=True, text=True).stdout
        self.assertIn("function", out)

    def test_existing_files_backed_up(self):
        c = self.home / ".claude"
        c.mkdir()
        (c / "settings.json").write_text(json.dumps({"model": "x", "permissions": {"allow": ["Bash(ls)"]},
                                                     "enabledPlugins": {"p@m": True}}))
        (c / "CLAUDE.md").write_text("my own rules\n")
        out = self.install().stdout
        baks = sorted(p.name.split(".bak-")[0] for p in c.glob("*.bak-*"))
        self.assertEqual(baks, ["CLAUDE.md", "settings.json"])
        for line in ('model = "x"', 'permissions.allow = ["Bash(ls)"]', "enabledPlugins = "):
            self.assertIn(line, out)
        self.assertIn("add them to ~/.claude/me/settings.overrides.json", out)
        # The old CLAUDE.md's rules become the personal layer's file, which the new one imports.
        self.assertEqual((c / "me" / "CLAUDE.md").read_text(), "my own rules\n")
        self.assertIn("is now ~/.claude/me/CLAUDE.md", out)

    def test_old_claude_md_kept_when_layer_has_one(self):
        c = self.home / ".claude"
        (c / "me").mkdir(parents=True)
        (c / "me" / "CLAUDE.md").write_text("layer\n")
        (c / "CLAUDE.md").write_text("old\n")
        out = self.install().stdout
        self.assertEqual((c / "me" / "CLAUDE.md").read_text(), "layer\n")
        self.assertEqual([p.read_text() for p in c.glob("CLAUDE.md.bak-*")], ["old\n"])
        self.assertIn("Your previous ~/.claude/CLAUDE.md is at ~/.claude/CLAUDE.md.bak-", out)

    def test_own_skill_moved_outside_skills(self):
        own = self.home / ".claude" / "skills" / "start-task"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text("mine")
        self.install()
        skills = sorted(p.name for p in (self.home / ".claude" / "skills").iterdir())
        self.assertFalse([s for s in skills if ".bak-" in s], skills)
        baks = list((self.home / ".claude" / "kit-backups" / "skills").iterdir())
        self.assertEqual([(b / "SKILL.md").read_text() for b in baks], ["mine"])

    def test_bad_overrides_write_nothing(self):
        layer = self.home / "layer"
        layer.mkdir()
        (layer / "profile").write_text("me = .\n")
        for bad in ({"permissions": {"ask": None}}, {"permissions": None}, {"permissions": {"allow": "Bash(x)"}},
                    {"hooks": None}, {"statusLine": "x"}, "[]", "{not json"):
            (layer / "settings.overrides.json").write_text(bad if isinstance(bad, str) else json.dumps(bad))
            r = self.install("--profile", str(layer / "profile"), ok=False)
            self.assertEqual(r.returncode, 1, (bad, r.stdout, r.stderr))
            self.assertIn("settings overrides", r.stderr)
            self.assertEqual(sorted(p.name for p in layer.iterdir()), ["profile", "settings.overrides.json"], bad)
            self.assertFalse((self.home / ".claude").exists(), bad)

    def test_profile_changes(self):
        layer = self.home / "layer"
        layer.mkdir()
        (layer / "settings.overrides.json").write_text(json.dumps({"model": "opus"}))
        (layer / "repos.txt").write_text("# a comment\n\n")
        (layer / "rc.sh").write_text("true\n")
        (layer / "profile").write_text(
            f"me = .\nplugins = all\nshell_file = rc.sh\npapercuts = pc.md\ngotchas = g.md\n"
            f"repos_dir = ~/code\nrepos = repos.txt\n")
        self.install("--profile", str(layer / "profile"))
        c = self.home / ".claude"
        s = json.loads((c / "settings.json").read_text())
        self.assertEqual(s["model"], "opus")
        self.assertEqual(s["env"]["GOTCHAS_FILE"], str(layer / "g.md"))
        self.assertTrue((layer / "pc.md").is_file() and (layer / "g.md").is_file())
        self.assertFalse((c / "me").exists())
        self.assertEqual((c / "CLAUDE.md").read_text().splitlines()[1], "@~/layer/CLAUDE.md")
        self.assertIn('source "$HOME/layer/rc.sh"', self.rc().read_text())
        n_all = len(list((c / "skills").iterdir()))
        self.assertGreater(n_all, 4)
        # Narrowing the plugin set removes the other kit links and leaves a link of the person's own.
        (c / "skills" / "own").symlink_to(layer)
        (layer / "profile").write_text("me = .\nplugins = papercuts\n")
        self.install("--profile", str(layer / "profile"))
        self.assertEqual(sorted(p.name for p in (c / "skills").iterdir()), ["own", "papercut-sweep"])

    def test_dry_run(self):
        r = self.install("--dry-run")
        self.assertEqual(tree(self.home).keys() - {k for k in tree(self.home) if k.startswith("src/")}, set())
        # Each planned change reads "would <verb> <path>": the verb in its plain form, then a space.
        planned = [l for l in r.stdout.splitlines() if l.startswith("would ")]
        self.assertTrue(planned)
        for line in planned:
            self.assertRegex(line, r"^would (write|link|unlink|back up|ignore|append|clone) +\S")

    def test_bad_profile(self):
        p = self.home / "profile"
        p.write_text("colour = red\n")
        r = self.install("--profile", str(p), ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown key", r.stderr)
        self.assertFalse((self.home / ".claude").exists())


class TestZsh(EndToEnd, unittest.TestCase):
    shell = "zsh"


class TestBash(EndToEnd, unittest.TestCase):
    shell = "bash"


class TestKitCopy(unittest.TestCase):
    def test_plain_copy(self):
        """The end-to-end tests also run from a kit that isn't a git checkout."""
        home = Path(tempfile.mkdtemp(prefix="kit-copy-")).resolve()
        try:
            dest = install_kit(home, use_git=False)
            self.assertTrue((dest / "install.sh").is_file() and (dest / "starter" / "settings.json").is_file())
            self.assertFalse((dest / ".git").exists() or list(dest.rglob("__pycache__")))
        finally:
            shutil.rmtree(home, ignore_errors=True)


class TestNamesPort(unittest.TestCase):
    """extras/bash/claude-names.bash names sessions exactly as extras/zsh/claude-names.zsh does."""

    ARGS = [[], ["do the thing"], ["-w", "feat"], ["--worktree", "feat", "x"], ["--worktree=feat"], ["-w"],
            ["-w", "--model", "x"], ["-w", "a", "--worktree=b"], ["--worktree=b", "-w", "a"], ["--worktree="],
            ["-n", "x"], ["--name=x"], ["-c"], ["--resume=abc"], ["-p", "hi"], ["plugin", "list"], ["mcp"],
            ["--model", "opus", "-w", "t"], ["*", "a b"]]

    def setUp(self):
        for sh in ("zsh", "bash", "git"):
            if not shutil.which(sh):
                self.skipTest(f"{sh} not installed")
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-names-")).resolve()
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "claude").write_text('#!/bin/sh\nfor a in "$@"; do printf "%s|" "$a"; done > "$OUT"\n')
        (bin_ / "claude").chmod(0o755)
        self.env = dict(CLEAN_ENV, PATH=f"{bin_}:{os.environ['PATH']}", HOME=str(self.tmp))
        g = lambda *a, cwd: subprocess.run(["git", *a], cwd=cwd, env=self.env, check=True, capture_output=True)
        repo = self.tmp / "repo"
        repo.mkdir()
        g("init", "-q", cwd=repo)
        g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x", cwd=repo)
        g("worktree", "add", "-q", str(repo / ".claude" / "worktrees" / "task1"), cwd=repo)
        (self.tmp / "plain").mkdir()
        self.dirs = [repo, repo / ".claude" / "worktrees" / "task1", self.tmp / "plain"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_in(self, shell, cwd, args):
        out = self.tmp / "out"
        if out.exists():
            out.unlink()
        src = KIT / "extras" / shell / f"claude-kit.{shell}"
        flags = ["-fc"] if shell == "zsh" else ["--norc", "-c"]
        script = f'source "{src}"; cd "$1"; shift; claude "$@"'
        # A terminal on stdin and stdout, as in an interactive shell.
        mfd, sfd = pty.openpty()
        try:
            subprocess.run([shell, *flags, script, shell, str(cwd), *args], stdin=sfd, stdout=sfd,
                           stderr=subprocess.PIPE, env=dict(self.env, OUT=str(out)), timeout=20)
        finally:
            os.close(sfd)
            os.close(mfd)
        return out.read_text() if out.exists() else None

    def test_same_names(self):
        for cwd in self.dirs:
            for args in self.ARGS:
                z = self.run_in("zsh", cwd, args)
                b = self.run_in("bash", cwd, args)
                self.assertIsNotNone(z, (cwd, args))
                self.assertEqual(b, z, (cwd.name, args))
        # Spot checks of the convention itself.
        self.assertEqual(self.run_in("bash", self.dirs[0], []), "--name|repo|")
        self.assertEqual(self.run_in("bash", self.dirs[1], []), "--name|repo--task1|")
        self.assertEqual(self.run_in("bash", self.dirs[0], ["-w", "feat"]), "--name|repo--feat|-w|feat|")
        self.assertEqual(self.run_in("bash", self.dirs[2], ["-p", "x"]), "-p|x|")

    def test_kit_secret_on_path(self):
        """Sourcing the shell file puts extras/secrets/kit-secret on PATH, once however often it is sourced."""
        want = str((KIT / "extras" / "secrets" / "kit-secret").resolve())
        for shell in ("zsh", "bash"):
            src = KIT / "extras" / shell / f"claude-kit.{shell}"
            flags = ["-fc"] if shell == "zsh" else ["--norc", "-c"]
            script = (f'source "{src}"; source "{src}"; command -v kit-secret; '
                      'printf "%s\\n" "$PATH" | tr ":" "\\n" | grep -c "extras/secrets$"')
            r = subprocess.run([shell, *flags, script], env=self.env, capture_output=True, text=True, timeout=20)
            lines = r.stdout.split()
            self.assertEqual(lines[0], want, (shell, r.stderr))
            self.assertEqual(lines[1], "1", shell)

    def test_no_terminal_passes_through(self):
        out = self.tmp / "out"
        src = KIT / "extras" / "bash" / "claude-kit.bash"
        subprocess.run(["bash", "--norc", "-c", f'source "{src}"; claude a', "bash"],
                       env=dict(self.env, OUT=str(out)), capture_output=True, timeout=20)
        self.assertEqual(out.read_text(), "a|")


if __name__ == "__main__":
    unittest.main()
