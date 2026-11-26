"""Offline tests for extras/secrets/kit-secret.

They run the script against fake `security`, `gh`, `pbpaste` and `pbcopy` on PATH, which log
every argv they get, so a test can check where a value travelled and not only what came out.
Nothing here touches the real keychain or GitHub. Run with:

    python3 -m unittest discover extras/secrets/tests
"""
import json
import os
import pty
import random
import select
import shutil
import string
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "kit-secret"

FAKE_SECURITY = r'''#!/usr/bin/env python3
import getpass, json, os, shlex, sys
store = os.environ["FAKE_STORE"]
def log(argv):
    with open(os.environ["ARGV_LOG"], "a") as f: f.write(json.dumps(["security"] + argv) + "\n")
    with open(os.environ["ENV_LOG"], "a") as f: f.write(json.dumps(dict(os.environ)) + "\n")
def load():
    try: return json.load(open(store))
    except FileNotFoundError: return []
def find(s, a):
    for it in load():
        if it["s"] == s and (a is None or it["a"] == a): return it
def opts(argv):
    o, i = {}, 0
    while i < len(argv):
        k = argv[i]
        if k in ("-s", "-a", "-l") and i + 1 < len(argv): o[k] = argv[i + 1]; i += 2
        elif k == "-w":
            if i + 1 < len(argv): o["-w"] = argv[i + 1]; i += 2
            else: o["-w"] = None; i += 1
        else: o[k] = True; i += 1
    return o
def run(argv, interactive=False):
    cmd, o = argv[0], opts(argv[1:])
    if cmd == "find-generic-password":
        it = find(o.get("-s"), o.get("-a"))
        if not it:
            print("security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain.", file=sys.stderr)
            return 44
        # As Apple's keychain_find.c: a value with any unprintable byte prints as hex.
        b = it["v"].encode("utf-8", "surrogateescape")
        hexed = any(not (0x20 <= c <= 0x7e) for c in b)
        if "-w" in o:
            sys.stdout.write((b.hex() if hexed else it["v"]) + "\n")
            return 0
        print('keychain: "fake"\nattributes: ...')
        if "-g" in o:
            if hexed or b"\\" in b:  # -g also prints a value holding a backslash as hex
                esc = "".join(chr(c) if 0x20 <= c <= 0x7e else "\\%03o" % c for c in b)
                sys.stderr.write('password: 0x%s  "%s"\n' % (b.hex().upper(), esc))
            else:
                sys.stderr.write('password: "%s"\n' % it["v"])
        return 0
    if cmd == "add-generic-password":
        v = o.get("-w")
        if v is None:
            if not os.isatty(0): print("security: no tty", file=sys.stderr); return 1
            v = getpass.getpass("password data for new item: ")
            if getpass.getpass("retype password data for new item: ") != v:
                print("passwords don't match", file=sys.stderr); return 1
        items = [it for it in load() if not (it["s"] == o["-s"] and it["a"] == o["-a"])]
        if len(items) != len(load()) and "-U" not in o:
            print("already exists", file=sys.stderr); return 45
        items.append({"s": o["-s"], "a": o["-a"], "v": v})
        json.dump(items, open(store, "w"))
        return 0
    return 2
argv = sys.argv[1:]
log(argv)
if argv == ["-i"]:
    rc = 0
    for line in sys.stdin:
        rc = run(shlex.split(line), True) or rc
    sys.exit(rc)
sys.exit(run(argv))
'''

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["ARGV_LOG"], "a") as f: f.write(json.dumps(["gh"] + argv) + "\n")
with open(os.environ["ENV_LOG"], "a") as f: f.write(json.dumps(dict(os.environ)) + "\n")
data = sys.stdin.buffer.read()
if os.environ.get("FAKE_GH_FAIL"): print("HTTP 404", file=sys.stderr); sys.exit(1)
with open(os.environ["GH_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "stdin": data.decode("utf-8", "surrogateescape"), "hex": data.hex()}) + "\n")
print("✓ Set Actions secret %s" % argv[2], file=sys.stderr)
'''

FAKE_PBPASTE = '#!/bin/sh\necho "pbpaste" >> "$ARGV_LOG.clip"; cat "$CLIP" 2>/dev/null\n'
FAKE_PBCOPY = '#!/bin/sh\ncat > "$CLIP"\n'


def made_up_value(n=40):
    """A made-up test value, never a real secret."""
    return "kst-" + "".join(random.choice(string.ascii_letters + string.digits + "-_.~") for _ in range(n))


class KitSecretTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-secret-")).resolve()
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        for name, body in (("security", FAKE_SECURITY), ("gh", FAKE_GH),
                           ("pbpaste", FAKE_PBPASTE), ("pbcopy", FAKE_PBCOPY)):
            (bin_ / name).write_text(body)
            (bin_ / name).chmod(0o755)
        self.store = self.tmp / "store.json"
        self.argv_log = self.tmp / "argv.log"
        self.gh_log = self.tmp / "gh.log"
        self.clip = self.tmp / "clip"
        self.env_log = self.tmp / "env.log"
        self.tmpdir = self.tmp / "tmpdir"
        self.tmpdir.mkdir()
        # Real openssl, uname, cat and python3 from the system; the fakes shadow the rest.
        self.env = {
            "PATH": f"{bin_}:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
            "HOME": str(self.tmp), "USER": "tester", "LANG": "C.UTF-8",
            "KIT_SECRET_STORE": "keychain",
            "FAKE_STORE": str(self.store), "ARGV_LOG": str(self.argv_log),
            "GH_LOG": str(self.gh_log), "CLIP": str(self.clip), "ENV_LOG": str(self.env_log),
            "TMPDIR": str(self.tmpdir),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- helpers

    def run_kit(self, *args, stdin=subprocess.DEVNULL, env=None):
        return subprocess.run([str(SCRIPT), *args], stdin=stdin, capture_output=True, text=True,
                              env=dict(self.env, **(env or {})), timeout=30)

    def run_kit_pty(self, *args, answers=()):
        """Run with a pseudo-terminal as the controlling terminal; type each answer at each prompt."""
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(str(SCRIPT), [str(SCRIPT), *args], self.env)
        out, pending, deadline = b"", list(answers), time.time() + 30
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
                if pending and out.rstrip().endswith(b":"):
                    os.write(fd, pending.pop(0).encode() + b"\n")
                    out += b"<typed>"
            else:
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:
                    break
        else:
            os.kill(pid, 9)
        try:
            _, status = os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        os.close(fd)
        return os.waitstatus_to_exitcode(status), out.decode(errors="replace")

    def items(self):
        return json.loads(self.store.read_text()) if self.store.exists() else []

    def gh_calls(self):
        return [json.loads(l) for l in self.gh_log.read_text().splitlines()] if self.gh_log.exists() else []

    def argv_text(self):
        return self.argv_log.read_text() if self.argv_log.exists() else ""

    def seed(self, service, account, value):
        items = self.items() + [{"s": service, "a": account, "v": value}]
        self.store.write_text(json.dumps(items))

    def assert_nowhere(self, value, *outputs):
        """The value is in no argv or environment any process got, in no temp file, and in nothing
        the script printed. Only the fake keychain and the fake gh's record of its stdin hold it."""
        self.assertNotIn(value, self.argv_text())
        if self.env_log.exists():
            self.assertNotIn(value, self.env_log.read_text())
        self.assertEqual(list(self.tmpdir.iterdir()), [])
        # Every file the run left, but Python's own caches under the scratch HOME's Library, and the
        # two files that hold the value by design. Short random values would match by chance.
        if len(value) >= 12:
            for p in self.tmp.rglob("*"):
                if (p.is_file() and p not in (self.store, self.gh_log) and p.parent.name != "bin"
                        and "Library" not in p.relative_to(self.tmp).parts):
                    self.assertNotIn(value.encode(), p.read_bytes(), p)
        for o in outputs:
            self.assertNotIn(value, o)

    # ---------------------------------------------------------------- path 2: existing value

    def test_gh_pipes_existing_value(self):
        v = made_up_value()
        self.seed("kit-secrets-test", "tester", v)
        r = self.run_kit("gh", "kit-secrets-test", "KIT_SECRETS_TEST_EXISTING", "--repo", "o/r")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.gh_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["argv"], ["secret", "set", "KIT_SECRETS_TEST_EXISTING", "--repo", "o/r"])
        self.assertEqual(calls[0]["stdin"], v)  # exact, no trailing newline
        self.assert_nowhere(v, r.stdout, r.stderr)

    def test_gh_values_round_trip(self):
        """Property: any printable value (spaces, quotes, $, backslashes) arrives at gh unchanged."""
        alphabet = string.printable.replace("\n", "").replace("\r", "").replace("\x0b", "").replace("\x0c", "")
        for i in range(25):
            v = "K" + "".join(random.choice(alphabet) for _ in range(random.randint(14, 80))) + "Z"
            self.store.unlink(missing_ok=True)
            self.gh_log.unlink(missing_ok=True)
            self.seed("svc", "tester", v)
            r = self.run_kit("gh", "svc", "NAME")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.gh_calls()[0]["stdin"], v)
            self.assert_nowhere(v, r.stdout, r.stderr)

    def test_gh_missing_key_fails_and_writes_nothing(self):
        r = self.run_kit("gh", "kit-secrets-test-missing", "KIT_SECRETS_TEST_MISSING", "--repo", "o/r")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no secret 'kit-secrets-test-missing'", r.stderr)
        self.assertIn("Nothing was set", r.stderr)
        self.assertEqual(self.gh_calls(), [])
        self.assertNotIn('"gh"', self.argv_text())  # gh never ran
        self.assertEqual(self.items(), [])  # no keychain item made
        self.assertNotIn("add-generic-password", self.argv_text())

    def test_gh_account_filter(self):
        self.seed("svc", "someone-else", made_up_value())
        r = self.run_kit("gh", "svc", "NAME", "--account", "tester")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.gh_calls(), [])

    def test_gh_refuses_body_flags(self):
        self.seed("svc", "tester", made_up_value())
        for flag in (["--body", "x"], ["-b", "x"], ["-bx"], ["--body=x"], ["--env-file", "f"], ["--no-store"]):
            r = self.run_kit("gh", "svc", "NAME", *flag)
            self.assertEqual(r.returncode, 2, flag)
            self.assertIn("refused", r.stderr)
        self.assertEqual(self.gh_calls(), [])

    def test_gh_failure_is_reported(self):
        self.seed("svc", "tester", made_up_value())
        r = self.run_kit("gh", "svc", "NAME", env={"FAKE_GH_FAIL": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gh secret set NAME failed", r.stderr)

    def test_gh_unprintable_values_arrive_as_bytes(self):
        """security -w prints a value with any unprintable byte as hex; gh must still get the bytes."""
        values = ["-----BEGIN KEY-----\nabc\n-----END KEY-----\n", "a\tb", "caf\u00e9", "deadbeef",
                  "DEADBEEF", "6c696e65310a", "trailing\n\n", "  spaced  ", 'quo"te\'s $x \\n']
        for v in values:
            self.store.unlink(missing_ok=True)
            self.gh_log.unlink(missing_ok=True)
            self.seed("svc", "tester", v)
            r = self.run_kit("gh", "svc", "NAME")
            self.assertEqual(r.returncode, 0, (v, r.stderr))
            self.assertEqual(self.gh_calls()[0]["hex"], v.encode().hex(), repr(v))

    def test_gh_bytes_survive_perl_unicode_settings(self):
        """PERL_UNICODE or PERL5OPT=-CS in the environment must not re-encode non-ASCII bytes."""
        values = ["caf\u00e9", "-----BEGIN KEY-----\n\u00fc\tx\n", "back\\slash \u00e9"]
        for extra in ({"PERL_UNICODE": "SDA"}, {"PERL5OPT": "-CS"}, {"PERL_UNICODE": "SDA", "PERL5OPT": "-CS"}):
            for v in values:
                self.store.unlink(missing_ok=True)
                self.gh_log.unlink(missing_ok=True)
                self.seed("svc", "tester", v)
                r = self.run_kit("gh", "svc", "NAME", env=extra)
                self.assertEqual(r.returncode, 0, (extra, v, r.stderr))
                self.assertEqual(self.gh_calls()[0]["hex"], v.encode().hex(), (extra, repr(v)))

    def test_gh_refuses_combined_short_flags(self):
        self.seed("svc", "tester", made_up_value())
        for flag in (["-ub", "literal"], ["-uf", "some.env"], ["-Rb"]):
            r = self.run_kit("gh", "svc", "NAME", *flag)
            self.assertEqual(r.returncode, 2, flag)
            self.assertIn("refused", r.stderr)
        self.assertEqual(self.gh_calls(), [])
        r = self.run_kit("gh", "svc", "NAME", "-R", "o/r", "--env", "prod")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_key_hint_keeps_account_and_flags(self):
        r = self.run_kit("gh", "svc", "NAME", "--account", "bot", "--repo", "o/r")
        self.assertEqual(r.returncode, 1)
        self.assertIn("kit-secret save svc --account bot --gh NAME --repo o/r", r.stderr)

    # ---------------------------------------------------------------- path 1: generated value

    def test_new_sets_store_and_github_from_same_value(self):
        r = self.run_kit("new", "kit-secrets-test", "--gh", "KIT_SECRETS_TEST_GENERATED", "--repo", "o/r")
        self.assertEqual(r.returncode, 0, r.stderr)
        items = self.items()
        self.assertEqual(len(items), 1)
        v = items[0]["v"]
        self.assertRegex(v, r"^[0-9a-f]{64}$")
        self.assertEqual(items[0]["a"], "tester")
        calls = self.gh_calls()
        self.assertEqual(calls[0]["stdin"], v)
        self.assertEqual(calls[0]["argv"], ["secret", "set", "KIT_SECRETS_TEST_GENERATED", "--repo", "o/r"])
        self.assert_nowhere(v, r.stdout, r.stderr)
        # The keychain write went through `security -i` on stdin, not through argv.
        self.assertIn('["security", "-i"]', self.argv_text())

    def test_new_without_gh_only_saves(self):
        r = self.run_kit("new", "svc", "--bytes", "16")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(self.items()[0]["v"], r"^[0-9a-f]{32}$")
        self.assertEqual(self.gh_calls(), [])

    def test_new_refuses_to_overwrite(self):
        old = made_up_value()
        self.seed("svc", "tester", old)
        r = self.run_kit("new", "svc", "--gh", "NAME")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already in the keychain store", r.stderr)
        self.assertEqual(self.items()[0]["v"], old)
        self.assertEqual(self.gh_calls(), [])
        r = self.run_kit("new", "svc", "--replace")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(self.items()[0]["v"], old)

    def test_new_gh_failure_keeps_store_and_says_how_to_retry(self):
        r = self.run_kit("new", "svc", "--gh", "NAME", "--repo", "o/r", env={"FAKE_GH_FAIL": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.items()), 1)
        self.assertIn("kit-secret gh svc NAME --account tester --repo o/r", r.stderr)
        self.assertIn("the two differ", r.stderr)

    def test_new_bad_bytes(self):
        for b in ("abc", "8", "1000", ""):
            r = self.run_kit("new", "svc", "--bytes", b)
            self.assertEqual(r.returncode, 2, b)
        self.assertEqual(self.items(), [])

    def test_names_with_quotes_are_refused(self):
        for bad in ('a"b', "a\\b", "a'b", "-x"):
            r = self.run_kit("new", bad)
            self.assertNotEqual(r.returncode, 0, bad)
        self.assertEqual(self.items(), [])

    # ---------------------------------------------------------------- path 3: hidden prompt

    def test_save_without_terminal_refuses(self):
        r = self.run_kit("save", "kit-secrets-test", "--gh", "NAME")
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs your own terminal", r.stderr)
        self.assertIn("Open a terminal tab and run: kit-secret save kit-secrets-test", r.stderr)
        self.assertEqual(self.items(), [])
        self.assertEqual(self.argv_text(), "")  # no store or gh command ran at all

    def test_save_with_piped_stdin_refuses(self):
        r = self.run_kit("save", "svc", stdin=subprocess.PIPE)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.items(), [])

    def test_save_refuses_when_only_stdin_is_not_a_terminal(self):
        """A terminal on stderr alone, as when a value is piped in, still refuses."""
        mfd, sfd = pty.openpty()
        try:
            r = subprocess.run([str(SCRIPT), "save", "svc"], input=made_up_value(), text=True,
                               stdout=sfd, stderr=sfd, env=self.env, timeout=30)
            out = os.read(mfd, 4096).decode()
        finally:
            os.close(sfd)
            os.close(mfd)
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs your own terminal", out)
        self.assertEqual(self.items(), [])
        self.assertEqual(self.argv_text(), "")

    def test_save_no_terminal_hint_keeps_flags(self):
        r = self.run_kit("save", "svc", "--account", "bot", "--replace", "--gh", "NAME", "--repo", "o/r")
        self.assertEqual(r.returncode, 2)
        self.assertIn("run: kit-secret save svc --account bot --replace --gh NAME --repo o/r", r.stderr)

    def test_save_gh_failure_says_store_and_github_differ(self):
        self.seed("svc", "tester", made_up_value())
        v = made_up_value()
        self.env["FAKE_GH_FAIL"] = "1"
        code, out = self.run_kit_pty("save", "svc", "--replace", "--gh", "NAME", "--repo", "o/r", answers=[v, v])
        self.assertNotEqual(code, 0)
        self.assertIn("the two differ", out)
        self.assertIn("kit-secret gh svc NAME --account tester --repo o/r", out.replace("\r\n", " ").replace("\n", " "))
        self.assertEqual(self.items()[0]["v"], v)

    def test_save_through_pty_then_gh(self):
        v = made_up_value()
        self.clip.write_text(v)  # as if copied from a dashboard
        code, out = self.run_kit_pty("save", "kit-secrets-test", "--gh", "KIT_SECRETS_TEST_PASTED",
                                     "--repo", "o/r", answers=[v, v])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.items(), [{"s": "kit-secrets-test", "a": "tester", "v": v}])
        self.assertEqual(self.gh_calls()[0]["stdin"], v)
        self.assertIn("cleared the clipboard", out)
        self.assertEqual(self.clip.read_text(), "")
        # Echo is off at the prompt, so the terminal never showed what was typed.
        self.assert_nowhere(v, out)

    def test_save_leaves_unrelated_clipboard(self):
        v = made_up_value()
        self.clip.write_text("something else")
        code, out = self.run_kit_pty("save", "svc", answers=[v, v])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.clip.read_text(), "something else")
        self.assertNotIn("cleared the clipboard", out)

    def test_save_mismatch_saves_nothing(self):
        code, out = self.run_kit_pty("save", "svc", "--gh", "NAME", answers=[made_up_value(), made_up_value()])
        self.assertNotEqual(code, 0)
        self.assertEqual(self.items(), [])
        self.assertEqual(self.gh_calls(), [])

    def test_save_refuses_to_overwrite(self):
        old = made_up_value()
        self.seed("svc", "tester", old)
        code, out = self.run_kit_pty("save", "svc", answers=[made_up_value(), made_up_value()])
        self.assertEqual(code, 1)
        self.assertIn("--replace", out)
        self.assertEqual(self.items()[0]["v"], old)

    # ---------------------------------------------------------------- misc

    def test_help_and_unknown(self):
        self.assertEqual(self.run_kit("help").returncode, 0)
        self.assertEqual(self.run_kit("bogus").returncode, 2)
        self.assertEqual(self.run_kit().returncode, 2)

    def test_bad_store(self):
        r = self.run_kit("gh", "svc", "NAME", env={"KIT_SECRET_STORE": "vault"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("keychain or secret-tool", r.stderr)


if __name__ == "__main__":
    unittest.main()
