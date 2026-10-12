#!/usr/bin/env python3
"""Scan, checksum and (optionally) zip what is about to leave the machine.

    python package.py FILE [FILE ...]          # single-file or few-file handoffs
    python package.py DIR --zip [--sums]       # zipped-folder handoffs

* Scans every file for what should not leave the machine. Blocking (exit 1):
  symlinks and likely secrets (key files, AWS/GitHub/Slack tokens, private keys,
  ``api_key = ...``). Warnings: home-directory paths in text and in Office files'
  XML, empty files, very large files, bare ``.html`` (mail gateways quarantine it;
  zip it). OS/editor junk (``.DS_Store``, ``__pycache__``, Excel ``~$`` lock files,
  ...) inside a folder is left out and reported.
* Prints each file's SHA-256 and size for the local record (``note.md``), so the
  user can later tell which version a recipient has without shipping a checksum
  file they would have to sort through.
* ``--zip``: writes ``<DIR>.zip`` beside the folder, with the folder as its single
  top-level directory. ``--sums`` also writes ``SHA256SUMS.txt`` inside it
  (``shasum -a 256 -c`` compatible), for recipients who verify drops.
* Reports which channels the result fits.

Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

SUMS = "SHA256SUMS.txt"
JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "__pycache__", ".ipynb_checkpoints", ".git"}
JUNK_PREFIXES = ("~$", "._")  # Office lock files, macOS resource forks
TEXT_SUFFIXES = {
    ".md", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml", ".toml", ".ini", ".xml",
    ".html", ".py", ".r", ".do", ".ado", ".sql", ".log", ".sh", ".tex", ".bib",
}
OFFICE_SUFFIXES = {".xlsx", ".xlsm", ".docx", ".pptx"}
SECRET_FILES = re.compile(r"^(\.env(\..*)?|id_(rsa|ed25519|ecdsa)(\.pub)?|.*\.pem|.*\.p12|credentials(\..*)?)$")
SECRET_TEXT = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("assigned secret", re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"]?[^\s'\"]{12,}")),
]
HOME_PATH = re.compile(r"(/Users/[^/\s\"'<>]+/|/home/[^/\s\"'<>]+/|[A-Za-z]:\\\\?Users\\\\?[^\\\s\"'<>]+)")
TEXT_SCAN_BYTES = 20_000_000
LARGE_MB = 500


def is_junk(rel: Path) -> bool:
    return any(p in JUNK_NAMES or p.startswith(JUNK_PREFIXES) for p in rel.parts)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def scan_text(label: str, text: str, errors: list[str], warnings: list[str]) -> None:
    for what, rx in SECRET_TEXT:
        if rx.search(text):
            errors.append(f"{label}: possible {what}")
    homes = sorted(set(HOME_PATH.findall(text)))
    if homes:
        warnings.append(f"{label}: home-directory path(s) {homes[:3]} (meaningless to the recipient)")


def scan_file(path: Path, label: str, errors: list[str], warnings: list[str], zipped: bool) -> None:
    if SECRET_FILES.match(path.name):
        errors.append(f"{label}: key/credential file name")
    size = path.stat().st_size
    if size == 0:
        warnings.append(f"{label}: empty file")
    if size > LARGE_MB * 1_000_000:
        warnings.append(f"{label}: {size / 1e6:,.0f} MB")
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"} and not zipped:
        warnings.append(f"{label}: bare .html is often quarantined by mail gateways; send it zipped")
    if suffix in TEXT_SUFFIXES and size <= TEXT_SCAN_BYTES:
        scan_text(label, path.read_text(errors="replace"), errors, warnings)
    elif suffix in OFFICE_SUFFIXES and size <= 10 * TEXT_SCAN_BYTES:
        try:
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if name.endswith(".xml") and z.getinfo(name).file_size <= TEXT_SCAN_BYTES:
                        text = z.read(name).decode(errors="replace")
                        scan_text(f"{label}[{name}]", text, errors, warnings)
        except zipfile.BadZipFile:
            warnings.append(f"{label}: not a valid Office file")


def collect(root: Path, zipped: bool) -> tuple[list[Path], list[str], list[str], list[str]]:
    files: list[Path] = []
    errors: list[str] = []
    warnings: list[str] = []
    skipped: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if is_junk(rel):
            if path.is_file() or path.name in JUNK_NAMES:
                skipped.append(str(rel))
            continue
        if path.is_symlink():
            errors.append(f"{rel}: symlink (a zip would carry the target or break); copy the file in")
            continue
        if not path.is_file() or rel.as_posix() == SUMS:
            continue
        files.append(path)
        scan_file(path, str(rel), errors, warnings, zipped)
    return files, errors, warnings, sorted(set(skipped))


def write_zip(root: Path, files: list[Path], sums: bool) -> Path:
    out = root.parent / f"{root.name}.zip"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            z.write(p, arcname=f"{root.name}/{p.relative_to(root).as_posix()}")
        if sums:
            lines = [f"{sha256(p)}  {p.relative_to(root).as_posix()}" for p in files]
            z.writestr(f"{root.name}/{SUMS}", "\n".join(lines) + "\n")
    return out


def channel_fit(mb: float, gmail_mb: float) -> str:
    if mb <= gmail_mb:
        return f"fits a Gmail attachment (<= {gmail_mb:g} MB) or a Slack upload; attach by hand"
    if mb <= 1000:
        return "too big for Gmail: Slack upload, or a Box/Drive link in the note"
    return "Box/Drive link in the note (too big for Gmail and Slack)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", type=Path, nargs="+", help="files to send, or one folder to zip")
    ap.add_argument("--zip", action="store_true", help="zip the folder into <DIR>.zip beside it")
    ap.add_argument("--sums", action="store_true", help="put SHA256SUMS.txt inside the zip")
    ap.add_argument("--gmail-mb", type=float, default=20.0,
                    help="largest total to call Gmail-attachable; Gmail's 25 MB cap counts the encoded "
                    "message, so leave headroom (default: %(default)s)")
    args = ap.parse_args()
    paths = [p.resolve() for p in args.paths]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"not found: {', '.join(map(str, missing))}", file=sys.stderr)
        return 2
    folder = len(paths) == 1 and paths[0].is_dir()
    if (args.zip or args.sums) and not folder:
        print("--zip/--sums take exactly one folder", file=sys.stderr)
        return 2
    if any(p.is_dir() for p in paths) and not folder:
        print("pass either files or a single folder", file=sys.stderr)
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    skipped: list[str] = []
    if folder:
        root = paths[0]
        files, errors, warnings, skipped = collect(root, zipped=args.zip)
        label = {p: p.relative_to(root).as_posix() for p in files}
    else:
        files = paths
        for p in files:
            if p.is_symlink():
                errors.append(f"{p.name}: symlink; send the file itself")
            scan_file(p, p.name, errors, warnings, zipped=p.suffix.lower() == ".zip")
        label = {p: p.name for p in files}
    if not files:
        print("no files to send", file=sys.stderr)
        return 2

    total = sum(p.stat().st_size for p in files)
    print(f"{len(files)} file(s), {total / 1e6:,.2f} MB")
    for p in files:
        print(f"  {label[p]:<50} {p.stat().st_size / 1e6:>9,.3f} MB  sha256 {sha256(p)}")
    if skipped:
        print(f"left out (junk): {', '.join(skipped)}")
    for w in warnings:
        print(f"WARNING  {w}")
    for e in errors:
        print(f"BLOCKING {e}")
    if errors:
        print("stopped: resolve the blocking findings first", file=sys.stderr)
        return 1

    if folder and args.zip:
        z = write_zip(paths[0], files, args.sums)
        mb = z.stat().st_size / 1e6
        print(f"wrote {z} ({mb:,.2f} MB, sha256 {sha256(z)}): {channel_fit(mb, args.gmail_mb)}")
    else:
        print(f"total {total / 1e6:,.2f} MB: {channel_fit(total / 1e6, args.gmail_mb)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
