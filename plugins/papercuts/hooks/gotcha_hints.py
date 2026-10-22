#!/usr/bin/env python3
"""Hand a session the one gotchas line it needs, at the call that needs it.

Each line of the gotchas file is a `- ` bullet that may end in a trigger comment:

    - `pkill -f "<pat>" -n` reads the trailing -n as a second pattern → `kill <pid>`. <!-- command: \\bpkill\\s+-f -->

Trigger keys are separated by `;` and their values are Python regexes:

    command:  searched in a Bash command when it is called (PreToolUse)
    deny:     like command, but a match blocks the call, with the line as the reason
    error:    searched, ignoring case, in a failed call's error text (PostToolUseFailure) and in
              a Bash call's output (PostToolUse), since `cmd 2>&1 | tail` exits 0 when cmd fails
    tool:     the tool name must match; with no other key, the line arrives with the
              session's first call to that tool
    in:       `worktree` limits the command, deny and tool triggers to sessions working in a
              linked git worktree; error triggers fire anywhere, since the error text already
              identifies the moment

Context from a hook reaches the session together with the call's result, so a `command:` hint
informs the next call, not the one that matched. Use `deny:` for a command that does harm or
silently does the wrong thing (killing other processes, writing to the wrong place): the
session sees the reason before anything runs and rewrites the command. A deny fires on every
match; a hint arrives at most once per session and at most two per call. Every delivery is
appended to a log for the next sweep. The hook never allows a call, so the normal permission
flow still applies, and on any error it prints nothing and exits 0.

Usage:
    gotcha_hints.py [GOTCHAS]                    hook mode; reads the event JSON on stdin
    gotcha_hints.py check [GOTCHAS] [--commands F] [--errors F] [--expect F] [--top N]

The gotchas file is GOTCHAS, else $GOTCHAS_FILE, else ~/.claude/gotchas.md. The delivery log
is $GOTCHA_HINTS_LOG, else ~/.claude/gotcha-hints.jsonl.

`check` reports bad regexes and lines without triggers. With corpora it counts how often each
trigger fires, to catch triggers so broad they would fire on routine work, and with session
ids how many hints sessions would actually receive. Corpus files are JSON lines (written by
the sweep skill's transcript_corpus.py): --commands holds {"command": str, "worktree": bool,
"session": str}, --errors holds {"error": str, "tool": str, "session": str}, and --expect
holds cases {"command"|"error": str, "tool": str,
"worktree": bool, "expect": "<line id or the line's first words>"} that must fire the
expected line.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

KEYS = ("command", "deny", "error", "tool", "in")
TRIGGERS = ("command", "deny", "error", "tool")
COMMENT = re.compile(r"\s*<!--\s*(.*?)\s*-->\s*$")
SPLIT = re.compile(r";\s*(?=(?:%s)\s*:)" % "|".join(KEYS))
PER_CALL = 2


def gotchas_path(arg: str | None) -> Path:
    return Path(arg or os.environ.get("GOTCHAS_FILE") or "~/.claude/gotchas.md").expanduser()


def parse(path: Path) -> tuple[list[dict], list[str]]:
    """Return the file's bullets with their triggers, and any trigger problems."""
    lines, problems, section = [], [], ""
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.startswith("## "):
            section = raw[3:].strip()
            continue
        if not raw.startswith("- "):
            continue
        m = COMMENT.search(raw)
        text = raw[: m.start()].rstrip() if m else raw.rstrip()
        item = {"id": hashlib.sha1(text.encode()).hexdigest()[:8], "n": n, "section": section, "text": text}
        for key in KEYS:
            item[key] = []
        if m:
            for part in SPLIT.split(m[1]):
                key, _, value = part.partition(":")
                key, value = key.strip(), value.strip()
                if key not in KEYS or not value:
                    problems.append(f"line {n}: can't read trigger {part!r}")
                    continue
                if key == "in":
                    item["in"].append(value)
                    continue
                try:
                    item[key].append(re.compile(value, re.IGNORECASE if key == "error" else 0))
                except re.error as e:
                    problems.append(f"line {n}: bad {key} regex {value!r}: {e}")
        lines.append(item)
    return lines, problems


def in_worktree(cwd: str | None) -> bool:
    """True when cwd sits in a linked git worktree (its .git is a file pointing at .../worktrees/...)."""
    if not cwd:
        return False
    p = Path(cwd)
    for d in (p, *p.parents):
        g = d / ".git"
        if g.is_dir():
            return False
        if g.is_file():
            try:
                return "/worktrees/" in g.read_text(encoding="utf-8")
            except OSError:
                return False
    return False


def first_hit(regexes: list[re.Pattern], text: str) -> str | None:
    for r in regexes:
        m = r.search(text)
        if m:
            return m.group(0)
    return None


def match(lines: list[dict], event: str, tool: str, worktree: bool, command: str = "", output: str = "") -> list[tuple[dict, str, str]]:
    """Lines whose triggers fire for this call, as (line, trigger kind, matched text)."""
    hits = []
    for item in lines:
        if not any(item[k] for k in TRIGGERS):
            continue
        if item["tool"] and not any(r.search(tool) for r in item["tool"]):
            continue
        if event == "PreToolUse":
            if "worktree" in item["in"] and not worktree:
                continue
            found = first_hit(item["deny"], command) if command else None
            if found:
                hits.append((item, "deny", found))
                continue
            found = first_hit(item["command"], command) if command else None
            if found:
                hits.append((item, "command", found))
            elif item["tool"] and not (item["command"] or item["deny"] or item["error"]):
                hits.append((item, "tool", tool))
        elif output and item["error"]:
            found = first_hit(item["error"], output)
            if found:
                hits.append((item, "error", found))
    return hits


def strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def quotes_log(command: str, gotchas: Path) -> bool:
    """A command that reads or edits the gotchas or papercut file quotes the text triggers look for."""
    return gotchas.name in command or "papercuts" in command


def seen_file(session: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", session or "unknown")
    return Path(tempfile.gettempdir()) / "gotcha-hints" / f"{safe}.json"


def run_hook(gotchas_arg: str | None) -> None:
    event_data = json.loads(sys.stdin.read() or "{}")
    event = event_data.get("hook_event_name", "")
    tool = event_data.get("tool_name", "")
    tool_input = event_data.get("tool_input") or {}
    command = tool_input.get("command", "") if tool == "Bash" else ""
    gotchas = gotchas_path(gotchas_arg)
    if command and quotes_log(command, gotchas):
        return

    if event == "PreToolUse":
        output = ""
    elif event == "PostToolUseFailure":
        output = "\n".join(strings(event_data.get("error")))
    elif event == "PostToolUse" and tool == "Bash":
        output = "\n".join(strings(event_data.get("tool_response")))
    else:
        return

    lines, _ = parse(gotchas)
    hits = match(lines, event, tool, in_worktree(event_data.get("cwd")), command, output)
    if not hits:
        return

    denied = [h for h in hits if h[1] == "deny"]
    if denied:
        log_hits(event_data, denied)
        reason = "\n".join(f"- [{item['section']}] {item['text'][2:]}" for item, _, _ in denied)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked by a known gotcha in {gotchas}; rewrite the command:\n{reason}",
        }}))
        return

    seen_path = seen_file(event_data.get("session_id", ""))
    try:
        seen = set(json.loads(seen_path.read_text()))
    except (OSError, ValueError):
        seen = set()
    fresh = [h for h in hits if h[0]["id"] not in seen][:PER_CALL]
    if not fresh:
        return
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(sorted(seen | {h[0]["id"] for h in fresh})))
    log_hits(event_data, fresh)

    body = "\n".join(f"- [{item['section']}] {item['text'][2:]}" for item, _, _ in fresh)
    context = f"Known gotcha matching this call, from {gotchas}:\n{body}"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}))


def log_hits(event_data: dict, hits: list[tuple[dict, str, str]]) -> None:
    log = Path(os.environ.get("GOTCHA_HINTS_LOG") or "~/.claude/gotcha-hints.jsonl").expanduser()
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with log.open("a", encoding="utf-8") as f:
        for item, kind, found in hits:
            f.write(json.dumps({
                "ts": stamp, "session": event_data.get("session_id"), "event": event_data.get("hook_event_name"),
                "tool": event_data.get("tool_name"), "id": item["id"], "section": item["section"],
                "trigger": kind, "matched": found[:80], "cwd": event_data.get("cwd"),
            }) + "\n")


def read_jsonl(path: str | None) -> list[dict]:
    if not path:
        return []
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def run_check(args) -> int:
    gotchas = gotchas_path(args.gotchas)
    lines, problems = parse(gotchas)
    triggered = [l for l in lines if any(l[k] for k in TRIGGERS)]
    n_deny = sum(bool(l["deny"]) for l in lines)
    print(f"{len(lines)} lines, {len(triggered)} with triggers ({n_deny} deny), {len(problems)} trigger problems")
    for p in problems:
        print(f"  {p}")

    commands, errors, expect = read_jsonl(args.commands), read_jsonl(args.errors), read_jsonl(args.expect)
    commands = [c for c in commands if not quotes_log(c["command"], gotchas)]
    if commands or errors:
        counts = {l["id"]: [0, 0] for l in lines}
        for c in commands:
            for item, _, _ in match(lines, "PreToolUse", "Bash", bool(c.get("worktree")), command=c["command"]):
                counts[item["id"]][0] += 1
        for e in errors:
            for item, _, _ in match(lines, "PostToolUseFailure", e.get("tool", "Bash"), bool(e.get("worktree")), output=e["error"]):
                counts[item["id"]][1] += 1
        ranked = sorted(lines, key=lambda l: -(counts[l["id"]][0] + counts[l["id"]][1]))
        print(f"fires over {len(commands)} commands and {len(errors)} errors "
              "(! = hint on more than 1% of commands, or a deny on more than 0.1%):")
        for item in ranked[: args.top]:
            c, e = counts[item["id"]]
            if not c and not e:
                break
            limit = 0.001 if item["deny"] else 0.01
            flag = "!" if commands and c / len(commands) > limit else " "
            kind = "deny" if item["deny"] else "cmd "
            print(f" {flag}{c:6d} {kind} {e:5d} err  {item['id']}  [{item['section']}] {item['text'][2:90]}")
        sessions = {r["session"] for r in [*commands, *errors] if r.get("session")}
        if sessions:
            # What sessions would actually receive: each hint once per session, every deny.
            hints, denies = set(), 0
            for c in commands:
                for item, kind, _ in match(lines, "PreToolUse", "Bash", bool(c.get("worktree")), command=c["command"]):
                    if kind == "deny":
                        denies += 1
                    else:
                        hints.add((c.get("session"), item["id"]))
            for e in errors:
                for item, _, _ in match(lines, "PostToolUseFailure", e.get("tool", "Bash"), bool(e.get("worktree")), output=e["error"]):
                    hints.add((e.get("session"), item["id"]))
            per = collections.Counter(s for s, _ in hints)
            print(f"delivered: {len(hints)} hints to {len(per)} of {len(sessions)} sessions "
                  f"(max {max(per.values(), default=0)} in one session), {denies} denies")

    if expect:
        missed = []
        for case in expect:
            want = case["expect"]
            event = "PreToolUse" if "command" in case else "PostToolUseFailure"
            hits = match(lines, event, case.get("tool", "Bash"), bool(case.get("worktree")),
                         command=case.get("command", ""), output=case.get("error", ""))
            if not any(h[0]["id"] == want or h[0]["text"][2:].startswith(want) for h in hits):
                missed.append(case)
        print(f"expected cases: {len(expect) - len(missed)}/{len(expect)} fire their line")
        for case in missed:
            probe = case.get("command") or case.get("error", "")
            print(f"  missed {case['expect'][:40]!r} on {probe[:100]!r}")
    return 1 if problems else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        ap = argparse.ArgumentParser(prog="gotcha_hints.py check")
        ap.add_argument("gotchas", nargs="?")
        ap.add_argument("--commands")
        ap.add_argument("--errors")
        ap.add_argument("--expect")
        ap.add_argument("--top", type=int, default=25)
        return run_check(ap.parse_args(sys.argv[2:]))
    try:
        run_hook(sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
