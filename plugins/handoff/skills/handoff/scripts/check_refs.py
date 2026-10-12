#!/usr/bin/env python3
"""Verify the file references in a draft handoff prompt.

Usage:
    python3 check_refs.py <draft-file> [repo-root] [--json]

A handoff prompt is only as trustworthy as its paths: one path that doesn't
resolve sends the next session somewhere that doesn't exist and costs it faith
in everything else you wrote. This finds those before the prompt ships.

Each cited path is reported as one of:
  OK       resolved (as given, or relative to repo-root). Globs resolve if they
           match at least one file.
  creates  does not resolve, but the prompt says on or near that line that the
           task will create it ("to create", "does not exist yet", "new file").
           Expected and fine -- this is how a deliverable is distinguished from
           a broken reference.
  PARTIAL  the filename exists under repo-root but not at the path as written
           -- usually a missing prefix. Fix the prefix.
  MISSING  nothing by that name under repo-root, and not labelled as an output.
           A typo, a file you imagined, or a deliverable you forgot to label.

Exit status is 1 if anything is MISSING or PARTIAL, else 0.

Handled: paths in backticks, paths containing spaces, brace shorthand
(src/pkg/{a.py, b.py} and out/panel.{csv,md}), globs, and ~/ expansion. URLs and
placeholder paths (out/<tile>.tif) are skipped rather than reported.

Not checked: section numbers, line numbers, and paths inside archives (a .docx's
word/media/*). Verify those by grepping the artifact itself.
"""

import glob
import json
import os
import re
import sys

# Paths routinely appear inside backticks, so a backtick must not block a match --
# excluding it silently clips "`~/a/b.md`" down to "/a/b.md".
PATH_RE = re.compile(
    r"(?<![\w])((?:~/|\.{0,2}/)?(?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z0-9]{1,8})"
)
# "1.8/5.9/19.8" and "§3.3/3.4" are version and section numbers, not paths. So is
# "800s/5.8%" -- a real extension has a letter in it, so require one.
NUMERIC_ONLY = re.compile(r"^[\d./]+$")
NO_ALPHA_EXT = re.compile(r"\.[^.]*$")
# Remote URIs are real references but not local files -- checking them here would
# report every bucket as a hallucination.
URI_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.I)
# Whole URLs are stripped before extraction; otherwise a backticked partial URL gets
# clipped into a path-looking fragment that can never resolve.
URL_ANYWHERE_RE = re.compile(r"[a-z][a-z0-9+.\-]*://[^\s`\"'<>)\]]+", re.I)
# A path the task is going to CREATE is not a broken reference -- but it must be
# labelled as such in the prompt, so it doesn't read as an existing asset.
CREATES_RE = re.compile(
    r"\b(?:creates?|will create|to create|to be created|created by|"
    r"exists?\s+yet|new files?|greenfield|does\s*not\s+yet\s+exist|"
    r"do\s*not\s+yet\s+exist)\b",
    re.I,
)
# The skill asks you to STATE absences ("the repo no longer has output/reports/").
# Without this, saying so truthfully would fail the check and you'd be pushed to
# reword around the path -- which is exactly the wrong incentive.
ABSENT_RE = re.compile(
    r"\b(?:no longer (?:has|exists?|present)|was removed|has been removed|"
    r"is absent|does\s*n[o']?t exist|do\s*n[o']?t exist|is gone|"
    r"never existed|not present|deleted)\b",
    re.I,
)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache"}


def expand_braces(text):
    """Expand brace shorthand so the parts aren't flagged as missing.

    Handles both forms that show up in these prompts:
      src/pkg/{a/b.py, c.py}          -> prefix ends in a separator
      outputs/panel_west.{csv,md}     -> prefix ends in a filename stem
    """

    def _sub(m):
        prefix, inner, suffix = m.group(1), m.group(2), m.group(3) or ""
        return " ".join(
            prefix + " ".join(part.split()) + suffix
            for part in inner.split(",")
            if part.strip()
        )

    # The trailing group matters: "fia_{crosscheck,intensity}.csv" must keep ".csv".
    return re.sub(r"([\w.\-/]*/[\w.\-]*)\{([^{}]+)\}([\w.\-]*)", _sub, text, flags=re.S)


def strip_rel_prefix(p):
    """Drop a leading './' or '/' without eating a dotfile's dot.

    str.lstrip("./") is character-set based, so it turned ".github/workflows/ci.yml"
    into "github/workflows/ci.yml" and every dotted path failed to resolve.
    """
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def looks_like_path(s):
    """Is this backtick/quote-delimited span a file path rather than a command?"""
    s = s.strip()
    if "/" not in s or "\n" in s:
        return False
    # A command like "uv run pytest tests/" starts with a bare word, not a path root.
    if " " in s and not re.match(r"^[~./]", s):
        return False
    # Either ends in an extension, or is a directory reference.
    return bool(re.search(r"\.[A-Za-z0-9]{1,8}$", s) or s.endswith("/"))


# An absolute/home-anchored path, allowing single spaces inside segments. Greedy,
# so it may swallow trailing prose -- resolve_spaced() trims it back by existence.
SPACED_RE = re.compile(
    r"(?:~|\.{0,2})/(?:[\w.\-]+(?: [\w.\-]+)*/)+[\w.\-]+(?: [\w.\-]+)*\.[A-Za-z0-9]{1,8}"
)


def resolve_spaced(raw):
    """Trim a greedy spaced match back to the longest prefix that exists.

    "~/Documents/MN Bids/file.docx and then some" -> "~/Documents/MN Bids/file.docx"
    Returns None if no prefix resolves, so the caller can fall back.
    """
    words = raw.split(" ")
    ends_in_ext = [
        " ".join(words[:n])
        for n in range(1, len(words) + 1)
        if re.search(r"\.[A-Za-z0-9]{1,8}$", " ".join(words[:n]))
    ]
    for cand in reversed(ends_in_ext):  # longest first
        if os.path.exists(os.path.expanduser(cand)):
            return cand
    # Nothing resolves: report the SHORTEST plausible path rather than the greedy
    # match, so a bad reference is named precisely instead of trailing prose.
    return ends_in_ext[0] if ends_in_ext else None


def candidate_paths(text):
    """Collect cited paths, including ones containing spaces.

    Bare-token regexes stop at the first space, which silently drops paths like
    `~/Documents/MN Bids/manuscript.docx` -- the out-of-repo references that are
    the most fabrication-prone part of a handoff. Delimited spans are read whole
    so those get checked too.
    """
    cands = set()
    for m in re.finditer(r"`([^`\n]+)`|\"([^\"\n]+)\"", text):
        span = (m.group(1) or m.group(2)).strip().rstrip(".,;:)")
        if not looks_like_path(span):
            continue
        # A delimited span can itself carry brace shorthand; expand it rather than
        # taking "outputs/x_{a,b}.csv" verbatim and calling it missing.
        if "{" in span:
            cands.update(t for t in expand_braces(span).split() if looks_like_path(t))
        else:
            cands.add(span)
    # Match spaced paths against the ORIGINAL text: brace expansion joins parts with
    # spaces, which would otherwise get glued into one bogus multi-path candidate.
    for raw in SPACED_RE.findall(text):
        if " " not in raw:
            continue
        resolved = resolve_spaced(raw)
        if resolved and not NUMERIC_ONLY.match(resolved):
            cands.add(resolved)
    expanded = expand_braces(text)
    for p in PATH_RE.findall(expanded):
        if not NUMERIC_ONLY.match(p):
            cands.add(p)
    # Drop bare fragments that are only the tail of a longer path we already have --
    # otherwise a spaced path gets reported twice, once as a clipped fragment.
    # Drop remote URIs and template paths ("out/lcms_<tile>_<year>.tif"), which are
    # placeholders by construction and can never resolve.
    def plausible(c):
        if URI_RE.match(c) or "<" in c or ">" in c:
            return False
        if any(ch in c for ch in "*?["):  # glob
            return True
        if c.endswith("/"):  # directory reference, no extension to inspect
            return True
        # A real extension contains a letter; "800s/5.8%" and "1.2/3.4" do not.
        ext = NO_ALPHA_EXT.search(c)
        return bool(ext and re.search(r"[A-Za-z]", ext.group(0)))

    cands = {c for c in cands if plausible(c)}
    return sorted(c for c in cands if not any(c != o and o.endswith(c) for o in cands))


def index_basenames(repo_root):
    names = set()
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        names.update(filenames)
    return names


def labelled_as(path, text, pattern, window=2):
    """Does the prompt label this path with `pattern` near where it's mentioned?

    The label often lands on a wrapped continuation line rather than the line
    holding the path ("- `a.py` and `b.md`\\n  **all new files; none exist yet**"),
    so look at a small window around each mention.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if path not in line:
            continue
        ctx = "\n".join(lines[max(0, i - window) : i + window + 1])
        if pattern.search(ctx):
            return True
    return False


def classify(paths, repo_root, basenames, text=""):
    rows = []
    for p in paths:
        cand = os.path.expanduser(p)
        tries = [cand, os.path.join(repo_root, strip_rel_prefix(cand))]
        # A glob ("analysis/*.py") is a legitimate way to reference a set of files;
        # resolve it rather than reporting the literal pattern as missing.
        if any(ch in p for ch in "*?["):
            hits = sum(len(glob.glob(t)) for t in tries)
            rows.append(
                (p, "OK", f"glob matches {hits} file(s)")
                if hits
                else (p, "MISSING", "glob matches nothing under repo root")
            )
            continue
        if any(os.path.exists(t) for t in tries):
            rows.append((p, "OK", ""))
        elif labelled_as(p, text, CREATES_RE):
            rows.append((p, "CREATES", "labelled as an output this task creates"))
        elif labelled_as(p, text, ABSENT_RE):
            rows.append((p, "ABSENT", "absence is asserted deliberately -- confirmed gone"))
        elif os.path.basename(p) in basenames:
            rows.append((p, "PARTIAL", "filename exists under repo root; prefix looks wrong"))
        else:
            rows.append((p, "MISSING", "no file by this name under repo root"))
    return rows


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    draft = args[0]
    repo_root = os.path.abspath(args[1]) if len(args) > 1 else os.getcwd()

    if not os.path.exists(draft):
        print(f"error: draft file not found: {draft}", file=sys.stderr)
        return 2

    text = open(draft, encoding="utf-8", errors="replace").read()
    scannable = URL_ANYWHERE_RE.sub(" ", text)
    # Search the creates-label against the EXPANDED text: candidates come out of brace
    # expansion, so matching them against raw lines (which still contain "{a,b}") meant
    # a brace-shorthand path could never be recognised as a declared output.
    labelled = expand_braces(scannable)
    rows = classify(
        candidate_paths(scannable), repo_root, index_basenames(repo_root), labelled
    )

    missing = [r for r in rows if r[1] == "MISSING"]
    partial = [r for r in rows if r[1] == "PARTIAL"]
    creates = [r for r in rows if r[1] == "CREATES"]
    absent = [r for r in rows if r[1] == "ABSENT"]

    if "--json" in argv:
        print(json.dumps(
            {
                "repo_root": repo_root,
                "cited": len(rows),
                "ok": sum(1 for r in rows if r[1] == "OK"),
                "partial": [r[0] for r in partial],
                "missing": [r[0] for r in missing],
                "creates": [r[0] for r in creates],
                "absent": [r[0] for r in absent],
                "results": [{"path": p, "status": s, "note": n} for p, s, n in rows],
            },
            indent=2,
        ))
        return 1 if missing else 0

    if not rows:
        print("No file paths cited. If the prompt names assets, it should cite where they are.")
        return 0

    width = max(len(r[0]) for r in rows)
    for p, status, note in rows:
        mark = {
            "OK": "  ok    ",
            "PARTIAL": " PARTIAL",
            "MISSING": " MISSING",
            "CREATES": " creates",
            "ABSENT": " absent ",
        }[status]
        print(f"{mark}  {p:<{width}}  {note}")

    print(
        f"\n{sum(1 for r in rows if r[1] == 'OK')}/{len(rows)} resolved"
        f" | {len(partial)} partial | {len(missing)} missing"
        f" | {len(creates)} to-be-created | {len(absent)} asserted-absent"
        f"   (repo root: {repo_root})"
    )
    if partial:
        print("Fix the prefix on PARTIAL paths -- the file is real, the path as written isn't.")
    if missing:
        print("Resolve every MISSING path before shipping: correct it, drop it, or say")
        print("explicitly in the prompt that the task will create it.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
