#!/usr/bin/env python3
"""Measure speaking time per section of a speaker-notes markdown file.

Counts spoken words per `## ` section and converts to time at a given
words-per-minute rate (conversational presenting pace is ~120-135 wpm).

Excluded from counts (not spoken): headings, HTML tag lines (e.g. advance
markers), stage directions written as [*...*] or (*...*) on their own line,
and label prefixes like **Say:** / **Expand:** / **Frame check:** (the label
itself, not the content after it; but "Frame check", "My additions",
"Danger zone" lines are excluded entirely since they're notes-to-self).

Usage:
    measure_timing.py notes.md [--wpm 130] [--match REGEX]

--match filters which section headings are counted (default: sections
starting with "Slide"; pass --match . to count everything).
"""
import argparse
import re
import sys

NOTE_LABELS = re.compile(
    r"^\*\*(Frame check|My additions|Danger zone|Handback note|Note)\b", re.I
)
SPOKEN_LABEL = re.compile(r"^\*\*(Say[^*]*|Expand[^*]*|Optional[^*]*|Handback)\s*:\*\*\s*")
STAGE_DIRECTION = re.compile(r"^[\[(]\s*\*.*\*\s*[\])]$")


def spoken_words(section_lines):
    # Work on paragraphs (blank-line separated) so a note-to-self that wraps
    # across lines is still recognized as one italic-only block.
    paragraphs = re.split(r"\n\s*\n", "\n".join(section_lines))
    words = 0
    for para in paragraphs:
        p = " ".join(l.strip() for l in para.splitlines()).strip()
        if not p or p.startswith("#") or p.startswith("<") or p == "---":
            continue
        if STAGE_DIRECTION.match(p) or NOTE_LABELS.match(p):
            continue
        # italic-only paragraphs are notes-to-self, not speech
        if re.fullmatch(r"\*[^*]+\*", p):
            continue
        p = SPOKEN_LABEL.sub("", p)
        # drop inline bracketed stage directions and emphasis markers
        p = re.sub(r"[\[(]\s*\*[^*]*\*\s*[\])]", " ", p)
        p = p.replace("**", "").replace("*", "")
        words += len(p.split())
    return words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--wpm", type=float, default=130.0)
    ap.add_argument("--match", default=r"^Slide", help="regex on section titles (default: ^Slide)")
    args = ap.parse_args()

    text = open(args.input, encoding="utf-8").read()
    sections = re.split(r"^## ", text, flags=re.M)
    matcher = re.compile(args.match)

    total = 0
    rows = []
    for sec in sections[1:]:
        title = sec.split("\n", 1)[0].strip()
        if not matcher.search(title):
            continue
        w = spoken_words(sec.split("\n")[1:])
        total += w
        rows.append((title, w))

    if not rows:
        print(f"No sections matched --match {args.match!r}. Titles found:", file=sys.stderr)
        for sec in sections[1:]:
            print("  ##", sec.split("\n", 1)[0].strip(), file=sys.stderr)
        sys.exit(1)

    width = max(len(t) for t, _ in rows) + 2
    for title, w in rows:
        secs = w / args.wpm * 60
        print(f"{title:<{width}} {w:5d} words  ~{secs:4.0f}s")
    mins = total / args.wpm
    print(f"\nTOTAL: {total} words  ~{mins:.1f} min at {args.wpm:.0f} wpm"
          f"  |  ~{total / 120:.1f} min at 120 wpm")
    print("Add ~5s per slide for transitions, plus any instructed pauses.")


if __name__ == "__main__":
    main()
