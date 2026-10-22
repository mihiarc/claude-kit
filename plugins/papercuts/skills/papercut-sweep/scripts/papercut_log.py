#!/usr/bin/env python3
"""Read and edit a papercut log and its gotchas file during a sweep.

The log holds one bullet per papercut, `- date · symptom · fix · project`. The gotchas file
holds settled answers as bullets under `## <tool>` headings. Log entries are addressed by a
short hash of their text, so lines that other sessions append between triage and the edit
are kept, and an entry that changed since triage is refused rather than overwritten.

Usage:
    python3 papercut_log.py summary LOG [FILTERS]
    python3 papercut_log.py export LOG OUT.json [FILTERS] [--batches N]
    python3 papercut_log.py sections GOTCHAS
    python3 papercut_log.py prs LOG [--owner OWNER]...
    python3 papercut_log.py merge LOG TRIAGE.json... [--overrides O.json] --plan PLAN.json --review REVIEW.md [--gotchas GOTCHAS]
    python3 papercut_log.py apply PLAN.json [--preview-dir DIR | --write --backup-dir DIR]

FILTERS are --since DATE, --project NAME (repeatable), --ids IDS and --exclude-ids IDS. A
project matches an entry's project field or its group (the first ` / ` part of the project,
without `--worktree`, `(note)` or `#N`), whole or as its first words, ignoring case. IDS is a
comma-separated list or @FILE (a JSON list of ids or of objects with "id", or ids separated
by whitespace). With --batches N, export splits the entries by group into N files of similar
size, OUT-1.json to OUT-N.json.

`prs` checks every PR or issue the log cites: `owner/repo#N` as written, `repo#N` under each
--owner in turn, and a bare `#N` against the entry's group under each --owner, marked as a
guess. Open PRs show their age, size, checks and review state.

`merge` joins triage results (one JSON list per file, one object per entry, fields as in
references/triage-brief.md) with optional overrides (same shape; an override's fields win,
and it may add entries the triage files lack) into a first-apply plan, and writes a review
file that lists every decision in full. Entries whose outcome is repo-note, repo-fix or
machine-fix are held: they stay in the log and are listed under "held" for the second apply.
An entry with "same_as" follows the outcome of the entry it names.

`apply` prints a unified diff and totals for the planned edit, with --preview-dir writes the
planned files there for checking, and writes the real files only with --write, which requires
--backup-dir. The first backup of each file in that directory is kept, so it
stays the pre-sweep copy, and each written plan is copied in beside it. A plan is JSON:

    {
      "log": "/abs/path/papercuts.md",
      "gotchas": "/abs/path/gotchas.md",
      "delete": {"<id>": "reason", ...},
      "replace": {"<id>": "- new bullet text"},
      "prepend": ["- bullet for the top of the log"],
      "append": ["- bullet for the end of the log"],
      "gotchas_add": [{"section": "uv", "line": "- symptom → what works"}],
      "gotchas_replace": [{"old": "- exact existing line", "new": "- new line, or \\"\\" to drop it"},
                          {"old_prefix": "- the first words of one line", "new": "..."}],
      "held": {"<id>": "why it stays for now"}
    }

Every key but "log" is optional, "delete" may also be a plain list of ids, and "gotchas" is
needed only with the gotchas_* keys. A gotchas_add section that does not exist is created at
the end of the file. "held" and "notes" are carried for the record and not applied.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SEP = " · "
DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")
FULL_REF = re.compile(r"(?<![\w/.-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)\b")
SHORT_REF = re.compile(r"(?<![\w/.#-])([A-Za-z][A-Za-z0-9_.-]*)#(\d+)\b")
BARE_REF = re.compile(r"(?<![\w/.#-])#(\d+)\b")
NOT_REPOS = {"pr", "prs", "issue", "issues", "pull", "gh"}
OPEN_FIELD = re.compile(r"\s*open\s*(?:[,:;]|$)", re.IGNORECASE)
OUTCOMES = {"delete", "gotcha", "repo-note", "repo-fix", "machine-fix", "open", "keep"}
HELD = {"repo-note", "repo-fix", "machine-fix"}


def entry_id(text: str) -> str:
    return hashlib.sha1(text.strip().encode()).hexdigest()[:8]


def group_of(project: str) -> str:
    first = project.split(" / ")[0]
    return re.sub(r"#\d+|--[\w.-]+|\s*\(.*?\)", "", first).strip()


def cited_refs(text: str) -> list[str]:
    refs = [f"{m[1]}#{m[2]}" for m in FULL_REF.finditer(text)]
    rest = FULL_REF.sub(" ", text)
    for m in SHORT_REF.finditer(rest):
        if m[1].lower() not in NOT_REPOS:
            refs.append(f"{m[1]}#{m[2]}")
    rest = SHORT_REF.sub(" ", rest)
    refs += [f"#{m[1]}" for m in BARE_REF.finditer(rest)]
    return sorted(set(refs))


def parse_blocks(lines: list[str]) -> list[dict]:
    """Split log lines into entry blocks and other blocks (blank lines, headings, prose).

    An entry starts at a top-level `- ` bullet; non-blank lines after it that are not a
    heading or another top-level bullet are its continuation.
    """
    blocks: list[dict] = []
    for line in lines:
        if line.startswith("- "):
            blocks.append({"entry": True, "lines": [line]})
        elif line.strip() and not line.startswith("#") and blocks and blocks[-1]["entry"]:
            blocks[-1]["lines"].append(line)
        else:
            blocks.append({"entry": False, "lines": [line]})
    return blocks


def describe(block: dict, line_no: int) -> dict:
    text = "".join(block["lines"]).rstrip("\n")
    fields = block["lines"][0][2:].rstrip("\n").split(SEP)
    date = fields[0].strip() if DATE.match(fields[0].strip()) else ""
    project = fields[-1].strip() if len(fields) >= 3 else ""
    middle = fields[2:-1] if len(fields) >= 4 else fields[1:-1]
    return {
        "id": entry_id(text),
        "line": line_no,
        "date": date,
        "project": project,
        "group": group_of(project),
        "open": any(OPEN_FIELD.match(f) for f in middle) or bool(re.search(r"\bOPEN\b", text)),
        "refs": cited_refs(text),
        "text": text,
    }


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def entries(path: Path) -> list[dict]:
    out, line_no = [], 1
    for block in parse_blocks(read_lines(path)):
        if block["entry"]:
            out.append(describe(block, line_no))
        line_no += len(block["lines"])
    return out


def symptom(e: dict, width: int = 110) -> str:
    fields = e["text"].split(SEP)
    s = fields[1] if len(fields) > 1 else e["text"]
    return s if len(s) <= width else s[: width - 1] + "…"


def parse_ids(spec: str | None) -> set[str]:
    if not spec:
        return set()
    if spec.startswith("@"):
        raw = Path(spec[1:]).read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return set(raw.split())
        return {d["id"] if isinstance(d, dict) else str(d) for d in data}
    return {s.strip() for s in spec.split(",") if s.strip()}


def project_matches(e: dict, wanted: set[str]) -> bool:
    for value in (e["project"].lower(), e["group"].lower()):
        if any(value == p or value.startswith(p + " ") for p in wanted):
            return True
    return False


def select(items: list[dict], args) -> list[dict]:
    wanted = {p.lower() for p in args.project}
    ids, skip = parse_ids(args.ids), parse_ids(args.exclude_ids)
    return [
        e
        for e in items
        if (not args.since or (e["date"] and e["date"] >= args.since))
        and (not wanted or project_matches(e, wanted))
        and (not ids or e["id"] in ids)
        and e["id"] not in skip
    ]


def cmd_summary(args) -> int:
    items = select(entries(Path(args.log)), args)
    if not items:
        print("no entries match")
        return 0
    dates = sorted(e["date"] for e in items if e["date"])
    span = f", {dates[0]} to {dates[-1]}" if dates else ""
    n_open = sum(e["open"] for e in items)
    n_refs = sum(bool(e["refs"]) for e in items)
    print(f"{len(items)} entries ({n_open} open, {n_refs} citing a PR or issue){span}")
    print("by group:")
    for group, n in collections.Counter(e["group"] or "(none)" for e in items).most_common():
        print(f"  {n:4d}  {group}")
    by_date = collections.Counter(e["date"] or "(undated)" for e in items)
    print("by date: " + "  ".join(f"{d[5:] if DATE.match(d) else d}:{n}" for d, n in sorted(by_date.items())))
    return 0


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_export(args) -> int:
    items = select(entries(Path(args.log)), args)
    out = Path(args.out)
    if not args.batches or args.batches < 2:
        write_json(out, items)
        print(f"wrote {len(items)} entries to {out}")
        return 0
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for e in items:
        groups[e["group"] or "(none)"].append(e)
    batches: list[list[dict]] = [[] for _ in range(args.batches)]
    names: list[list[str]] = [[] for _ in range(args.batches)]
    for name, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        i = min(range(args.batches), key=lambda j: len(batches[j]))
        batches[i].extend(members)
        names[i].append(name)
    for i, batch in enumerate(batches, 1):
        path = out.with_name(f"{out.stem}-{i}{out.suffix or '.json'}")
        batch.sort(key=lambda e: e["line"])
        write_json(path, batch)
        print(f"wrote {len(batch):3d} entries to {path}: {', '.join(names[i - 1])}")
    return 0


def cmd_sections(args) -> int:
    counts: dict[str, list[int]] = {}
    current = None
    for line in read_lines(Path(args.gotchas)):
        if line.startswith("## "):
            current = line[3:].strip()
            counts[current] = [0, 0]
        elif current and line.startswith("- "):
            counts[current][0] += 1
            counts[current][1] += bool(re.search(r"<!--.*-->\s*$", line))
    print("  lines  triggered  section")
    for name, (n, t) in counts.items():
        print(f"  {n:5d}  {t:9d}  {name}")
    return 0


PR_FIELDS = "state,mergedAt,closedAt,createdAt,title,mergeable,reviewDecision,additions,deletions,statusCheckRollup"


def gh_json(*argv: str) -> dict | None:
    try:
        out = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else None


def lookup(repo: str, num: str) -> tuple[str, dict] | None:
    info = gh_json("pr", "view", num, "-R", repo, "--json", PR_FIELDS)
    if info is not None:
        return "PR", info
    info = gh_json("issue", "view", num, "-R", repo, "--json", "state,closedAt,createdAt,title")
    return ("issue", info) if info is not None else None


def checks_state(rollup: list[dict] | None) -> str:
    if not rollup:
        return "no CI"
    states = {(c.get("conclusion") or c.get("state") or "PENDING").upper() for c in rollup}
    if states & {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"}:
        return "checks fail"
    if states & {"PENDING", "IN_PROGRESS", "QUEUED", "EXPECTED", ""}:
        return "checks pending"
    return "checks pass"


def describe_ref(kind: str, info: dict) -> str:
    title = info["title"][:60]
    if kind == "PR" and info["state"] == "OPEN":
        created = dt.datetime.fromisoformat(info["createdAt"].replace("Z", "+00:00"))
        age = (dt.datetime.now(dt.timezone.utc) - created).days
        review = (info.get("reviewDecision") or "no review").lower().replace("_", " ")
        merge = "conflicts" if info.get("mergeable") == "CONFLICTING" else "mergeable"
        return (
            f"PR OPEN {age:3d}d  +{info['additions']}/-{info['deletions']}  "
            f"{checks_state(info.get('statusCheckRollup'))}, {review}, {merge}  {title}"
        )
    when = (info.get("mergedAt") or info.get("closedAt") or "")[:10]
    return f"{kind} {info['state']} {when}  {title}"


def cmd_prs(args) -> int:
    # (as written, entry group for a bare ref) -> entry ids
    cited: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for e in entries(Path(args.log)):
        for ref in e["refs"]:
            cited[(ref, e["group"] if ref.startswith("#") else "")].append(e["id"])
    if not cited:
        print("the log cites no PR or issue references")
        return 0

    def candidates(ref: str, group: str) -> list[str]:
        name, num = ref.split("#")
        if "/" in name:
            return [name]
        repo = name or group
        if not repo or " " in repo:
            return []
        return [repo] if "/" in repo else [f"{o}/{repo}" for o in args.owner]

    def resolve(key: tuple[str, str]) -> tuple[str, bool, str]:
        ref, group = key
        num = ref.split("#")[1]
        for repo in candidates(ref, group):
            found = lookup(repo, num)
            if found:
                return f"{repo}#{num}", ref.startswith("#"), describe_ref(*found)
        why = "no --owner given" if not args.owner and "/" not in ref else "gh could not find it"
        return ref + (f" in {group}" if group else ""), False, f"UNRESOLVED ({why})"

    keys = sorted(cited)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        resolved = list(pool.map(resolve, keys))
    # One row per resolved PR or issue; it is a guess only if every citation was a bare #N.
    rows: dict[str, dict] = {}
    for key, (label, guess, detail) in zip(keys, resolved):
        row = rows.setdefault(label, {"guess": True, "detail": detail, "ids": []})
        row["guess"] = row["guess"] and guess
        row["ids"] += [i for i in cited[key] if i not in row["ids"]]
    for label, row in sorted(rows.items()):
        name = label + (" (guess)" if row["guess"] else "")
        print(f"{name:44s}  {row['detail']}  entries {','.join(row['ids'])}")
    return 0


class PlanError(Exception):
    pass


def delete_ids(plan: dict) -> set[str]:
    d = plan.get("delete", [])
    return set(d) if isinstance(d, (list, dict)) else set()


def plan_log(lines: list[str], plan: dict) -> list[str]:
    blocks = parse_blocks(lines)
    by_id: dict[str, list[int]] = collections.defaultdict(list)
    for i, b in enumerate(blocks):
        if b["entry"]:
            by_id[entry_id("".join(b["lines"]))].append(i)

    delete = delete_ids(plan)
    replace = plan.get("replace", {})
    missing = sorted((delete | set(replace)) - set(by_id))
    if missing:
        raise PlanError(
            "entries not in the log (changed or removed since export; re-export and re-triage them): "
            + ", ".join(missing)
        )
    both = delete & set(replace)
    if both:
        raise PlanError("ids both deleted and replaced: " + ", ".join(sorted(both)))
    for eid in replace:
        if len(by_id[eid]) > 1:
            raise PlanError(f"id {eid} matches {len(by_id[eid])} identical entries; delete the duplicates instead")

    for new in [*replace.values(), *plan.get("prepend", []), *plan.get("append", [])]:
        if not new.startswith("- ") or "\n" in new.strip():
            raise PlanError(f"log lines must be one `- ` bullet: {new[:80]!r}")

    out: list[str] = []
    for b in blocks:
        if not b["entry"]:
            out.extend(b["lines"])
            continue
        eid = entry_id("".join(b["lines"]))
        if eid in delete:
            continue
        if eid in replace:
            out.append(replace[eid].rstrip("\n") + "\n")
        else:
            out.extend(b["lines"])

    # Prepended bullets go after any heading or prose that opens the file, spaced like the
    # first entry already there.
    head = 0
    while head < len(out) and not out[head].startswith("- "):
        head += 1
    if head == len(out):
        head = 0
    spaced = head + 1 < len(out) and not out[head + 1].strip()
    for p in reversed(plan.get("prepend", [])):
        out[head:head] = [p.rstrip("\n") + "\n"] + (["\n"] if spaced else [])
    if out and not out[-1].endswith("\n"):
        out[-1] += "\n"
    out.extend(a.rstrip("\n") + "\n" for a in plan.get("append", []))
    return squeeze_blank_runs(out)


def squeeze_blank_runs(lines: list[str]) -> list[str]:
    """Drop leading blank lines and collapse runs of blank lines that deletions leave."""
    out: list[str] = []
    for line in lines:
        if not line.strip() and (not out or not out[-1].strip()):
            continue
        out.append(line)
    return out


def plan_gotchas(lines: list[str], plan: dict) -> tuple[list[str], list[str], collections.Counter]:
    notes: list[str] = []
    stats: collections.Counter = collections.Counter()
    out = list(lines)
    for item in plan.get("gotchas_replace", []):
        new = item.get("new", "").rstrip("\n")
        if "old" in item:
            old = item["old"].rstrip("\n")
            hits = [i for i, l in enumerate(out) if l.rstrip("\n") == old]
        else:
            old = item["old_prefix"].rstrip("\n").rstrip("…").rstrip()
            hits = [i for i, l in enumerate(out) if l.startswith(old)]
        if len(hits) != 1:
            raise PlanError(f"gotchas_replace needs exactly one matching line, found {len(hits)}: {old[:80]!r}")
        if new and (not new.startswith("- ") or "\n" in new):
            raise PlanError(f"gotchas lines must be one `- ` bullet: {new[:80]!r}")
        if new:
            out[hits[0]] = new + "\n"
            stats["replaced"] += 1
        else:
            del out[hits[0]]
            stats["removed"] += 1

    existing = {l.rstrip("\n") for l in out}
    for item in plan.get("gotchas_add", []):
        section, line = item["section"].strip(), item["line"].rstrip("\n")
        if not line.startswith("- ") or "\n" in line:
            raise PlanError(f"gotchas lines must be one `- ` bullet: {line[:80]!r}")
        if line in existing:
            notes.append(f"skipped, already present: {line[:70]}")
            continue
        heads = [i for i, l in enumerate(out) if l.startswith("## ") and l[3:].strip().lower() == section.lower()]
        if not heads:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            if out and out[-1].strip():
                out.append("\n")
            out.extend([f"## {section}\n", "\n"])
            heads = [len(out) - 2]
            notes.append(f"created section: {section}")
            stats["sections"] += 1
        floor = heads[0] + 1
        if floor < len(out) and not out[floor].strip():
            floor += 1
        end = floor
        while end < len(out) and not out[end].startswith("#"):
            end += 1
        while end > floor and not out[end - 1].strip():
            end -= 1
        out.insert(end, line + "\n")
        existing.add(line)
        stats["added"] += 1
    return out, notes, stats


def bullet_count(lines: list[str]) -> int:
    return sum(1 for l in lines if l.startswith("- "))


def plan_files(plan: dict) -> tuple[list[tuple[str, Path]], dict, dict, list[str], str]:
    """Compute the planned contents of the log and gotchas files and a one-line total."""
    targets = [("log", Path(plan["log"]).expanduser())]
    if plan.get("gotchas_add") or plan.get("gotchas_replace"):
        if "gotchas" not in plan:
            raise PlanError('plan has gotchas_* edits but no "gotchas" path')
        targets.append(("gotchas", Path(plan["gotchas"]).expanduser()))
    before = {name: read_lines(p) for name, p in targets}
    after = {"log": plan_log(before["log"], plan)}
    notes: list[str] = []
    total = f"log: {bullet_count(before['log'])} -> {bullet_count(after['log'])} entries"
    if "gotchas" in before:
        after["gotchas"], notes, stats = plan_gotchas(before["gotchas"], plan)
        total += (
            f"; gotchas: {bullet_count(before['gotchas'])} -> {bullet_count(after['gotchas'])} lines "
            f"(+{stats['added']} added, {stats['replaced']} replaced, {stats['removed']} removed"
            + (f", {stats['sections']} new sections" if stats["sections"] else "")
            + ")"
        )
    return targets, before, after, notes, total


def write_atomic(path: Path, lines: list[str]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(lines)
    shutil.copymode(path, tmp)
    os.replace(tmp, path)


def backup(path: Path, backup_dir: Path) -> str:
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / path.name
    if dest.exists():
        return f"kept existing backup {dest}"
    shutil.copy2(path, dest)
    return f"backed up to {dest}"


def cmd_apply(args) -> int:
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if args.write and not args.backup_dir:
        print("--write needs --backup-dir", file=sys.stderr)
        return 2

    # Another session can append between our read and our write; recompute if it did.
    for _ in range(3):
        try:
            targets, before, after, notes, total = plan_files(plan)
        except PlanError as e:
            print(f"plan refused: {e}", file=sys.stderr)
            return 1
        for name, p in targets:
            sys.stdout.writelines(difflib.unified_diff(before[name], after[name], str(p), f"{p} (planned)"))
        for n in notes:
            print(f"note: {n}")
        if not args.write:
            if args.preview_dir:
                preview = Path(args.preview_dir).expanduser()
                preview.mkdir(parents=True, exist_ok=True)
                for name, p in targets:
                    (preview / p.name).write_text("".join(after[name]), encoding="utf-8")
                print(f"planned files written to {preview}")
            print(f"dry run, {total}; rerun with --write --backup-dir DIR to apply")
            return 0
        if all(read_lines(p) == before[name] for name, p in targets):
            backup_dir = Path(args.backup_dir).expanduser()
            for name, p in targets:
                print(backup(p, backup_dir))
                write_atomic(p, after[name])
            stamp = dt.datetime.now().strftime("%H%M%S")
            shutil.copy2(plan_path, backup_dir / f"plan-{stamp}.json")
            print(f"wrote {total}")
            return 0
        print("a file changed while planning; recomputing", file=sys.stderr)
    print("files kept changing; try again", file=sys.stderr)
    return 1


def cmd_merge(args) -> int:
    log = Path(args.log)
    by_id = {e["id"]: e for e in entries(log)}
    decisions: dict[str, dict] = {}
    for path in args.triage:
        for d in json.loads(Path(path).read_text(encoding="utf-8")):
            decisions[d["id"]] = dict(d)
    if args.overrides:
        for d in json.loads(Path(args.overrides).read_text(encoding="utf-8")):
            decisions[d["id"]] = {**decisions.get(d["id"], {}), **d}

    problems = [f"{i}: not in the log (changed since export?)" for i in decisions if i not in by_id]
    for i, d in decisions.items():
        if d.get("outcome") not in OUTCOMES:
            problems.append(f"{i}: unknown outcome {d.get('outcome')!r}")
        if d.get("same_as") and d["same_as"] not in decisions:
            problems.append(f"{i}: same_as {d['same_as']} has no decision")
        if d.get("outcome") == "gotcha" and not d.get("same_as") and not (d.get("line") and d.get("section")):
            problems.append(f"{i}: gotcha needs section and line (or same_as)")
    if problems:
        print("merge refused:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1

    def effective(d: dict) -> str:
        seen = set()
        while d.get("same_as") and d["id"] not in seen:
            seen.add(d["id"])
            d = decisions[d["same_as"]]
        return d["outcome"]

    plan: dict = {"log": str(log)}
    if args.gotchas:
        plan["gotchas"] = args.gotchas
    delete, replace, held = {}, {}, {}
    adds, reps, seen_lines = [], [], set()
    buckets: dict[str, list[tuple[dict, dict]]] = collections.defaultdict(list)
    for i, d in decisions.items():
        e, outcome = by_id[i], effective(d)
        reason = d.get("reason", "")
        if d.get("same_as"):
            reason = f"same as {d['same_as']}" + (f": {reason}" if reason else "")
        if outcome in HELD:
            held[i] = f"{outcome}" + (f" in {d.get('repo')}" if d.get("repo") else "") + (f": {reason}" if reason else "")
        elif outcome == "keep":
            pass
        elif outcome == "open" and not d.get("same_as"):
            line = (d.get("line") or "").strip()
            if line and line != e["text"]:
                replace[i] = line
        else:
            delete[i] = (f"→ gotchas ({d.get('section')}): " if outcome == "gotcha" and not d.get("same_as") else "") + reason
        if outcome == "gotcha" and not d.get("same_as"):
            line = d["line"].strip()
            if d.get("replaces"):
                reps.append({"old_prefix": d["replaces"], "new": line})
            elif line not in seen_lines:
                adds.append({"section": d["section"], "line": line})
            seen_lines.add(line)
        buckets["same_as" if d.get("same_as") else outcome].append((d, e))
    plan.update(
        {k: v for k, v in (("delete", delete), ("replace", replace), ("gotchas_add", adds), ("gotchas_replace", reps), ("held", held)) if v}
    )
    if (adds or reps) and "gotchas" not in plan:
        print("merge refused: gotchas edits need --gotchas", file=sys.stderr)
        return 1
    write_json(Path(args.plan), plan)

    try:
        _, _, _, notes, total = plan_files(plan)
    except PlanError as e:
        print(f"plan written to {args.plan} but refused by apply: {e}", file=sys.stderr)
        return 1

    untriaged = [e for i, e in by_id.items() if i not in decisions]
    write_review(Path(args.review), buckets, untriaged, total)
    counts = ", ".join(f"{k} {len(v)}" for k, v in sorted(buckets.items(), key=lambda kv: -len(kv[1])))
    print(f"{len(decisions)} decisions ({counts}); {len(untriaged)} entries untriaged")
    print(f"first apply: {total}")
    for n in notes:
        print(f"note: {n}")
    print(f"wrote {args.plan} and {args.review}")
    return 0


def write_review(path: Path, buckets: dict, untriaged: list[dict], total: str) -> None:
    out = ["# Papercut sweep: every decision", "", f"First apply: {total}.", ""]

    def head(title: str, items: list) -> None:
        out.extend([f"## {title} ({len(items)})", ""])

    if buckets.get("gotcha"):
        head("Gotchas", buckets["gotcha"])
        by_section: dict[str, list] = collections.defaultdict(list)
        for d, e in buckets["gotcha"]:
            by_section[d["section"]].append((d, e))
        followers = collections.defaultdict(list)
        for d, e in buckets.get("same_as", []):
            followers[d["same_as"]].append(d["id"])
        for section, items in by_section.items():
            out.extend([f"### {section}", ""])
            for d, e in items:
                also = f" (also {', '.join(followers[d['id']])})" if followers.get(d["id"]) else ""
                verb = f"replaces `{d['replaces'][:70]}…`" if d.get("replaces") else "adds"
                out.append(f"- `{d['id']}`{also} {verb}:")
                out.append(f"  {d['line'].strip()}")
            out.append("")
    for outcome, title in (("repo-note", "Repo notes (held)"), ("repo-fix", "Repo fixes (held)"), ("machine-fix", "Machine fixes (held)")):
        if buckets.get(outcome):
            head(title, buckets[outcome])
            for d, e in buckets[outcome]:
                out.append(f"- `{d['id']}` {e['project']}: {symptom(e)}")
                for key in ("repo", "change", "verified"):
                    if d.get(key):
                        out.append(f"  - {key}: {d[key]}")
            out.append("")
    if buckets.get("open"):
        head("Open", buckets["open"])
        for d, e in buckets["open"]:
            out.append(f"- `{d['id']}` {(d.get('line') or e['text']).strip()}")
        out.append("")
    if buckets.get("delete"):
        head("Delete", buckets["delete"])
        for d, e in buckets["delete"]:
            out.append(f"- `{d['id']}` {e['project']}: {symptom(e, 80)} — {d.get('reason', '')}")
        out.append("")
    if buckets.get("same_as"):
        head("Folded into another entry", buckets["same_as"])
        for d, e in buckets["same_as"]:
            out.append(f"- `{d['id']}` → `{d['same_as']}`: {symptom(e, 80)}")
        out.append("")
    left = [(d, e) for d, e in buckets.get("keep", [])]
    if left or untriaged:
        out.extend([f"## Left alone ({len(left) + len(untriaged)})", ""])
        for d, e in left:
            out.append(f"- `{d['id']}` {e['project']}: {symptom(e, 80)} — {d.get('reason', 'kept')}")
        for e in untriaged:
            out.append(f"- `{e['id']}` {e['project']}: {symptom(e, 80)} — not triaged")
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("summary", "export"):
        p = sub.add_parser(name)
        p.add_argument("log")
        if name == "export":
            p.add_argument("out")
            p.add_argument("--batches", type=int)
        p.add_argument("--since")
        p.add_argument("--project", action="append", default=[])
        p.add_argument("--ids")
        p.add_argument("--exclude-ids")
    sub.add_parser("sections").add_argument("gotchas")
    p = sub.add_parser("prs")
    p.add_argument("log")
    p.add_argument("--owner", action="append", default=[])
    p = sub.add_parser("merge")
    p.add_argument("log")
    p.add_argument("triage", nargs="+")
    p.add_argument("--overrides")
    p.add_argument("--gotchas")
    p.add_argument("--plan", required=True)
    p.add_argument("--review", required=True)
    p = sub.add_parser("apply")
    p.add_argument("plan")
    p.add_argument("--write", action="store_true")
    p.add_argument("--backup-dir")
    p.add_argument("--preview-dir")
    args = ap.parse_args()
    commands = {
        "summary": cmd_summary,
        "export": cmd_export,
        "sections": cmd_sections,
        "prs": cmd_prs,
        "merge": cmd_merge,
        "apply": cmd_apply,
    }
    return commands[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
