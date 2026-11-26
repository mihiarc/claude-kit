#!/usr/bin/env python3
"""
Check whether a zip is fully redundant against an already-extracted folder,
byte for byte, so the zip can be trashed once the folder itself has a home.

Every file entry in the zip must match, byte for byte, some file with the same
basename under the folder. Matching is by basename, not path: zip entry paths
carry the archive's internal folder prefix ("drop/report.pdf") while paths
under the folder don't ("report.pdf"), so comparing full paths silently
reports every entry as missing. Entries are streamed from the zip and compared
in chunks; nothing is extracted to disk.

Finder metadata entries (__MACOSX/, ._*, .DS_Store) are skipped: they are
resource forks and folder settings, not content.

Usage:
    python3 -I check_zip_redundant.py <zipfile> <folder>

Prints REDUNDANT when every entry has a byte-identical match, otherwise lists
each entry without one. Exit status: 0 redundant, 1 not redundant, 2 bad input.
"""
import os
import sys
import zipfile
from collections import defaultdict

CHUNK = 1 << 20


def is_metadata(name):
    base = name.rsplit("/", 1)[-1]
    return name.startswith("__MACOSX/") or base.startswith("._") or base == ".DS_Store"


def same_bytes(zf, info, path):
    if os.path.getsize(path) != info.file_size:
        return False
    with zf.open(info) as a, open(path, "rb") as b:
        while True:
            x, y = a.read(CHUNK), b.read(CHUNK)
            if x != y:
                return False
            if not x:
                return True


def main():
    if len(sys.argv) != 3:
        print("usage: check_zip_redundant.py <zipfile> <folder>", file=sys.stderr)
        return 2
    zpath, folder = sys.argv[1], sys.argv[2]
    if not zipfile.is_zipfile(zpath):
        print(f"error: not a readable zip: {zpath}", file=sys.stderr)
        return 2
    if not os.path.isdir(folder):
        print(f"error: folder not found: {folder}", file=sys.stderr)
        return 2

    by_name = defaultdict(list)
    for dirpath, _, filenames in os.walk(folder):
        for fn in filenames:
            by_name[fn].append(os.path.join(dirpath, fn))

    checked, missing = 0, []
    with zipfile.ZipFile(zpath) as zf:
        for info in zf.infolist():
            if info.is_dir() or is_metadata(info.filename):
                continue
            checked += 1
            base = info.filename.rsplit("/", 1)[-1]
            if not any(same_bytes(zf, info, p) for p in by_name.get(base, [])):
                missing.append(info.filename)

    if missing:
        print(f"NOT REDUNDANT: {len(missing)} of {checked} entries in {zpath} "
              f"have no byte-identical file under {folder}:")
        for m in missing:
            print(f"  {m}")
        return 1
    print(f"REDUNDANT: all {checked} entries in {zpath} match files under {folder} byte for byte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
