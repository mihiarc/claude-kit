#!/usr/bin/env python3
"""Extract Bash commands and failed tool results from Claude Code transcripts.

Writes OUT_DIR/commands.jsonl ({"command", "worktree", "session"}) and OUT_DIR/errors.jsonl
({"error", "tool", "worktree", "session"}) from every session that started on or after --since, for
checking gotcha triggers with `gotcha_hints.py check`. Transcripts are read from
~/.claude/projects/*/*.jsonl; errors are cut to 4,000 characters.

Usage:
    python3 -I transcript_corpus.py OUT_DIR [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path


def is_worktree(cwd: str) -> bool:
    if not cwd:
        return False
    if "/.claude/worktrees/" in cwd:
        return True
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


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def session_rows(path: Path, since: str) -> list[dict] | None:
    """The transcript's rows, or None if the session started before `since`."""
    rows, first = [], None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            ts = row.get("timestamp")
            if first is None and ts:
                first = ts
                if ts[:10] < since:
                    return None
            rows.append(row)
    return rows if first else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir")
    ap.add_argument("--since", default=(dt.date.today() - dt.timedelta(days=30)).isoformat())
    args = ap.parse_args()

    root = Path.home() / ".claude" / "projects"
    commands, errors, sessions = [], [], 0
    worktree: dict[str, bool] = {}
    for d in os.listdir(root):
        if not (root / d).is_dir():
            continue
        for f in os.listdir(root / d):
            if not f.endswith(".jsonl"):
                continue
            try:
                rows = session_rows(root / d / f, args.since)
            except OSError:
                continue
            if rows is None:
                continue
            sessions += 1
            session = f[: -len(".jsonl")]
            tools: dict[str, str] = {}
            for row in rows:
                content = (row.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                cwd = row.get("cwd", "")
                if cwd not in worktree:
                    worktree[cwd] = is_worktree(cwd)
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_use":
                        tools[c.get("id")] = c.get("name", "")
                        cmd = (c.get("input") or {}).get("command", "") if c.get("name") == "Bash" else ""
                        if cmd:
                            commands.append({"command": cmd, "worktree": worktree[cwd], "session": session})
                    elif c.get("type") == "tool_result" and c.get("is_error"):
                        errors.append({
                            "error": text_of(c.get("content"))[:4000],
                            "tool": tools.get(c.get("tool_use_id"), ""),
                            "worktree": worktree[cwd],
                            "session": session,
                        })

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, items in (("commands", commands), ("errors", errors)):
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(i, ensure_ascii=False) + "\n" for i in items)
    in_wt = sum(c["worktree"] for c in commands)
    print(f"{sessions} sessions since {args.since}: {len(commands)} commands ({in_wt} in worktrees), {len(errors)} errors -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
