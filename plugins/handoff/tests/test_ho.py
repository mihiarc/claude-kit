"""Tests for ho.py that need no live Claude Code session.

Run from the repo root: python3 -m unittest discover plugins/handoff/tests
"""
import contextlib, importlib.util, io, json, os, shlex, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HO = Path(__file__).resolve().parents[1] / "skills" / "handoff" / "scripts" / "ho.py"
spec = importlib.util.spec_from_file_location("ho", HO)
ho = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ho)

CLAUDE = 100
SNAP = "/bin/zsh -c source /home/u/.claude/shell-snapshots/snapshot-zsh-1-abc.sh 2>/dev/null || true && eval '{}' < /dev/null && pwd -P >| /tmp/claude-cwd"
OLD, YOUNG = 3 * 3600, 30


def table():
    """A session's process tree: what dies with it, what doesn't, and what is only a watcher."""
    return {
        CLAUDE: (50, OLD, "claude --name lane"),
        # direct children that aren't Bash-tool shells: MCP servers, a channel plugin, caffeinate
        101: (CLAUDE, OLD, "npm exec @playwright/mcp@latest"),
        102: (CLAUDE, OLD, "/usr/local/bin/bun /plugins/team-bus/src/channel.ts"),
        103: (CLAUDE, OLD, "caffeinate -i -t 300"),
        # a long projection: shell -> uv -> python, all old; only uv (the topmost) is named
        200: (CLAUDE, OLD, SNAP.format("uv run rpa-pipeline run configs/v0.1.toml --resume")),
        201: (200, OLD, "uv run rpa-pipeline run configs/v0.1.toml --resume"),
        202: (201, OLD, "/usr/bin/python3 -m rpa_pipeline run configs/v0.1.toml"),
        # a watcher: an old wait loop whose sleeps are young
        300: (CLAUDE, OLD, SNAP.format("while kill -0 57253 2>/dev/null; do sleep 60; done; tail -2 run.log")),
        301: (300, YOUNG, "sleep 60"),
        # a quick test run: young
        400: (CLAUDE, YOUNG, SNAP.format("pytest -q")),
        401: (400, YOUNG, "/usr/bin/python3 -m pytest -q"),
        # a long shell loop of short commands: the shell itself is the work
        500: (CLAUDE, OLD, SNAP.format("for f in *.tif; do gdal_translate $f out/$f; done")),
        501: (500, YOUNG, "gdal_translate a.tif out/a.tif"),
        # the caller's own shell (ho --next runs here): left out through skip
        600: (CLAUDE, OLD, SNAP.format("python3 long.py")),
        601: (600, OLD, "python3 long.py"),
        # already detached (parent pid 1), and another session's Bash shell: neither is this session's
        700: (1, OLD, "/bin/sh -c ... ho-run /h/runs/x.exit uv run thing"),
        800: (50, OLD, "claude --name other"),
        801: (800, OLD, SNAP.format("python3 other.py")),
        802: (801, OLD, "python3 other.py"),
    }


class ProcessWalk(unittest.TestCase):
    def test_etime(self):
        self.assertEqual(ho.etime("05:03"), 303)
        self.assertEqual(ho.etime("01:02:03"), 3723)
        self.assertEqual(ho.etime("2-01:00:00"), 2 * 86400 + 3600)
        self.assertEqual(ho.etime("garbage"), 0)

    def test_bash_text(self):
        self.assertEqual(ho.bash_text(SNAP.format("echo hi")), "echo hi")
        self.assertEqual(ho.bash_text(SNAP.format("echo '\\''quoted'\\''")), "echo 'quoted'")
        self.assertEqual(ho.bash_text("python3 x.py"), "python3 x.py")

    def test_long_runs_sorts_work_from_watchers(self):
        work, watchers = ho.long_runs(table(), CLAUDE, 600, skip={600, 601})
        self.assertEqual([p for p, _, _ in work], [201, 500])
        self.assertEqual(work[1][2], "for f in *.tif; do gdal_translate $f out/$f; done")
        self.assertEqual([p for p, _, _ in watchers], [300])

    def test_threshold(self):
        work, watchers = ho.long_runs(table(), CLAUDE, OLD + 1)
        self.assertEqual((work, watchers), ([], []))

    def test_watcher_patterns(self):
        for cmd in ["sleep 600", "/bin/sleep 60", "while kill -0 9 2>/dev/null; do sleep 60; done",
                    "until [ -e x.exit ]; do sleep 30; done", "tail -f run.log"]:
            self.assertRegex(cmd, ho.WATCHER)
        for cmd in ["uv run rpa-pipeline run x.toml", "python3 train.py", "tail -n 5 run.log"]:
            self.assertNotRegex(cmd, ho.WATCHER)


class Fixture(unittest.TestCase):
    """A temp handoffs folder and a fake session: claude pid 100 with the table above."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "lane.md").write_text(f"---\nworkdir: {self.dir}\nlauncher: claude\n---\nGoal: x\n")
        self.transcript = self.dir / "t.jsonl"
        self.patches = [mock.patch.object(ho, "HANDOFFS", self.dir), mock.patch.object(ho, "NEXT", self.dir / ".next"),
                        mock.patch.object(ho, "DRY", False), mock.patch.object(ho, "proc_table", table),
                        mock.patch.object(ho, "lineage", lambda t, pid: {600, 601})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_main(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                ho.main(argv)
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()


class Hook(Fixture):
    def event(self, kind, tokens):
        self.transcript.write_text(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": tokens}}}) + "\n")
        return json.dumps({"hook_event_name": kind, "transcript_path": str(self.transcript)})

    def hook(self, kind, tokens):
        with mock.patch.object(ho, "claude_ancestor", lambda: (CLAUDE, None)), \
                mock.patch.object(sys, "stdin", io.StringIO(self.event(kind, tokens))):
            return self.run_main(["--hook"])

    def test_past_soft_names_work_and_counts_watchers(self):
        _, out, _ = self.hook("UserPromptSubmit", 300_000)
        msg = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("pid 201 (up 3h00m): uv run rpa-pipeline", msg)
        self.assertIn("pid 500", msg)
        self.assertIn("--detach --name <run> -- <cmd>", msg)
        self.assertIn("1 watcher(s)", msg)
        for pid in (101, 102, 103, 202, 300, 401, 601, 700, 802):
            self.assertNotIn(f"pid {pid} ", msg)

    def test_stop_past_hard_blocks_with_the_list(self):
        _, out, _ = self.hook("Stop", 500_000)
        self.assertIn("pid 201", json.loads(out)["reason"])

    def test_below_soft_walks_nothing(self):
        def boom():
            raise AssertionError("walked the process table below the soft limit")
        with mock.patch.object(ho, "proc_table", boom):
            self.assertEqual(self.hook("UserPromptSubmit", 1000)[1], "")
            self.assertEqual(self.hook("Stop", 300_000)[1], "")


class Next(Fixture):
    def run_next(self, extra=(), work=True):
        t = table() if work else {k: v for k, v in table().items() if k not in (200, 201, 202, 500, 501)}
        with mock.patch.object(ho, "own_session", lambda: (CLAUDE, 50, {"name": "lane", "cwd": str(self.dir)})), \
                mock.patch.object(ho, "has_shell_hook", lambda pid: True), \
                mock.patch.object(ho, "clear_hook_installed", lambda: False), \
                mock.patch.object(ho, "proc_table", lambda: t):
            return self.run_main(["--next", "lane", *extra], {"HO_AUTO_EXIT": "1"})

    def test_refuses_auto_exit_over_long_work(self):
        code, out, err = self.run_next()
        self.assertEqual(code, 1)
        self.assertIn("not queued", err)
        self.assertIn("pid 201", err)
        self.assertIn("--force", err)
        self.assertFalse((self.dir / ".next").exists())

    def test_watchers_alone_do_not_block(self):
        code, out, _ = self.run_next(work=False)
        self.assertEqual(code, 0)
        self.assertIn("exits when this turn ends", out)
        self.assertTrue((self.dir / ".next" / "shell-50").exists())

    def test_force_queues_anyway(self):
        code, out, _ = self.run_next(["--force"])
        self.assertEqual(code, 0)
        self.assertTrue((self.dir / ".next" / f"pid-{CLAUDE}").exists())

    def test_user_exit_path_warns_instead(self):
        with mock.patch.dict(os.environ, {"HO_AUTO_EXIT": "0"}):
            with mock.patch.object(ho, "own_session", lambda: (CLAUDE, 50, {"name": "lane", "cwd": str(self.dir)})), \
                    mock.patch.object(ho, "has_shell_hook", lambda pid: True), \
                    mock.patch.object(ho, "clear_hook_installed", lambda: False):
                code, out, _ = self.run_main(["--next", "lane"])
        self.assertEqual(code, 0)
        self.assertIn("type /exit", out)
        self.assertIn("Exiting kills this session's long work: pid 201", out)


class Detach(unittest.TestCase):
    """A real detached run, through the command line."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "HO_HANDOFFS": self.tmp.name}
        self.folder = Path(self.tmp.name) / "lane"

    def tearDown(self):
        self.tmp.cleanup()

    def ho(self, *args):
        return subprocess.run([sys.executable, str(HO), *args], env=self.env, cwd=self.tmp.name,
                              capture_output=True, text=True, timeout=30)

    def wait_exit(self, path, secs=15):
        end = time.time() + secs
        while not path.exists() and time.time() < end:
            time.sleep(0.1)
        return path.read_text().strip()

    def rows(self):
        lines = (self.folder / "runs.tsv").read_text().splitlines()
        self.assertEqual(lines[0].split("\t"), ho.RUN_FIELDS)
        return [dict(zip(ho.RUN_FIELDS, line.split("\t"))) for line in lines[1:]]

    def test_sleep_runs_detached_and_leaves_a_marker(self):
        r = self.ho("--detach", "--session", "lane", "--name", "nap", "--", "sleep", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.rows()[0]
        self.assertEqual(row["run"], "nap")
        self.assertIn(f"as pid {row['pid']}", r.stdout)
        self.assertEqual(row["log"], str(self.folder / "runs" / "nap.log"))
        self.assertEqual(row["exit"], str(self.folder / "runs" / "nap.exit"))
        self.assertEqual(os.path.realpath(row["cwd"]), os.path.realpath(self.tmp.name))
        self.assertEqual(row["cmd"], "sleep 2")
        # its own process session and group: nothing aimed at the caller's group reaches it
        pgid = subprocess.run(["ps", "-o", "pgid=", "-p", row["pid"]], capture_output=True, text=True).stdout.strip()
        self.assertEqual(pgid, row["pid"])
        self.assertIn("running", self.ho("--runs", "lane").stdout)
        self.assertRegex(self.wait_exit(Path(row["exit"])), r"^exit 0 at \d{4}-\d\d-\d\dT")
        log = Path(row["log"]).read_text()
        self.assertIn("start, pid", log)
        self.assertIn("exit 0", log)
        # the watch line returns at once for a finished run and shows how it ended
        line = next(l for l in r.stdout.splitlines() if l.strip().startswith("watch")).split("watch", 1)[1]
        w = subprocess.run(["/bin/sh", "-c", line.strip()], capture_output=True, text=True, timeout=10)
        self.assertIn("exit 0", w.stdout)
        self.assertIn("exit 0 at", self.ho("--runs", "lane").stdout)

    def test_stopped_run_still_writes_its_marker(self):
        r = self.ho("--detach", "--session", "lane", "--name", "long", "--", "sleep", "30")
        pid = self.rows()[0]["pid"]
        again = self.ho("--detach", "--session", "lane", "--name", "long", "--", "sleep", "1")
        self.assertEqual(again.returncode, 1)
        self.assertIn("still running", again.stderr)
        time.sleep(0.3)
        subprocess.run(["kill", "-TERM", "--", f"-{pid}"], check=True)
        self.assertEqual(self.wait_exit(self.folder / "runs" / "long.exit").split()[:2], ["exit", "143"])

    def test_failure_status_and_gone_rows(self):
        self.ho("--detach", "--session", "lane", "--name", "bad", "--", "sh", "-c", "exit 3")
        self.assertEqual(self.wait_exit(self.folder / "runs" / "bad.exit").split()[:2], ["exit", "3"])
        with open(self.folder / "runs.tsv", "a") as fh:
            fh.write("\t".join(["lost", "99999999", "/nope.log", "/nope.exit", "/", "2026-01-01T00:00:00", "x"]) + "\n")
        out = self.ho("--runs", "lane").stdout
        self.assertIn("exit 3 at", out)
        self.assertIn("lost  gone: pid 99999999", out)

    def test_dry_run_changes_nothing(self):
        r = self.ho("--detach", "--dry-run", "--session", "lane", "--", "sleep", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would start", r.stdout)
        self.assertFalse(self.folder.exists())

    def test_command_after_double_dash_keeps_its_flags(self):
        r = self.ho("--detach", "--session", "lane", "--name", "flags", "--", "sh", "-c", "echo $0 $1", "--dry-run", "--name")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_exit(self.folder / "runs" / "flags.exit")
        self.assertIn("--dry-run --name", (self.folder / "runs" / "flags.log").read_text())

    def test_unknown_program_is_refused(self):
        r = self.ho("--detach", "--session", "lane", "--", "no-such-program-here")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such program", r.stderr)


if __name__ == "__main__":
    unittest.main()
