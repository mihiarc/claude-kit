#!/usr/bin/env python3
"""ho: start the session a handoff prompt describes, or set it up to start when this one ends.

A handoff is ~/.claude/handoffs/<stem>.md. The next session is named <stem> (its messaging
address) and opens with "read ~/.claude/handoffs/<stem>.md and follow it". Optional
frontmatter at the top of the file says where it runs:

    ---
    workdir: /abs/path/to/checkout
    launcher: claude
    ---

workdir defaults to the current directory. A workdir of <main>/.claude/worktrees/<task> that
doesn't exist yet is created by launching from <main> with --worktree <task>. launcher is
`claude` or a shell function or command that wraps it (for example one that starts Claude
Code under another identity); it gets the same arguments.

  ho <stem>              free the name, then start the session in this terminal (the `ho`
                         zsh function evals the command this prints)
  ho --window <stem>     same, in a new Terminal window (macOS)
  ho --bg <stem>         start it in the background and open a Terminal attached to it.
                         Plain `claude` only: a wrapper's environment doesn't reach
                         background sessions, so other launchers get --window instead.
  ho --next <stem>       run from inside a Claude Code session (its Bash tool). When this
                         session exits, the next one starts in the same window. When <stem>
                         is this session's own name, workdir and launcher, /clear works too:
                         a SessionStart hook hands the fresh context the prompt. It won't
                         queue an exit that would kill long work: anything under the
                         session's Bash tool older than HO_LONG_RUN_MINUTES (default 10)
                         makes it refuse and name the process; `ho --detach` it, or pass
                         --force. Watchers (sleep, kill -0 and tail -f loops) don't block.
  ho --detach [--name <run>] [--session <name>] -- <cmd...>
                         start <cmd> in its own process session (stdin /dev/null, output to
                         a log), so it outlives the Claude Code session that started it, and
                         record it in <handoffs>/<session>/runs.tsv. Prints the pid, the log,
                         the exit marker (written when <cmd> ends: "exit <status> at <time>"),
                         a watch line a fresh session runs in the background to wait on it,
                         and a stop line. <session> defaults to the caller's session name.
                         <cmd> runs as given, without a shell: use `sh -c '...'` for pipes
                         or &&, and on macOS put `caffeinate -i` in front to keep it awake.
  ho --runs [<session>]  list a session's detached runs (running, exited with its status, or
                         gone with no exit marker) and a watch line for each running one
  ho --relaunch <stem>   replace the live session holding <stem>'s name with a fresh one from
                         the handoff. A background holder is stopped and relaunched in the
                         background; an interactive one gets SIGTERM, and its own window
                         starts the next session. With no holder, it starts one (--bg if
                         also given, else --window).
  ho --pending <pid>     zsh precmd: print the command for a handoff queued for shell <pid>
  ho --on-clear          SessionStart hook (matcher "clear"): emit the queued prompt as context
  ho --hook              UserPromptSubmit and Stop hook: watch the session's context. Past
                         HO_CONTEXT_SOFT tokens (default 250000) each prompt carries a note to
                         hand off at the next natural stopping point; past HO_CONTEXT_HARD
                         (default 400000) a finished turn is sent back to write the handoff.
                         After `ho --next` has queued one, the session exits when its turn
                         ends, so the next one starts in the same window (HO_AUTO_EXIT=0 to
                         leave that to the user). Past the soft point the note also names
                         long work under the session's Bash tool that would die on exit.

--dry-run reports what would happen and changes nothing. HO_HANDOFFS overrides the folder.
Queued handoffs live in <handoffs>/.next/ and expire after 24 hours.
"""
import json, os, re, shlex, shutil, signal, subprocess, sys, time
from datetime import datetime
from pathlib import Path

HANDOFFS = Path(os.environ.get("HO_HANDOFFS", Path.home() / ".claude" / "handoffs"))
NEXT = HANDOFFS / ".next"
MAX_AGE = 24 * 3600
DRY = False
SELF = Path(__file__).resolve()
# a process that only waits: a sleep, a `while kill -0 <pid>` or `until …; sleep` loop, a tail -f
WATCHER = re.compile(r"\bkill -0\b|^\s*(\S*/)?sleep\b|\btail -[fF]\b|\b(while|until)\b.*\bsleep\b")
RUN_FIELDS = ["run", "pid", "log", "exit", "cwd", "started", "cmd"]
# runs <cmd> and writes the exit marker ($1) when it ends, also when the run is stopped by signal
WRAPPER = r'''x=$1; shift
trap : HUP INT TERM
echo "== $(date +%Y-%m-%dT%H:%M:%S) start, pid $$, in $PWD: $*"
"$@"
rc=$?
echo "== $(date +%Y-%m-%dT%H:%M:%S) exit $rc"
echo "exit $rc at $(date +%Y-%m-%dT%H:%M:%S)" > "$x.tmp" && mv -f "$x.tmp" "$x"
exit $rc'''


def die(msg):
    print(f"ho: {msg}", file=sys.stderr)
    sys.exit(1)


def note(msg):
    print(f"ho: {msg}", file=sys.stderr)


def load(stem):
    path = Path(stem).expanduser()
    if path.suffix != ".md":
        path = HANDOFFS / f"{stem}.md"
    if not path.is_file():
        die(f"no handoff at {path}")
    meta = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            if v.strip():
                meta[k.strip()] = os.path.expanduser(v.split("#")[0].strip().strip("'\""))
    shown = f"~/{path.relative_to(Path.home())}" if path.is_relative_to(Path.home()) else str(path)
    return {
        "stem": path.stem,
        "workdir": os.path.realpath(meta.get("workdir") or os.getcwd()),
        "launcher": meta.get("launcher", "claude"),
        "prompt": f"read {shown} and follow it",
    }


def launch_parts(h):
    """(directory to start in, extra args) for this handoff's workdir."""
    wd = h["workdir"]
    if os.path.isdir(wd):
        return wd, []
    m = re.match(r"(.+)/\.claude/worktrees/([^/]+)$", wd)
    if m and os.path.isdir(m.group(1)):
        return m.group(1), ["--worktree", m.group(2)]
    die(f"workdir {wd} doesn't exist")


def shell_cmd(h):
    where, extra = launch_parts(h)
    args = " ".join(shlex.quote(a) for a in ["--name", h["stem"], *extra, h["prompt"]])
    return f"cd {shlex.quote(where)} && HO_LAUNCHER={shlex.quote(h['launcher'])} {h['launcher']} {args}"


def agents():
    try:
        out = subprocess.run(["claude", "agents", "--json", "--all"], capture_output=True, text=True, timeout=20).stdout
        return json.loads(out or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def holders(stem):
    out = []
    for a in agents():
        name = a.get("name") or ""
        if name == stem or name.startswith(stem + " ("):
            if a.get("id") and a.get("state") in ("stopped", "failed"):
                continue
            if not a.get("id") and not alive(a.get("pid")):
                continue
            out.append(a)
    return out


def free_name(stem, waiting_for=None):
    """Stop background holders; refuse on a live interactive one (other than waiting_for)."""
    for a in holders(stem):
        if a.get("id"):
            note(f"stopping background session {a['id']} ({a.get('name')}), which holds the name")
            if not DRY:
                subprocess.run(["claude", "stop", a["id"]], capture_output=True, timeout=30)
        elif a.get("pid") and int(a["pid"]) != (waiting_for or -1):
            die(f"interactive session '{a.get('name')}' (pid {a['pid']}, {a.get('cwd')}) holds the name. "
                f"Exit it first, or use `ho --relaunch {stem}` to replace it.")


def ps(pid):
    out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True).stdout.split(None, 1)
    return (int(out[0]), out[1].strip()) if len(out) == 2 else (None, "")


def clear_hook_installed():
    try:
        return "--on-clear" in (Path.home() / ".claude" / "settings.json").read_text()
    except OSError:
        return False


def has_shell_hook(pid):
    """Whether the process was started from a shell that sources ho.zsh."""
    if pid == os.getpid() or pid is None:
        return os.environ.get("HO_SHELL_HOOK") == "1"
    env = subprocess.run(["ps", "eww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    return "HO_SHELL_HOOK=1" in env


def claude_ancestor():
    """(claude pid, its parent zsh pid or None) for the session this process runs under."""
    pid = os.getppid()
    for _ in range(12):
        ppid, comm = ps(pid)
        if ppid is None:
            break
        if os.path.basename(comm) == "claude":
            return pid, (ppid if "zsh" in os.path.basename(ps(ppid)[1]) else None)
        pid = ppid
    return None, None


def own_session():
    """(claude pid, its parent shell pid or None, the session's agents entry) for the caller."""
    cpid, shell = claude_ancestor()
    if not cpid:
        die("not running inside a Claude Code session")
    return cpid, shell, next((a for a in agents() if a.get("pid") == cpid), {})


def context_tokens(transcript):
    """Context size at the session's last request, from the tail of its transcript."""
    try:
        with open(transcript, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 2_000_000))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError):
        return 0
    for line in reversed(lines):
        if '"usage"' not in line or '"assistant"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        u = (d.get("message") or {}).get("usage") or {}
        if u and not d.get("isSidechain"):
            return sum(u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return 0


def etime(s):
    """Seconds from ps's elapsed time, [[dd-]hh:]mm:ss."""
    days, _, hms = s.rpartition("-")
    try:
        secs = 0
        for part in hms.split(":"):
            secs = secs * 60 + int(part)
        return secs + int(days or 0) * 86400
    except ValueError:
        return 0


def proc_table():
    """{pid: (ppid, seconds alive, command line)} for every process."""
    out = subprocess.run(["ps", "-A", "-ww", "-o", "pid=,ppid=,etime=,command="],
                         capture_output=True, text=True).stdout
    table = {}
    for line in out.splitlines():
        f = line.split(None, 3)
        if len(f) == 4 and f[0].isdigit() and f[1].isdigit():
            table[int(f[0])] = (int(f[1]), etime(f[2]), f[3])
    return table


def lineage(table, pid):
    """pid and its ancestors."""
    seen = set()
    while pid and pid not in seen:
        seen.add(pid)
        pid = table.get(pid, (None,))[0]
    return seen


def bash_text(cmd):
    """The command a Bash-tool shell was given: the eval '…' in its command line, else all of it."""
    m = re.search(r"\beval '((?:[^']|'\\'')*)'", cmd)
    return m.group(1).replace("'\\''", "'") if m else cmd


def long_runs(table, cpid, min_age, skip=()):
    """(work, watchers) under session cpid's Bash-tool shells, each a list of (pid, age, command).

    A Bash-tool shell is a child of claude running `<shell> -c source …/shell-snapshots/…`; MCP
    servers, channel plugins and other direct children are not, and outlive nothing. Work is the
    topmost process in each shell's tree that has run min_age seconds and isn't a watcher, or the
    shell itself when it runs a long loop of short commands. Shells in skip (the caller's) are left out.
    """
    kids = {}
    for pid, (ppid, _, _) in table.items():
        kids.setdefault(ppid, []).append(pid)
    work, watchers = [], []
    for sh in sorted(kids.get(cpid, [])):
        _, age, cmd = table[sh]
        if "shell-snapshots/" not in cmd or sh in skip:
            continue
        found, stack = [], list(kids.get(sh, []))
        while stack:
            pid = stack.pop()
            _, a, c = table[pid]
            if a >= min_age and not WATCHER.search(c):
                found.append((pid, a, c))
            else:
                stack += kids.get(pid, [])
        if found:
            work += sorted(found)
        elif age >= min_age:
            text = bash_text(cmd)
            (watchers if WATCHER.search(text) else work).append((sh, age, text))
    return work, watchers


def at_risk(cpid):
    """long_runs for this session, leaving out the shell this process runs in."""
    try:
        min_age = 60 * float(os.environ.get("HO_LONG_RUN_MINUTES", 10))
    except ValueError:
        min_age = 600
    table = proc_table()
    return long_runs(table, cpid, min_age, lineage(table, os.getpid()))


def fmt_age(secs):
    d, s = divmod(int(secs), 86400)
    h, s = divmod(s, 3600)
    return f"{d}d{h}h" if d else f"{h}h{s // 60:02d}m" if h else f"{s // 60}m"


def named(procs):
    def short(c):
        c = re.sub(r"^\S*/", "", " ".join(c.split()))  # the program's name, not its path
        return c if len(c) <= 120 else c[:119] + "…"
    return "; ".join(f"pid {p} (up {fmt_age(a)}): {short(c)}" for p, a, c in procs)


def detach_how():
    return f"python3 {shlex.quote(str(SELF))} --detach --name <run> -- <cmd>"


def risk_note(work, watchers):
    """What the context note adds about processes that die with the session."""
    msg = ""
    if work:
        msg += (f" This session's Bash tool runs long work that dies when the session exits: {named(work)}. "
                f"Relaunch it with `{detach_how()}` so it outlives the session (stop this copy first, and "
                f"resume where the tool can), and have the handoff list it from `ho --runs`.")
    if watchers:
        msg += (f" Its {len(watchers)} watcher(s) (sleep / kill -0 loops) are disposable: let them go, and "
                f"have the handoff say what each waits on so the next session re-arms it.")
    return msg


def hook(event):
    """UserPromptSubmit / Stop: nudge toward a handoff by context size; exit once one is queued."""
    soft = int(os.environ.get("HO_CONTEXT_SOFT", 250_000))
    hard = int(os.environ.get("HO_CONTEXT_HARD", 400_000))
    kind = event.get("hook_event_name")
    # walk the process tree only when some session has handed off: this runs on every prompt and turn
    cpid = claude_ancestor()[0] if NEXT.is_dir() and any(NEXT.glob("pid-*")) else None
    done = NEXT / f"pid-{cpid}"
    if cpid and done.exists():
        if kind == "Stop":
            try:
                rec = json.loads(done.read_text())
            except (OSError, ValueError):
                rec = {}
            if rec.get("exit"):
                done.unlink(missing_ok=True)
                subprocess.Popen(["sh", "-c", f"sleep 2; kill -TERM {cpid}"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    ctx = context_tokens(event.get("transcript_path"))
    if ctx < soft:
        return
    if kind != "UserPromptSubmit" and not (kind == "Stop" and ctx >= hard and not event.get("stop_hook_active")):
        return
    how = ("run the handoff skill, then queue the next session with `ho --next` (its Step 6); "
           "a session that reports to a coordinator sends it the handoff's path instead. If the work is "
           "finished and nothing follows, say so and suggest /clear instead of handing off")
    # only now, with a note to send, walk the process table for work that would die with the session
    cpid = cpid or claude_ancestor()[0]
    runs = risk_note(*at_risk(cpid)) if cpid else ""
    if kind == "UserPromptSubmit":
        msg = (f"[ho] Context is {ctx // 1000}K, past the {hard // 1000}K hand-off point. Finish the step in "
               f"progress, then hand off: {how}." if ctx >= hard else
               f"[ho] Context is {ctx // 1000}K; the hand-off point is {hard // 1000}K. At the next natural "
               f"stopping point (a finished piece of work, before starting a new one), hand off without "
               f"asking: {how}.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg + runs}}))
    else:
        print(json.dumps({"decision": "block", "reason":
              f"Context is {ctx // 1000}K, past the {hard // 1000}K hand-off point. Hand off now: {how}.{runs}"}))


def osa_window(cmd):
    script = 'tell application "Terminal" to do script "%s"' % cmd.replace("\\", "\\\\").replace('"', '\\"')
    if DRY:
        note(f"would open a Terminal window running: {cmd}")
        return
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


def start_bg(h):
    if os.path.basename(h["launcher"]) != "claude":
        note(f"launcher {h['launcher']} can't run in the background; opening a window instead")
        return osa_window(shell_cmd(h))
    where, extra = launch_parts(h)
    argv = ["claude", "--bg", "--name", h["stem"], *extra, h["prompt"]]
    if DRY:
        note(f"would run in {where}: {shlex.join(argv)}, then open a Terminal on it")
        return
    r = subprocess.run(argv, cwd=where, capture_output=True, text=True, timeout=60)
    out = (r.stdout + r.stderr).strip()
    m = re.search(r"\b([0-9a-f]{8,})\b", out)
    if r.returncode or not m:
        die(f"background launch failed or printed no id:\n{out}")
    osa_window(f"claude attach {m.group(1)}")
    print(f"started {h['stem']} in the background as {m.group(1)}; a Terminal is attached")


def queue(shell, h, name=None):
    rec = {"stem": h["stem"], "path": h["prompt"], "workdir": h["workdir"], "shell": shell,
           "name": name, "created": time.time()}
    if DRY:
        note(f"would queue {rec}")
        return
    NEXT.mkdir(parents=True, exist_ok=True)
    (NEXT / f"shell-{shell}").write_text(json.dumps(rec))
    if name:
        (NEXT / f"name-{name}").write_text(json.dumps(rec))


def mark_done(cpid, exit_after_turn):
    """Record that this session has handed off, so the context hook stops nudging (and may exit it)."""
    if DRY:
        note(f"would mark session {cpid} handed off (exit after turn: {exit_after_turn})")
        return
    NEXT.mkdir(parents=True, exist_ok=True)
    (NEXT / f"pid-{cpid}").write_text(json.dumps({"exit": exit_after_turn, "created": time.time()}))


def take(marker):
    """Read and remove a queued handoff and its twin marker; None if missing or expired."""
    try:
        rec = json.loads(marker.read_text())
    except (OSError, ValueError):
        return None
    for f in (NEXT / f"shell-{rec.get('shell')}", NEXT / f"name-{rec.get('name')}"):
        f.unlink(missing_ok=True)
    return rec if time.time() - rec.get("created", 0) < MAX_AGE else None


def sweep():
    if NEXT.is_dir():
        for f in NEXT.iterdir():
            if time.time() - f.stat().st_mtime > MAX_AGE:
                f.unlink(missing_ok=True)


def session_name(given):
    """The session whose runs folder to use: --session, else the caller's session name."""
    name = given
    if not name:
        cpid = claude_ancestor()[0]
        if not cpid:
            die("not inside a Claude Code session: name one with --session <name>")
        name = re.sub(r" \(.*\)$", "", next((a.get("name") or "" for a in agents() if a.get("pid") == cpid), ""))
        if not name:
            die("this session has no name: pass --session <name>")
    if "/" in name or name.startswith("."):
        die(f"session name {name!r} can't be a folder name")
    return name


def read_runs(session):
    try:
        lines = (HANDOFFS / session / "runs.tsv").read_text().splitlines()
    except OSError:
        return []
    return [dict(zip(RUN_FIELDS, line.split("\t"))) for line in lines[1:] if line.strip()]


def run_state(r, table):
    """('exited', marker text), ('running', seconds up) or ('gone', None) for a runs.tsv row."""
    try:
        return "exited", Path(r["exit"]).read_text().strip()
    except (OSError, KeyError):
        pass
    p = table.get(int(r["pid"])) if r.get("pid", "").isdigit() else None
    try:
        expect = time.time() - datetime.fromisoformat(r.get("started", "")).timestamp()
    except ValueError:
        expect = None
    # a live pid whose age doesn't match the row's start time is a reused pid
    if p and (expect is None or abs(p[1] - expect) < 120):
        return "running", p[1]
    return "gone", None


def watch_line(r):
    """A disposable shell loop that returns when the run ends, then shows how it ended."""
    q = shlex.quote
    return (f"until [ -e {q(r['exit'])} ] || ! kill -0 {r['pid']} 2>/dev/null; do sleep 60; done; "
            f"tail -n 5 {q(r['log'])}; [ -e {q(r['exit'])} ] || echo {q('run ' + r['run'] + ' ended with no exit marker')}")


def detach(cmd, run, session):
    if not cmd:
        die("nothing to run: ho --detach [--name <run>] -- <cmd...>")
    if not shutil.which(cmd[0]):
        die(f"{cmd[0]}: no such program (shell functions and aliases don't carry over; use sh -c '...')")
    run = run or re.sub(r"[^\w.-]+", "-", os.path.basename(cmd[0])) + time.strftime("-%m%d-%H%M%S")
    if not re.fullmatch(r"[\w.-]+", run):
        die(f"run name {run!r}: use letters, digits, '.', '_' and '-'")
    folder = HANDOFFS / session
    tsv = folder / "runs.tsv"
    r = {"run": run, "pid": "<pid>", "log": str(folder / "runs" / f"{run}.log"),
         "exit": str(folder / "runs" / f"{run}.exit"), "cwd": os.getcwd(),
         "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": shlex.join(cmd)}
    table = proc_table()
    for old in read_runs(session):
        if old.get("run") == run and run_state(old, table)[0] == "running":
            die(f"run {run} is still running (pid {old['pid']}); give this one another --name")
    if DRY:
        note(f"would start in {r['cwd']}, in a process session of its own: {r['cmd']}")
        note(f"would log to {r['log']}, write {r['exit']} when it ends, and add run {run} to {tsv}")
    else:
        Path(r["exit"]).parent.mkdir(parents=True, exist_ok=True)
        Path(r["exit"]).unlink(missing_ok=True)
        with open(r["log"], "ab") as log:
            p = subprocess.Popen(["/bin/sh", "-c", WRAPPER, "ho-run", r["exit"], *cmd], stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        r["pid"] = str(p.pid)
        new = not tsv.exists()
        with open(tsv, "a") as fh:
            if new:
                fh.write("\t".join(RUN_FIELDS) + "\n")
            fh.write("\t".join(re.sub(r"[\t\n]", " ", r[k]) for k in RUN_FIELDS) + "\n")
    print(f"{'would start' if DRY else 'started'} run {run} as pid {r['pid']}, in a process session of its own, "
          f"so it outlives this Claude Code session\n"
          f"  log    {r['log']}\n"
          f"  exit   {r['exit']}  (written when it ends: exit <status> at <time>)\n"
          f"  watch  {watch_line(r)}\n"
          f"  stop   kill -TERM -- -{r['pid']}\n"
          f"Run the watch line with the Bash tool in the background to hear when the run ends. The watcher is "
          f"disposable: a handoff lists this run (`ho --runs`) with its watch line, and the next session re-arms it.")


def list_runs(session):
    rows = read_runs(session)
    if not rows:
        print(f"no detached runs for {session}")
        return
    table = proc_table()
    print(f"runs for {session} ({HANDOFFS / session / 'runs.tsv'}):")
    for r in rows:
        state, info = run_state(r, table)
        how = (f"running, pid {r.get('pid')}, up {fmt_age(info)}" if state == "running" else
               info if state == "exited" else f"gone: pid {r.get('pid')} ended with no exit marker")
        print(f"- {r.get('run')}  {how}  (started {r.get('started')})\n  cmd    {r.get('cmd')}\n  log    {r.get('log')}")
        if state == "running":
            print(f"  watch  {watch_line(r)}")


def main(argv):
    global DRY
    cmd = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    DRY = "--dry-run" in argv
    opts, args, it = {}, [], iter(argv)
    for a in it:
        if a in ("--name", "--session"):
            opts[a] = next(it, "")
        elif a != "--dry-run":
            args.append(a)
    flags = {a for a in args if a.startswith("-")}
    rest = [a for a in args if not a.startswith("-")]
    if not args or flags & {"-h", "--help"}:
        print(__doc__)
        return
    sweep()

    if "--detach" in flags:
        return detach(cmd, opts.get("--name"), session_name(opts.get("--session")))
    if "--runs" in flags:
        return list_runs(session_name(rest[0] if rest else opts.get("--session")))

    if "--hook" in flags:
        try:
            hook(json.load(sys.stdin))
        except ValueError:
            pass
        return

    if "--on-clear" in flags:
        try:
            event = json.load(sys.stdin)
        except ValueError:
            return
        name = event.get("session_title") or ""
        rec = take(NEXT / f"name-{name}") if name and (NEXT / f"name-{name}").exists() else None
        if rec and os.path.realpath(event.get("cwd", "")) == rec["workdir"]:
            ctx = f"This session continues from a handoff: {rec['path']}."
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}}))
        return

    if "--pending" in flags:
        marker = NEXT / f"shell-{rest[0]}"
        rec = take(marker) if marker.exists() else None
        if rec:
            h = load(rec["stem"])
            for _ in range(20):  # the old session may still be shutting down
                if not any(not a.get("id") for a in holders(h["stem"])):
                    break
                time.sleep(0.25)
            free_name(h["stem"])
            print(shell_cmd(h))
        return

    if not rest:
        die("name a handoff: ho [--window|--bg|--next|--relaunch] <stem>")
    h = load(rest[0])

    if "--next" in flags:
        cpid, shell, me = own_session()
        auto = os.environ.get("HO_AUTO_EXIT", "1") != "0"
        # watchers may die with the session; long work may not, unless --force says so
        work = [] if "--force" in flags else at_risk(cpid)[0]
        dies = (f" Exiting kills this session's long work: {named(work)}. Relaunch it with "
                f"`{detach_how()}` first." if work else "")
        if not shell:
            mark_done(cpid, False)
            print(f"This session has no shell to continue in (a background session?). Have the coordinator "
                  f"run `ho --relaunch {h['stem']}`, or start it with `ho {h['stem']}`.{dies}")
            return
        name = me.get("name")
        same = (name == h["stem"] and os.path.realpath(me.get("cwd") or "") == h["workdir"]
                and os.environ.get("HO_LAUNCHER", "claude") == h["launcher"])
        can_clear = same and clear_hook_installed()
        can_exit = has_shell_hook(None)
        if not (can_clear or can_exit):
            mark_done(cpid, False)
            print(f"This window can't continue on its own yet (its shell doesn't source ho.zsh). "
                  f"Exit, then run: {shell_cmd(h)}{dies}")
            return
        if auto and can_exit and work:
            die(f"not queued: this session would exit when the turn ends, and its Bash tool runs long work "
                f"that would die with it: {named(work)}. Relaunch each with `{detach_how()}` (stop this copy "
                f"first, and resume where the tool can), then run `ho --next {h['stem']}` again; or pass --force "
                f"to let it die. Watchers (sleep / kill -0 loops) don't block.")
        queue(shell, h, name if can_clear else None)
        mark_done(cpid, auto and can_exit)
        if auto and can_exit:
            print(f"Queued {h['stem']}: this session exits when this turn ends, and {h['stem']} starts in this window.")
            return
        how = " or ".join(filter(None, ["/clear and then any message ('go')" if can_clear else "",
                                        "/exit" if can_exit else ""]))
        print(f"Queued {h['stem']}: type {how}, and it starts in this window.{dies}")
        return

    if "--relaunch" in flags:
        live = holders(h["stem"])
        bg = [a for a in live if a.get("id")]
        inter = [a for a in live if not a.get("id") and a.get("pid")]
        if inter:
            pid = int(inter[0]["pid"])
            shell, comm = ps(pid)
            if not shell or "zsh" not in os.path.basename(ps(shell)[1]) or not has_shell_hook(pid):
                die(f"session pid {pid} can't continue in its own window (no zsh sourcing ho.zsh); "
                    f"exit it, then run `ho --window {h['stem']}`")
            queue(shell, h)
            if DRY:
                note(f"would send SIGTERM to {pid}")
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"sent SIGTERM to {h['stem']} (pid {pid}); its window starts the fresh session")
            return
        free_name(h["stem"])
        return start_bg(h) if bg or "--bg" in flags else osa_window(shell_cmd(h))

    if "--bg" in flags:
        free_name(h["stem"])
        return start_bg(h)
    if "--window" in flags:
        free_name(h["stem"])
        return osa_window(shell_cmd(h))
    free_name(h["stem"])
    if DRY:
        note(f"would run: {shell_cmd(h)}")
        return
    print(shell_cmd(h))


if __name__ == "__main__":
    main(sys.argv[1:])
