"""Tests for the setup check.

    python3 -m unittest discover plugins/setup-check/tests

The end-to-end tests copy the kit into a scratch HOME as a git repo, run its install.sh there and
run the check against that HOME, never the real one. The npm lookup reads a file:// URL; the kit
copy has no origin, so nothing here touches the network.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[3]
SCRIPT_REL = "plugins/setup-check/skills/setup-check/scripts/setup_check.py"
sys.path.insert(0, str(KIT / Path(SCRIPT_REL).parent))
import setup_check as sc  # noqa: E402

DROP = ("CLAUDE_CODE_EXECPATH", "CLAUDE_PLUGIN_ROOT", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL", "ZDOTDIR",
        "GOTCHAS_FILE", "CLAUDECODE", "SETUP_CHECK_DIST_TAGS_URL", "SETUP_CHECK_NO_REFRESH")
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
SECRET = "ghp_" + "Zx9" * 12


def copy_kit(dest: Path):
    """The kit's tracked and new files, as a fresh one-commit git repo."""
    r = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=KIT, capture_output=True, check=True)
    dest.mkdir(parents=True)
    for f in filter(None, r.stdout.split(b"\0")):
        src = KIT / f.decode()
        if src.is_file() and src.name != "CLAUDE.local.md":
            (dest / f.decode()).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / f.decode())
    env = dict(os.environ, **GIT_ID)
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "kit"]):
        subprocess.run(["git", *cmd], cwd=dest, check=True, env=env, capture_output=True)


class Units(unittest.TestCase):
    def test_older(self):
        self.assertTrue(sc.older("2.1.330", "2.1.332"))
        self.assertFalse(sc.older("2.1.332", "2.1.332"))
        self.assertFalse(sc.older("2.10.0", "2.9.9"))
        self.assertIsNone(sc.older(None, "1.0"))
        self.assertTrue(sc.older("abc", "def"))

    def test_redact(self):
        for s in (f"token={SECRET}", f"Bearer {SECRET}", f"MY_KEY={SECRET}", f"x {SECRET} y",
                  "sk-" + "a1" * 15, "AKIA" + "B2" * 8):
            self.assertNotIn(SECRET[4:], sc.redact(s))
            self.assertIn("…", sc.redact(s))
        self.assertEqual(sc.redact("mcp__claude_ai_Gmail__send_message"), "mcp__claude_ai_Gmail__send_message")

    def test_ignore(self):
        e = sc.ignore_entries("intro\n- `agents/x.md` — why (2026-01-01)\n- no backticks\n")
        self.assertEqual(e, ["agents/x.md"])
        self.assertTrue(sc.ignored("agents/x.md: a file here", e))
        self.assertFalse(sc.ignored("agents/x.mdx: a file here", e))

    def test_warning(self):
        ok = sc.row("cli", "Claude Code", "ok", "2.1.332", "2.1.332")
        self.assertIsNone(sc.warning([ok], 0))
        self.assertIsNone(sc.warning([sc.row("cli-update", "x", "failed")], 0))
        rows = [sc.row("cli", "Claude Code", "behind", "2.1.330", "2.1.332"),
                sc.row("plugin:a@m", "plugin a@m", "behind"), sc.row("plugin:b@m", "plugin b@m", "behind"),
                sc.row("kit", "claude-kit", "behind")]
        w = sc.warning(rows, 3)
        self.assertEqual(w.count("\n"), 0)
        self.assertTrue(w.startswith("Setup check: Claude Code 2.1.330 is behind 2.1.332; 2 plugins are behind;"), w)
        self.assertIn("3 setup items", w)

    def test_changes(self):
        prev = {"rows": [sc.row("cli", "Claude Code", "behind", "2.1.330", "2.1.332")], "drift": ["a: x", "b: y"]}
        cur = {"rows": [sc.row("cli", "Claude Code", "ok", "2.1.332", "2.1.332")], "drift": ["b: y", "c: z"]}
        ch = sc.changes(prev, cur)
        self.assertIn("Claude Code: 2.1.330 → 2.1.332", ch)
        self.assertIn("Claude Code: caught up", ch)
        self.assertIn("new drift: c: z", ch)
        self.assertIn("drift resolved: a: x", ch)
        self.assertEqual(sc.changes(None, cur), [])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        self.home = Path(tempfile.mkdtemp(prefix="setup-check-")).resolve()
        self.kit = self.home / "src" / "claude-kit"
        copy_kit(self.kit)
        self.tags = self.home / "dist-tags.json"
        self.tags.write_text(json.dumps({"latest": "2.1.332", "stable": "2.1.326"}))
        self.env = {k: v for k, v in os.environ.items() if k not in DROP}
        self.env.update(GIT_ID, HOME=str(self.home), SHELL="/bin/zsh",
                        SETUP_CHECK_DIST_TAGS_URL=self.tags.as_uri(),
                        CLAUDE_CODE_EXECPATH=str(self.home / "versions" / "2.1.332"))
        r = subprocess.run([str(self.kit / "install.sh"), "--skip-repos"], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.claude = self.home / ".claude"
        self.script = self.kit / SCRIPT_REL

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def check(self, *args, env=None):
        r = subprocess.run([sys.executable, "-I", str(self.script), *args], env=env or self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def data(self, *args):
        return json.loads(self.check("report", "--json", *args))

    def hook(self, sid="s1", env=None):
        e = dict(env or self.env, SETUP_CHECK_NO_REFRESH="1")
        start = time.monotonic()
        r = subprocess.run(["/bin/sh", "-c", self.hook_command()], input=json.dumps(
            {"session_id": sid, "source": "startup", "hook_event_name": "SessionStart", "cwd": str(self.home)}),
            env=e, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return r.stdout, time.monotonic() - start

    def hook_command(self):
        s = json.loads((self.claude / "settings.json").read_text())
        cmds = [h["command"] for g in s["hooks"]["SessionStart"] if g.get("matcher") == "startup" for h in g["hooks"]]
        self.assertEqual(len(cmds), 1)
        self.assertIn("setup_check.py", cmds[0])
        return cmds[0]

    def rows(self, snap):
        return {r["key"]: r for r in snap["rows"]}

    def test_fresh_install_is_clean(self):
        stamp = json.loads((self.claude / "kit-install.json").read_text())
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.kit, capture_output=True, text=True).stdout.strip()
        self.assertEqual(stamp["commit"], head)
        self.assertFalse(stamp["dirty"])
        self.assertTrue((self.claude / "skills" / "setup-check" / "SKILL.md").is_file())
        snap = self.data()["snapshot"]
        rows = self.rows(snap)
        self.assertEqual(rows["cli"]["state"], "ok")
        self.assertEqual(rows["kit"]["state"], "ok")
        self.assertEqual(snap["drift"], [])
        self.assertEqual(snap["drift_notes"], [])
        self.assertEqual(self.hook()[0], "")
        out = self.check()
        self.assertIn("Drift: what ~/.claude holds", out)
        self.assertIn("  none", out)

    def test_each_problem_reported(self):
        self.data()  # the first snapshot, to report changes against
        # A stray link, a hand-edited setting holding a secret, and the kit one commit ahead.
        stray = self.home / "elsewhere" / "stray"
        stray.mkdir(parents=True)
        (stray / "SKILL.md").write_text("x")
        (self.claude / "skills" / "stray").symlink_to(stray)
        s = json.loads((self.claude / "settings.json").read_text())
        s["env"] = {"MY_TOKEN": SECRET}
        s["permissions"]["ask"].append(f"Bash(curl -H 'Authorization: Bearer {SECRET}' *)")
        (self.claude / "settings.json").write_text(json.dumps(s))
        (self.kit / "NEWS").write_text("x")
        subprocess.run(["git", "add", "NEWS"], cwd=self.kit, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "next"], cwd=self.kit, check=True, env=self.env)
        # An older CLI with a failed auto-update, and a plugin behind its marketplace copy.
        env = dict(self.env, CLAUDE_CODE_EXECPATH=str(self.home / "versions" / "2.1.330"))
        (self.claude / ".last-update-result.json").write_text(json.dumps(
            {"timestamp": "2026-01-01T00:00:00Z", "outcome": "failed", "status": "install_failed",
             "version_from": "2.1.330", "version_to": None}))
        market = self.home / "market"
        (market / ".claude-plugin").mkdir(parents=True)
        (market / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
            {"name": "m", "plugins": [{"name": "p", "version": "1.2.0", "source": "./p"}]}))
        (self.claude / "plugins").mkdir(exist_ok=True)
        (self.claude / "plugins" / "known_marketplaces.json").write_text(json.dumps(
            {"m": {"installLocation": str(market), "lastUpdated": "2026-01-01T00:00:00Z"}}))
        (self.claude / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"p@m": [{"scope": "user", "version": "1.0.0"}]}}))

        r = subprocess.run([sys.executable, "-I", str(self.script), "report"], env=env,
                           capture_output=True, text=True, timeout=60)
        out = r.stdout
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(SECRET[4:], out)
        self.assertNotIn(SECRET[4:], (self.claude / "setup-check" / "snapshot.json").read_text())
        self.assertIn("BEHIND  Claude Code: 2.1.330, the latest channel has 2.1.332", out)
        self.assertIn("FAILED  Claude Code auto-update", out)
        self.assertIn("BEHIND  plugin p@m: 1.0.0, its marketplace copy", out)
        self.assertIn("BEHIND  claude-kit: settings built from", out)
        self.assertIn("1 commit ahead", out)
        self.assertIn("skills/stray: a link to something the kit and your personal layer don't track", out)
        self.assertIn("settings.json: env is set here", out)
        self.assertIn("settings.json: permissions.ask has Bash(curl -H 'Authorization: …", out)
        self.assertIn("plugin p@m: installed for the user", out)
        self.assertIn("marketplace m: known here", out)
        self.assertIn("new drift: skills/stray", out)
        self.assertIn("claude-kit: the kit checkout moved", out)
        for fix in ("claude update", "/plugin update p@m", "install.sh"):
            self.assertIn(fix, out)

        line, took = self.hook(env=env)
        msg = json.loads(line)
        self.assertEqual(msg["systemMessage"].count("\n"), 0)
        self.assertTrue(msg["systemMessage"].startswith("Setup check: Claude Code 2.1.330 is behind 2.1.332; 1 plugin is behind;"))
        self.assertIn("/setup-check", msg["systemMessage"])
        self.assertEqual(msg["hookSpecificOutput"]["additionalContext"], msg["systemMessage"])
        self.assertNotIn(SECRET[4:], line)
        self.assertLess(took, 5)
        self.assertEqual(self.hook(env=env)[0], "", "a second hook in the same session stays quiet")
        self.assertNotEqual(self.hook("s2", env=env)[0], "")

        # Catching up clears it: the hook re-reads the running version without a new lookup.
        (self.claude / "skills" / "stray").unlink()
        self.data("--offline")
        out, _ = self.hook("s3")
        msg = json.loads(out)["systemMessage"]
        self.assertNotIn("Claude Code", msg)
        self.assertIn("1 plugin is behind", msg)

    def test_ignore_list(self):
        (self.claude / "agents").mkdir()
        (self.claude / "agents" / "x.md").write_text("x")
        (self.claude / "agents" / "y.md").write_text("y")
        (self.claude / "me" / "drift-ignore.md").write_text("- `agents/x.md` — another tool's (2026-01-01)\n")
        snap = self.data()["snapshot"]
        self.assertEqual(snap["drift"], ["agents/y.md: a file here, not a link into the kit or your personal layer"])
        self.assertEqual(snap["drift_ignored"], 1)

    def test_hook_offline_and_without_snapshot(self):
        env = dict(self.env, SETUP_CHECK_DIST_TAGS_URL="http://127.0.0.1:9/none", http_proxy="http://127.0.0.1:9")
        out, took = self.hook(env=env)
        self.assertEqual(out, "")
        self.assertLess(took, 5)
        # Offline, the report still runs and says the latest isn't known.
        out = self.check("report", "--offline", env=env)
        self.assertIn("Latest versions not known yet", out)
        self.assertIn("?       Claude Code", out)

    def test_hook_starts_a_refresh(self):
        env = {k: v for k, v in self.env.items() if k != "SETUP_CHECK_NO_REFRESH"}
        r = subprocess.run(["/bin/sh", "-c", self.hook_command()], input="{}", env=env,
                           capture_output=True, text=True, timeout=10)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        snap, deadline = self.claude / "setup-check" / "snapshot.json", time.monotonic() + 30
        while not snap.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertTrue(snap.exists(), "the background refresh wrote no snapshot")
        self.assertEqual(json.loads(snap.read_text())["latest"]["cli"]["latest"], "2.1.332")
        # A snapshot over a day old is refreshed by the next session's hook.
        old = json.loads(snap.read_text())
        stale = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat()
        old["checked_at"] = stale
        snap.write_text(json.dumps(old))
        subprocess.run(["/bin/sh", "-c", self.hook_command()], input="{}", env=env, capture_output=True, text=True,
                       timeout=10)
        deadline = time.monotonic() + 30
        while (sc.read_snapshot(self.home) or {}).get("checked_at") == stale and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertNotEqual(sc.read_snapshot(self.home)["checked_at"], stale)

    def test_unstamped_install(self):
        (self.claude / "kit-install.json").unlink()
        snap = self.data()["snapshot"]
        self.assertEqual(self.rows(snap)["kit"]["state"], "unknown")
        self.assertIn("installed before install.sh recorded its profile", snap["drift_notes"][0])
        self.assertEqual(self.hook()[0], "", "an unknown kit version alone doesn't warn")

    def test_no_kit_install(self):
        h = self.home / "bare"
        (h / ".claude").mkdir(parents=True)
        env = dict(self.env, HOME=str(h))
        snap = json.loads(self.check("report", "--json", env=env))["snapshot"]
        self.assertNotIn("kit", self.rows(snap))
        self.assertEqual(snap["drift"], [])


if __name__ == "__main__":
    unittest.main()
