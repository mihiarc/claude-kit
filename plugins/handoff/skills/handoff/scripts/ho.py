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
                         a SessionStart hook hands the fresh context the prompt.
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
                         leave that to the user).

--dry-run reports what would happen and changes nothing. HO_HANDOFFS overrides the folder.
Queued handoffs live in <handoffs>/.next/ and expire after 24 hours.
"""
import json, os, re, shlex, signal, subprocess, sys, time
from pathlib import Path

HANDOFFS = Path(os.environ.get("HO_HANDOFFS", Path.home() / ".claude" / "handoffs"))
NEXT = HANDOFFS / ".next"
MAX_AGE = 24 * 3600
DRY = "--dry-run" in sys.argv


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
    how = ("run the handoff skill, then queue the next session with `ho --next` (its Step 6); "
           "a session that reports to a coordinator sends it the handoff's path instead. If the work is "
           "finished and nothing follows, say so and suggest /clear instead of handing off")
    if kind == "UserPromptSubmit":
        msg = (f"[ho] Context is {ctx // 1000}K, past the {hard // 1000}K hand-off point. Finish the step in "
               f"progress, then hand off: {how}." if ctx >= hard else
               f"[ho] Context is {ctx // 1000}K; the hand-off point is {hard // 1000}K. At the next natural "
               f"stopping point (a finished piece of work, before starting a new one), hand off without "
               f"asking: {how}.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))
    elif kind == "Stop" and ctx >= hard and not event.get("stop_hook_active"):
        print(json.dumps({"decision": "block", "reason":
              f"Context is {ctx // 1000}K, past the {hard // 1000}K hand-off point. Hand off now: {how}."}))


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


def main(argv):
    args = [a for a in argv if a != "--dry-run"]
    flags = {a for a in args if a.startswith("--")}
    rest = [a for a in args if not a.startswith("--")]
    if not args or flags & {"-h", "--help"}:
        print(__doc__)
        return
    sweep()

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
        if not shell:
            mark_done(cpid, False)
            print(f"This session has no shell to continue in (a background session?). Have the coordinator "
                  f"run `ho --relaunch {h['stem']}`, or start it with `ho {h['stem']}`.")
            return
        name = me.get("name")
        same = (name == h["stem"] and os.path.realpath(me.get("cwd") or "") == h["workdir"]
                and os.environ.get("HO_LAUNCHER", "claude") == h["launcher"])
        can_clear = same and clear_hook_installed()
        can_exit = has_shell_hook(None)
        if not (can_clear or can_exit):
            mark_done(cpid, False)
            print(f"This window can't continue on its own yet (its shell doesn't source ho.zsh). "
                  f"Exit, then run: {shell_cmd(h)}")
            return
        queue(shell, h, name if can_clear else None)
        mark_done(cpid, auto and can_exit)
        if auto and can_exit:
            print(f"Queued {h['stem']}: this session exits when this turn ends, and {h['stem']} starts in this window.")
            return
        how = " or ".join(filter(None, ["/clear and then any message ('go')" if can_clear else "",
                                        "/exit" if can_exit else ""]))
        print(f"Queued {h['stem']}: type {how}, and it starts in this window.")
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
