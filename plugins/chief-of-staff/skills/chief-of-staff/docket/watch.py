#!/usr/bin/env python3
"""Wait until the Docket inbox has answers the chief-of-staff session hasn't seen, print them, exit.

The session runs this in the background; its exit wakes the session, which shows the answers to
the user in chat, then marks them seen with `--ack` and starts the watcher again.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(os.environ.get("COS_QUESTIONS", "~/.claude/chief-of-staff/questions.md")).expanduser().parent / "docket"
INBOX = HERE / "inbox.jsonl"
SEEN = HERE / ".seen"


def lines() -> list[str]:
    return INBOX.read_text().splitlines() if INBOX.exists() else []


def seen() -> int:
    return int(SEEN.read_text().strip() or 0) if SEEN.exists() else 0


if "--ack" in sys.argv:
    SEEN.write_text(str(len(lines())))
    print(f"acknowledged {len(lines())} answers")
    sys.exit(0)

limit = time.time() + float(sys.argv[1]) if len(sys.argv) > 1 else None
while True:
    all_lines = lines()
    if len(all_lines) > seen():
        for line in all_lines[seen():]:
            a = json.loads(line)
            pick = f"({a['choice']}) " if a.get("choice") else ""
            where = f"#{a['num']}" if a["num"] not in ("item", "project", "pr") else f"{a['num']} \"{a.get('item', '')[:80]}\""
            verb = {"drop": "DROP ", "refresh": "REFRESH ", "merge": "MERGE? ", "review": "REVIEW ",
                    "discuss": "DISCUSS ", "done": "DONE ",
                    "move": f"MOVE→{a.get('to', '?')} "}.get(a.get("action"), "")
            print(f"{verb}{where}: {pick}{a.get('text', '')}  [{a['time']}]")
        sys.exit(0)
    if limit and time.time() > limit:
        print("no new answers")
        sys.exit(0)
    time.sleep(3)
