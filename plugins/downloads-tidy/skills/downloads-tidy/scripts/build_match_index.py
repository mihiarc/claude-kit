#!/usr/bin/env python3
"""
Index the user's real filing homes (Documents, Github repos, etc.) and classify
every item in Downloads against that index by filename + byte size.

Why this exists: doing this matching by hand (or re-deriving it fresh each time)
is the single most repetitive, mechanical part of a downloads-tidy pass. Writing
it ad hoc is also easy to get subtly wrong -- e.g. comparing zip entry paths
(which include the archive's internal folder prefix) against bare folder-relative
paths, which silently produces false "missing" results. This script gets that
right once so every run can just trust the output.

Usage:
    python3 build_match_index.py \
        --downloads ~/Downloads \
        --homes ~/Documents ~/Github ~/Data \
        [--exclude ~/Documents/<restricted-area>] \
        [--since-days 14] \
        [--prune node_modules,.venv,venv,__pycache__,.git,dist,build] \
        > match_result.json

Output (JSON to stdout, progress/summary to stderr):
    {
      "exact_dup":     [{"rel": <path under Downloads>, "size": <bytes>,
                          "match": <full path found in a home>, "match_home": <which --homes root>}],
      "size_mismatch": [{"rel": ..., "size": ..., "candidates": [[path, size], ...]}],
      "no_match":      [{"rel": ..., "size": ...,
                          "same_size": [path, ...]}]   # only when non-empty
    }

A Downloads item is EXACT_DUP if some file somewhere under a --homes root has the
same basename (or the same basename after stripping a trailing " (1)", " (2)"
macOS-style re-download suffix) AND the same byte size -- strong evidence it's
already filed and the Downloads copy is redundant.

SIZE_MISMATCH means the name matched but no candidate had the same size --
this is exactly the case that needs a human (or a diff/unzip -l/git log check)
before deciding anything, since it usually means either a newer/older version
or two genuinely different files that happen to share a name.

NO_MATCH means nothing with that name was found anywhere in the homes -- this
item has probably never been filed, or was filed under another name. For items
of at least SAME_SIZE_MIN bytes, "same_size" lists up to SAME_SIZE_MAX home
files with exactly the same byte size: candidates for a renamed copy, to be
confirmed byte for byte before anything is treated as a duplicate. Smaller
files are skipped because unrelated small files share sizes too often.

Package directories (.gdb, .zarr, .app, .SAFE and the others in PACKAGE_EXTS)
are one item each, on both sides: matched by directory name and total byte
size, never descended into. Their internal files have generic names
(a00000001.gdbtable, .zarray, 0.0.0) that collide across unrelated datasets,
so per-file matching inside them reports false duplicates.

--exclude takes full paths that are skipped entirely while indexing, for areas
the user's rules say must not be opened unless they name them.

Notes on quality:
- Extremely generic basenames (image.png, index.html, manifest.json, and the
  like) produce noisy, meaningless "matches" because they recur constantly in
  build output / node_modules / test fixtures across many repos. This script
  does NOT try to filter these out automatically -- treat a size_mismatch or
  exact_dup hit on a generic filename with suspicion, and prefer NO_MATCH
  handling (i.e. leave it alone / ask) over trusting a coincidental hit.
- This only compares byte size, not content hashes. Two different files that
  happen to share both a name and a size would show as EXACT_DUP incorrectly.
  This is rare enough in practice not to hash everything (hashing is slow over
  large homes), but for anything large or consequential, verify with an actual
  diff/md5 before trashing.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

DEFAULT_PRUNE = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".cache", ".pytest_cache", ".terraform", ".DS_Store",
    ".ipynb_checkpoints", ".mypy_cache", ".ruff_cache", "egg-info",
    "site-packages", ".playwright-mcp",
}

SAME_SIZE_MIN = 64 * 1024
SAME_SIZE_MAX = 5

PACKAGE_EXTS = {
    ".app", ".bundle", ".framework", ".plugin", ".pkg", ".mpkg", ".xcarchive",
    ".rtfd", ".key", ".pages", ".numbers", ".photoslibrary",
    ".gdb", ".zarr", ".safe",
}


def is_package(name):
    return os.path.splitext(name)[1].lower() in PACKAGE_EXTS


def tree_size(path):
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def normalize(name):
    """Strip a trailing macOS re-download suffix like ' (1)' before the extension."""
    base, ext = os.path.splitext(name)
    base = re.sub(r"\s*\(\d+\)$", "", base)
    return base + ext


def walk_index(root, prune, exclude):
    idx = defaultdict(list)  # basename -> [(full_path, size), ...]
    for dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            if d in prune or d.startswith(".git") or full in exclude:
                continue
            if is_package(d):
                idx[d].append((full, tree_size(full)))
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            if fn == ".DS_Store" or fn.startswith("~$") or fn.startswith("._"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                sz = os.path.getsize(full)
            except OSError:
                continue
            idx[fn].append((full, sz))
    return idx


def lookup(name, home_indexes):
    norm = normalize(name)
    hits = []
    for home_label, idx in home_indexes:
        for key in {name, norm}:
            for path, sz in idx.get(key, []):
                hits.append((home_label, path, sz))
    seen, out = set(), []
    for h in hits:
        if h[1] not in seen:
            seen.add(h[1])
            out.append(h)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--downloads", default=os.path.expanduser("~/Downloads"))
    ap.add_argument("--homes", nargs="+", required=True,
                     help="Root directories to index as 'real homes' (e.g. ~/Documents ~/Github)")
    ap.add_argument("--since-days", type=int, default=None,
                     help="Only classify Downloads items modified in the last N days "
                          "(for a quick/incremental pass). Omit for a full/deep pass.")
    ap.add_argument("--prune", default="",
                     help="Comma-separated extra directory names to skip while indexing homes")
    ap.add_argument("--exclude", nargs="*", default=[],
                     help="Full directory paths to skip entirely while indexing homes")
    args = ap.parse_args()

    prune = set(DEFAULT_PRUNE)
    if args.prune:
        prune |= {p.strip() for p in args.prune.split(",") if p.strip()}
    exclude = {os.path.normpath(os.path.expanduser(p)) for p in args.exclude}

    home_indexes = []
    for home in args.homes:
        home = os.path.expanduser(home)
        t0 = time.time()
        print(f"Indexing {home} ...", file=sys.stderr)
        idx = walk_index(home, prune, exclude)
        n = sum(len(v) for v in idx.values())
        print(f"  {n} files in {time.time()-t0:.1f}s", file=sys.stderr)
        home_indexes.append((home, idx))

    by_size = defaultdict(list)  # size -> [full_path, ...], large items only
    for _, idx in home_indexes:
        for entries in idx.values():
            for path, sz in entries:
                if sz >= SAME_SIZE_MIN:
                    by_size[sz].append(path)

    downloads = os.path.expanduser(args.downloads)
    cutoff = None
    if args.since_days is not None:
        cutoff = time.time() - args.since_days * 86400

    results = {"exact_dup": [], "size_mismatch": [], "no_match": []}

    def classify(full, rel):
        try:
            st = os.stat(full)
        except OSError:
            return
        if cutoff is not None and st.st_mtime < cutoff:
            return
        size = tree_size(full) if os.path.isdir(full) else st.st_size
        name = os.path.basename(full)
        hits = lookup(name, home_indexes)
        if not hits:
            entry = {"rel": rel, "size": size}
            if size >= SAME_SIZE_MIN and by_size.get(size):
                entry["same_size"] = by_size[size][:SAME_SIZE_MAX]
            results["no_match"].append(entry)
            return
        exact = [h for h in hits if h[2] == size]
        if exact:
            results["exact_dup"].append({
                "rel": rel, "size": size,
                "match": exact[0][1], "match_home": exact[0][0],
            })
        else:
            results["size_mismatch"].append({
                "rel": rel, "size": size,
                "candidates": [[h[1], h[2]] for h in hits],
            })

    # Walk Downloads recursively so items inside any remaining subfolders get
    # classified too, not just top-level entries. Packages are classified whole.
    for dirpath, dirnames, filenames in os.walk(downloads):
        keep = []
        for d in dirnames:
            if d == ".Trash":
                continue
            if is_package(d):
                full = os.path.join(dirpath, d)
                classify(full, os.path.relpath(full, downloads))
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            if fn == ".DS_Store" or fn.startswith("._"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, downloads)
            classify(full, rel)

    print(json.dumps(results, indent=1))
    print(
        f"\nSUMMARY: exact_dup={len(results['exact_dup'])} "
        f"size_mismatch={len(results['size_mismatch'])} "
        f"no_match={len(results['no_match'])}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
