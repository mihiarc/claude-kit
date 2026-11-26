#!/usr/bin/env python3
"""Build delivery and distribution PDFs from a speaker-notes markdown file.

One markdown source -> two PDFs:
  <stem>-delivery.pdf   large-print lectern copy: 17pt, phrase-per-line honored,
                        top-two-thirds page, each ## section on a fresh page,
                        big page numbers, advance markers kept with their
                        preceding paragraph (never orphaned on an empty page).
  <stem>.pdf            compact distribution copy for sharing; advance markers
                        (<div class="advance">) stripped.

Requires: pandoc, plus a renderer (Google Chrome / Chromium / Edge headless, or
weasyprint). Chrome is found in its usual place on macOS, Linux and Windows, on PATH,
or at `$CHROME`. Reports clearly if something is missing.

Usage:
    build_pdfs.py notes.md --outdir . --header "Project · Speaker Script"
    build_pdfs.py outline.md --distribution-only --title "Condensed Outline"
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"

CHROME_COMMANDS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                   "chrome", "msedge", "microsoft-edge"]


def chrome_candidates(platform=sys.platform, env=os.environ):
    """Where Chrome or Chromium usually lives on this OS. `$CHROME` comes first; PATH commands
    are added by find_chrome."""
    out = [env["CHROME"]] if env.get("CHROME") else []
    if platform == "darwin":
        for root in ("/Applications", str(Path.home() / "Applications")):
            out += [f"{root}/Google Chrome.app/Contents/MacOS/Google Chrome",
                    f"{root}/Chromium.app/Contents/MacOS/Chromium"]
    elif platform.startswith("win"):
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if env.get(var):
                out += [str(Path(env[var]) / "Google/Chrome/Application/chrome.exe"),
                        str(Path(env[var]) / "Microsoft/Edge/Application/msedge.exe")]
    return out


def find_chrome(platform=sys.platform, env=os.environ, which=shutil.which, exists=os.path.exists):
    for c in chrome_candidates(platform, env):
        if exists(c):
            return c
    for name in CHROME_COMMANDS:
        if which(name):
            return which(name)
    return None


def install_hint(tool, platform=sys.platform):
    if platform == "darwin":
        return f"brew install {tool}"
    if platform.startswith("win"):
        return f"winget install {'JohnMacFarlane.Pandoc' if tool == 'pandoc' else tool}"
    return f"your package manager, e.g. apt install {tool}"


def pandoc_html(md_path, css_path, title, out_html):
    subprocess.run(
        ["pandoc", str(md_path), "-f", "gfm", "-t", "html5", "--standalone",
         "--css", str(css_path), "--metadata", f"pagetitle={title}",
         "-o", str(out_html)],
        check=True,
    )


def bind_advance_markers(html_path):
    """Wrap each advance marker with its preceding paragraph so a page break
    never strands the marker alone on an empty page."""
    html = html_path.read_text(encoding="utf-8")
    html, n = re.subn(
        r'(<p>(?:(?!</p>).)*?</p>)\s*(<div class="advance">(?:(?!</div>).)*?</div>)',
        r'<div class="keep">\1\n\2</div>',
        html, flags=re.S,
    )
    html_path.write_text(html, encoding="utf-8")
    return n


def render_pdf(html_path, pdf_path):
    chrome = find_chrome()
    if chrome:
        subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={pdf_path}", str(html_path)],
            check=True, capture_output=True,
        )
        return
    if shutil.which("weasyprint"):
        # macOS: weasyprint may need DYLD paths that shells strip; try anyway.
        subprocess.run(["weasyprint", str(html_path), str(pdf_path)], check=True)
        return
    sys.exit("No PDF renderer found: install Google Chrome or Chromium (or set $CHROME to its "
             "binary), or weasyprint.")


def prepare_css(template_name, header, tmpdir):
    css = (ASSETS / template_name).read_text(encoding="utf-8")
    css = css.replace("__HEADER__", header.replace('"', r"\""))
    out = Path(tmpdir) / template_name
    out.write_text(css, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--header", default="Speaker Script",
                    help="running header text (project · doc name)")
    ap.add_argument("--title", default=None, help="PDF <title>; default from filename")
    ap.add_argument("--delivery-only", action="store_true")
    ap.add_argument("--distribution-only", action="store_true")
    args = ap.parse_args()

    if not shutil.which("pandoc"):
        sys.exit(f"pandoc not found — install it ({install_hint('pandoc')}).")

    md = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    title = args.title or md.stem.replace("-", " ").title()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        if not args.distribution_only:
            css = prepare_css("delivery.css", args.header + " — DELIVERY COPY", tmp)
            html = tmp / "delivery.html"
            pandoc_html(md, css, f"{title} — Delivery Copy", html)
            n = bind_advance_markers(html)
            pdf = outdir / f"{md.stem}-delivery.pdf"
            render_pdf(html, pdf)
            print(f"delivery:     {pdf}  ({n} advance markers bound)")

        if not args.delivery_only:
            stripped = tmp / md.name
            stripped.write_text(
                "\n".join(l for l in md.read_text(encoding="utf-8").splitlines()
                          if 'class="advance"' not in l),
                encoding="utf-8",
            )
            css = prepare_css("distribution.css", args.header, tmp)
            html = tmp / "dist.html"
            pandoc_html(stripped, css, title, html)
            pdf = outdir / f"{md.stem}.pdf"
            render_pdf(html, pdf)
            print(f"distribution: {pdf}  (advance markers stripped)")


if __name__ == "__main__":
    main()
