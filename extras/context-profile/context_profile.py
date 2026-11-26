#!/usr/bin/env python3
"""Profile context size and token cost across your top-level Claude Code sessions.

Reads the main-thread transcripts in ~/.claude/projects/*/*.jsonl modified in the
last --days days (subagent turns are skipped). Each API response is counted once,
deduplicated by message id. Context at a turn is input + cache read + cache write
tokens. Cost is in input-token equivalents at Anthropic's relative prices:
input 1, cache write 1.25, cache read 0.1, output 5.

Reports:
  - peak context per session (percentiles, share of sessions past set sizes);
  - turns and cost by the context size at the turn;
  - for sessions with 30+ turns, context at turns 1, 10 and 30 and turns until 150K.

--split SUBSTRING (repeatable) groups sessions by whether their first user message
contains any of the substrings, e.g. the prompt your launcher passes to new sessions.

Usage: context_profile.py [--days 30] [--split "Start on the task in"]
"""
import argparse, glob, json, os, time
from collections import defaultdict

BUCKETS = [0, 50_000, 100_000, 150_000, 200_000, 250_000, 300_000, 400_000, 10**9]
CTX_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def text_of(content):
    if isinstance(content, str):
        return content
    return " ".join(x.get("text", "") for x in content or [] if isinstance(x, dict))


def read_session(path, split):
    """Return (per-turn [(context, cost)], matched_split) for one transcript."""
    seen, turns, first_user, matched = set(), [], True, False
    try:
        fh = open(path, errors="replace")
    except OSError:
        return [], False
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain"):
                continue
            m = d.get("message") or {}
            if d.get("type") == "user" and first_user:
                first_user = False
                txt = text_of(m.get("content"))
                matched = any(s in txt for s in split)
            u = m.get("usage")
            if not u or d.get("type") != "assistant":
                continue
            mid = m.get("id") or d.get("uuid")
            if mid in seen:
                continue
            seen.add(mid)
            ctx = sum(u.get(k) or 0 for k in CTX_KEYS)
            cost = ((u.get("input_tokens") or 0) + 1.25 * (u.get("cache_creation_input_tokens") or 0)
                    + 0.1 * (u.get("cache_read_input_tokens") or 0) + 5 * (u.get("output_tokens") or 0))
            turns.append((ctx, cost))
    return turns, matched


def med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def report(label, sessions):
    n = len(sessions)
    if not n:
        return
    total = sum(c for s in sessions for _, c in s)
    print(f"== {label}: {n} sessions, {total/1e6:.0f}M input-token equivalents")
    peaks = sorted(max(x for x, _ in s) for s in sessions)
    q = lambda p: peaks[min(n - 1, int(p * n))] // 1000
    print(f"Peak context per session: p50 {q(.5)}K  p75 {q(.75)}K  p90 {q(.9)}K  p95 {q(.95)}K  max {peaks[-1]//1000}K")
    for t in (100_000, 150_000, 250_000, 400_000):
        k = sum(1 for p in peaks if p >= t)
        print(f"  sessions reaching {t//1000}K: {k} ({100*k/n:.0f}%)")

    turns_by, cost_by = defaultdict(int), defaultdict(float)
    for s in sessions:
        for ctx, cost in s:
            lo = max(b for b in BUCKETS[:-1] if b <= ctx)
            turns_by[lo] += 1
            cost_by[lo] += cost
    T = sum(turns_by.values())
    print("Turns and cost by context size at the turn:")
    print("  context      turns   share of turns   share of cost")
    for lo, hi in zip(BUCKETS, BUCKETS[1:]):
        name = f"{lo//1000}-{hi//1000}K" if hi < 10**9 else f"{lo//1000}K+"
        print(f"  {name:<11}{turns_by[lo]:>7}   {100*turns_by[lo]/T:>6.1f}%         {100*cost_by[lo]/total:>6.1f}%")

    long = [[x for x, _ in s] for s in sessions if len(s) >= 30]
    if long:
        reach = [r for r in (next((i + 1 for i, x in enumerate(c) if x >= 150_000), None) for c in long) if r]
        print(f"Sessions with 30+ turns: {len(long)}")
        print(f"  median context at turn 1: {med([c[0] for c in long])//1000}K; turn 10: "
              f"{med([c[9] for c in long])//1000}K; turn 30: {med([c[29] for c in long])//1000}K")
        print(f"  median turns until 150K: {med(reach)} ({len(reach)} of {len(long)} got there); "
              f"median turns per session: {med([len(c) for c in long])}")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--split", action="append", default=[], metavar="SUBSTRING")
    a = ap.parse_args()
    cut = time.time() - a.days * 86400
    groups = defaultdict(list)
    for f in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        if os.path.getmtime(f) < cut:
            continue
        turns, matched = read_session(f, a.split)
        if turns:
            groups[matched].append(turns)
    print(f"Last {a.days} days\n")
    report("All sessions", groups[True] + groups[False])
    if a.split:
        report("First message matches --split", groups[True])
        report("First message does not match", groups[False])


if __name__ == "__main__":
    main()
