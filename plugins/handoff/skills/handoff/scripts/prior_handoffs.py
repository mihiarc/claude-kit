#!/usr/bin/env python3
"""List a project's earlier handoffs before you write a new one.

Usage:
    python3 prior_handoffs.py [repo-root] [--name NAME]... [--json]
    python3 prior_handoffs.py --archive ENTRY [ENTRY ...]

A project keeps one live handoff, ~/.claude/handoffs/<name>.md. Writing over
that path without looking loses things:
  - a prompt the user wrote but has not launched yet;
  - the record of what an already-launched session was told;
  - after a rename, nothing is overwritten at all. The old file sits under the
    old name and goes stale beside the new one.
This script reports what is already there, so the writer can decide per
SKILL.md Step 6.

Names searched: the repo directory's name; the git remote's repository name
(these differ after a rename, or when the local clone has a different name);
and each --name.

An entry directly in the handoffs directory is reported when its name is
  exact    <name>.md, or <name>/ (the directory for the prompt's companion files)
  variant  anything starting with <name>--, <name>- or <name>. That can be another
           task of this project, a companion file saved beside the prompt, a
           hand-made dated copy, or an unrelated project sharing the prefix.
           Its Goal line tells you which.

For each prompt (.md) it prints the date it was written, its Goal line, and
whether a session was launched from it. A launch is a session transcript under
~/.claude/projects/ with a user-typed message naming the file, timestamped after
the file was last written. That is how
    claude --name <name> "read ~/.claude/handoffs/<name>.md and follow it"
shows up. A typed mention in the session that wrote the prompt also counts, so
treat "launched" as "someone read it after it was written". A session that
picked up the task without naming the file is invisible here, so "not launched"
means no session named the file after it was written. It does not mean the work
was never done.

--archive moves each ENTRY (a name in the handoffs directory, or a path to one)
into ~/.claude/handoffs/archive/ as <stem>.<YYYY-MM-DD><ext>, dated by the
entry's modification time. It adds -2, -3 ... rather than overwrite anything.
Nothing is ever deleted.

Exit status: 0, or 1 if an --archive entry was missing or outside the handoffs
directory.
"""

import argparse
import datetime as dt
import json
import mmap
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
HANDOFFS = HOME / ".claude" / "handoffs"
TRANSCRIPTS = HOME / ".claude" / "projects"
SEPARATORS = ("--", "-", ".")


def project_names(root, extra):
    names = []
    if root:
        path = Path(root).expanduser().resolve()
        names.append(path.name)
        try:
            url = subprocess.run(
                ["git", "-C", str(path), "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            url = ""
        if url:
            # git@github.com:org/repo.git and https://host/org/repo(.git) both
            # end in the repository name.
            tail = re.sub(r"\.git$", "", url.rstrip("/"))
            names.append(re.split(r"[/:]", tail)[-1])
    names.extend(extra or [])
    return list(dict.fromkeys(n for n in names if n))


def classify(entry, names):
    stem = entry.name[:-3] if entry.name.endswith(".md") else entry.name
    for name in names:
        if stem == name:
            return "exact", name
    for name in names:
        if any(entry.name.startswith(name + sep) for sep in SEPARATORS):
            return "variant", name
    return None, None


def goal_line(path, width=110):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _, line in zip(range(60), fh):
                if line.startswith("Goal:"):
                    line = line.strip()
                    return line if len(line) <= width else line[: width - 1] + "…"
    except OSError:
        pass
    return ""


def typed_text(content):
    """Text the user typed: a plain string, or the text parts of a content list.
    Tool results are left out, so an `ls` that printed the path is no launch."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def epoch(timestamp):
    try:
        return dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def find_launches(prompts, transcripts_dir):
    """First user-typed mention of each prompt, after it was last written.

    One pass over the session transcripts (top level only; subagent transcripts
    live deeper and are never launched from a handoff). Files older than the
    oldest prompt are skipped, and a file is parsed only if a fast byte search
    finds a prompt's name in it.
    """
    if not prompts:
        return {}
    needles = {p: ("handoffs/" + p.name).encode() for p in prompts}
    written = {p: p.stat().st_mtime for p in prompts}
    oldest = min(written.values())
    found = {}
    for transcript in transcripts_dir.glob("*/*.jsonl"):
        try:
            if transcript.stat().st_mtime < oldest or transcript.stat().st_size == 0:
                continue
            with open(transcript, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                hits = [p for p, needle in needles.items() if mm.find(needle) != -1]
                if not hits:
                    continue
                for raw in iter(mm.readline, b""):
                    live = [p for p in hits if needles[p] in raw]
                    if not live:
                        continue
                    try:
                        record = json.loads(raw)
                    except ValueError:
                        continue
                    if record.get("type") != "user" or record.get("isMeta"):
                        continue
                    text = typed_text((record.get("message") or {}).get("content"))
                    when = epoch(record.get("timestamp"))
                    if when is None:
                        continue
                    for p in live:
                        if needles[p].decode() in text and when > written[p]:
                            if p not in found or when < found[p]["at"]:
                                found[p] = {
                                    "at": when,
                                    "project": transcript.parent.name,
                                    "session": transcript.stem,
                                }
        except (OSError, ValueError):
            continue
    return found


def hint(item, current):
    if item["kind"] != "prompt":
        return "companion: archive it unless the new prompt cites it"
    if item["match"] == "variant":
        return "read its Goal: another task of this project, or another project"
    if item["matched_name"] != current:
        return "former name: archive it, write under the current name"
    if item["launched"]:
        return "launched: archive it, then write"
    return "not launched: same task -> archive; different task -> ask the user"


def list_handoffs(args):
    names = project_names(args.root, args.name)
    if not names:
        print("no project name: pass a repo root or --name", file=sys.stderr)
        return 2
    handoffs = Path(args.handoffs_dir).expanduser()
    entries = []
    if handoffs.is_dir():
        for entry in sorted(handoffs.iterdir()):
            if entry.name == "archive" or entry.name.startswith("."):
                continue
            match, name = classify(entry, names)
            if match:
                entries.append((entry, match, name))
    prompts = [e for e, _, _ in entries if e.is_file() and e.suffix == ".md"]
    launches = find_launches(prompts, Path(args.transcripts_dir).expanduser())

    items = []
    for entry, match, name in entries:
        is_prompt = entry.is_file() and entry.suffix == ".md"
        launch = launches.get(entry)
        items.append({
            "entry": entry.name + ("/" if entry.is_dir() else ""),
            "kind": "prompt" if is_prompt else "companion",
            "match": match,
            "matched_name": name,
            "written": dt.datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "goal": goal_line(entry) if is_prompt else "",
            "launched": (
                {**launch, "at": dt.datetime.fromtimestamp(launch["at"]).strftime("%Y-%m-%d %H:%M")}
                if launch else None
            ),
        })
    for item in items:
        item["hint"] = hint(item, names[0])

    if args.json:
        print(json.dumps({"names": names, "handoffs_dir": str(handoffs), "entries": items}, indent=2))
        return 0

    print(f"Names: {', '.join(names)}   (current: {names[0]})   in {handoffs}")
    if not items:
        print(f"  nothing yet -> write {names[0]}.md")
        return 0
    for item in items:
        status = ""
        if item["kind"] == "prompt":
            launch = item["launched"]
            status = f"launched {launch['at']} ({launch['project']})" if launch else "not launched"
        print(f"  {item['match']:<8} {item['entry']:<48} {item['written']}  {status}")
        if item["goal"]:
            print(f"           {item['goal']}")
        print(f"           -> {item['hint']}")
    return 0


def archive(args):
    handoffs = Path(args.handoffs_dir).expanduser().resolve()
    dest = handoffs / "archive"
    status = 0
    for raw in args.archive:
        source = Path(raw).expanduser()
        if not source.exists():
            source = handoffs / raw
        if not source.exists():
            print(f"MISSING  {raw}")
            status = 1
            continue
        source = source.resolve()
        if source.parent != handoffs:
            print(f"REFUSED  {raw}: not directly in {handoffs}")
            status = 1
            continue
        date = dt.date.fromtimestamp(source.stat().st_mtime).isoformat()
        stem, ext = (source.stem, source.suffix) if source.is_file() else (source.name, "")
        dest.mkdir(exist_ok=True)
        target = dest / f"{stem}.{date}{ext}"
        n = 2
        while target.exists():
            target = dest / f"{stem}.{date}-{n}{ext}"
            n += 1
        shutil.move(str(source), str(target))
        print(f"archived {source.name} -> archive/{target.name}")
    return status


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("root", nargs="?", help="repo root (its name and git remote name are searched)")
    parser.add_argument("--name", action="append", help="another name to search (no-repo slug, former name)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--archive", nargs="+", metavar="ENTRY", help="move entries into archive/")
    parser.add_argument("--handoffs-dir", default=str(HANDOFFS))
    parser.add_argument("--transcripts-dir", default=str(TRANSCRIPTS))
    args = parser.parse_args(argv[1:])
    if args.archive:
        return archive(args)
    return list_handoffs(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
