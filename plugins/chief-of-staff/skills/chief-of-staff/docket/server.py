#!/usr/bin/env python3
"""Serve the chief-of-staff docket on 127.0.0.1:8765 (or `$COS_DOCKET_PORT`) and take answers into an inbox file.

State lives in the `docket/` folder beside the questions file (`$COS_QUESTIONS`, or
`~/.claude/chief-of-staff/questions.md`), the same folder build.py writes.

GET /         -> docket/index.html (rebuilt by build.py)
GET /version  -> the page's build time, which the page polls to reload itself after a rebuild
POST /answer  -> appends {"time","num","choice","text","item","action"} to docket/inbox.jsonl
                 (requires the page's token; localhost only). A `move` also carries "to":
                 you | others | someday; `done` closes a to-do item.

Answers arriving here are queued, not acted on: the chief-of-staff session reads the inbox,
shows each answer in chat, and acts only after the user confirms there.

POST /attach  -> opens a live background session in Terminal (`claude attach <id>`) or brings an
                 interactive session's Terminal window forward. macOS only: elsewhere it answers
                 501 with the command to run, and the page hides the button. Only sessions in
                 the current `claude agents` list are accepted.

Start: nohup python3 -I server.py >> <state>/server.log 2>&1 &
"""
import datetime as dt
import hmac
import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(os.environ.get("COS_QUESTIONS", "~/.claude/chief-of-staff/questions.md")).expanduser().parent / "docket"
PAGE = HERE / "index.html"
INBOX = HERE / "inbox.jsonl"
TOKEN_FILE = HERE / ".token"
HOST, PORT = "127.0.0.1", int(os.environ.get("COS_DOCKET_PORT", "8765"))
MAX_BODY = 8192
COLUMNS = ("you", "others", "someday")  # a `move` target; Done is reached by `done` or `drop`


def _tty(pid: str) -> str:
    return subprocess.run(["ps", "-o", "tty=", "-p", pid], capture_output=True, text=True).stdout.strip()


def attach_plan(a: dict, platform: str = sys.platform, tty_of=_tty) -> tuple[int, str]:
    """(200, AppleScript) that opens or raises the session's Terminal window, or (error code,
    message). Attach drives Terminal.app, so off macOS it answers 501 with the command to run."""
    background = a.get("kind") == "background" and re.fullmatch(r"[0-9a-f]{8}", a.get("id") or "")
    if platform != "darwin":
        if background:
            return 501, f"Attach opens Terminal on macOS only. Run: claude attach {a['id']}"
        return 501, "Attach opens Terminal on macOS only. Switch to that session's window yourself."
    if background:
        return 200, f'tell application "Terminal" to do script "claude attach {a["id"]}"\ntell application "Terminal" to activate'
    pid = str(a.get("pid") or "")
    if not pid.isdigit():
        return 404, "no process for that session"
    tty = tty_of(pid)
    if not re.fullmatch(r"ttys\d{3}", tty):
        return 404, "session has no Terminal window"
    return 200, ('tell application "Terminal"\n'
                 f'  repeat with w in windows\n    repeat with t in tabs of w\n'
                 f'      if tty of t is "/dev/{tty}" then\n        set selected of t to true\n        set index of w to 1\n        activate\n        return\n      end if\n'
                 '    end repeat\n  end repeat\nend tell')


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/version":
            return self._send(200, str(int(PAGE.stat().st_mtime)).encode())
        if self.path.split("?")[0] in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found")

    def do_POST(self) -> None:
        if self.path not in ("/answer", "/attach"):
            return self._send(404, b"not found")
        origin = self.headers.get("Origin", "")
        if origin and origin not in (f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"):
            return self._send(403, b"bad origin")
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._send(413, b"too large")
        try:
            data = json.loads(self.rfile.read(length))
        except ValueError:
            return self._send(400, b"bad json")
        token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""
        if not token or not hmac.compare_digest(str(data.get("token", "")), token):
            return self._send(403, b"bad token")
        if self.path == "/attach":
            return self._attach(data)
        num = str(data.get("num", ""))
        choice = data.get("choice")
        text = str(data.get("text") or "")[:4000]
        item = str(data.get("item") or "")[:300]
        if not (re.fullmatch(r"\d{1,4}", num) or (num in ("item", "project", "pr") and item)) or (choice is not None and not re.fullmatch(r"[a-z]", str(choice))):
            return self._send(400, b"bad answer")
        action = data.get("action")
        if action not in (None, "drop", "refresh", "merge", "review", "discuss", "move", "done"):
            return self._send(400, b"bad action")
        if action is None and not choice and not text.strip():
            return self._send(400, b"empty answer")
        to = data.get("to")
        if (action == "move") != (to is not None) or (to is not None and to not in COLUMNS):
            return self._send(400, b"bad column")
        if action == "done" and num != "item":
            return self._send(400, b"questions close by answering")
        entry = {"time": dt.datetime.now().isoformat(timespec="seconds"), "num": num,
                 "choice": choice, "text": text, "item": item, "action": action or "answer"}
        if to:
            entry["to"] = to
        with INBOX.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        os.chmod(INBOX, 0o600)
        self._send(200, b"ok")

    def _attach(self, data: dict) -> None:
        sid = str(data.get("sessionId", ""))
        if not re.fullmatch(r"[0-9a-f-]{36}", sid):
            return self._send(400, b"bad session id")
        try:
            raw = subprocess.run(["claude", "agents", "--json", "--all"], capture_output=True, text=True, timeout=20).stdout
            agents = json.loads(raw)
        except Exception:
            return self._send(500, b"could not list sessions")
        agents = agents if isinstance(agents, list) else agents.get("agents", [])
        a = next((x for x in agents if x.get("sessionId") == sid and (x.get("status") or "") not in ("done", "stopped")), None)
        if not a:
            return self._send(404, b"not a live session")
        code, out = attach_plan(a)
        if code != 200:
            return self._send(code, out.encode())
        subprocess.Popen(["osascript", "-e", out])
        self._send(200, b"ok")

    def log_message(self, fmt: str, *args) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
