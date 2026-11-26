"""Docket's parser: a card keeps its id when it changes column (the page's pending marks depend
on it), tags and Done dates parse, and the Done column shows only the last week."""
import datetime as dt
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

BUILD = Path(__file__).resolve().parents[1] / "skills/chief-of-staff/docket/build.py"


def load_build():
    tmp = tempfile.mkdtemp()
    os.environ["COS_QUESTIONS"] = os.path.join(tmp, "questions.md")
    os.environ.pop("COS_GITHUB_ORG", None)  # no gh call
    spec = importlib.util.spec_from_file_location("docket_build", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b = load_build()
TODAY = dt.date.today()
SINCE = (TODAY - dt.timedelta(days=b.DONE_DAYS)).isoformat()


class ItemIds(unittest.TestCase):
    LINE = "**Renew the demo domain.** It lapses next week. Demo site."

    def test_same_id_in_every_column(self):
        you = b.parse_work_types("### Admin\n\n- " + self.LINE, set())[0]
        others = b.parse_column("- [admin] " + self.LINE, "others", set())[0]
        done = b.parse_column(f"- [admin, done {TODAY}] " + self.LINE, "done", set(), SINCE)[0]
        self.assertEqual({you["id"], others["id"], done["id"]}, {you["id"]})
        self.assertEqual([you["col"], others["col"], done["col"]], ["you", "others", "done"])

    def test_tag_and_project(self):
        c = b.parse_column("- [data] " + self.LINE, "someday", set())[0]
        self.assertEqual((c["type"], c["project"], c["title"]), ("data", "Demo site", "Renew the demo domain"))

    def test_untagged_lines_are_ignored_outside_by_work_type(self):
        self.assertEqual(b.parse_column("- " + self.LINE, "others", set()), [])


class Columns(unittest.TestCase):
    def test_question_records_after_items(self):
        text = "- [writing] **Write the notes.** Later. Example app.\n\n### 7. [apps] Example app: which colour?\n\nWhy.\n"
        cards = b.parse_column(text, "someday", set())
        self.assertEqual(sorted((c["kind"], c["col"]) for c in cards), [("item", "someday"), ("question", "someday")])
        self.assertEqual(next(c for c in cards if c["kind"] == "question")["num"], "7")

    def test_done_window(self):
        old = (TODAY - dt.timedelta(days=b.DONE_DAYS + 1)).isoformat()
        text = f"- [admin, done {TODAY}] **New thing.** Closed. Demo site.\n- [admin, done {old}] **Old thing.** Closed. Demo site.\n"
        self.assertEqual([c["title"] for c in b.parse_column(text, "done", set(), SINCE)], ["New thing"])

    def test_answered_window(self):
        old = (TODAY - dt.timedelta(days=b.DONE_DAYS + 1)).isoformat()
        text = (f"### 9. [agents] Example agent: keep it?\n\n**Answered** {TODAY} by you: no.\n\n"
                f"### 8. [admin] Demo site: keep it?\n\n**Settled** {old} by chief-of-staff, per a decision: no.\n")
        cards = b.parse_questions(text, "done", SINCE)
        self.assertEqual([(c["num"], c["done"]) for c in cards], [("9", TODAY.isoformat())])


SAMPLE = BUILD.parent / "sample/questions.md"
TEMPLATE = BUILD.parents[1] / "assets/questions-template.md"


class TypeKey(unittest.TestCase):
    def setUp(self):
        b.set_types(b.sections(SAMPLE.read_text())["By work type"])

    def test_types_come_from_the_subheadings(self):
        self.assertEqual([k for k, _ in b.TYPES], ["admin", "writing", "data", "services", "agents", "apps", "infra"])
        self.assertEqual(b.TYPE_LABEL["data"], "Data & science")

    def test_bare_keys_and_headings(self):
        for key, _ in list(b.TYPES):
            self.assertEqual(b.type_key(key), key)
        self.assertEqual(b.type_key("Building: data & science (estimators)"), "data")
        self.assertEqual(b.type_key(""), "admin")

    def test_unknown_tag_becomes_its_own_type(self):
        n = len(b.TYPES)
        self.assertEqual(b.type_key("Garden"), "garden")
        self.assertEqual((len(b.TYPES), b.TYPE_LABEL["garden"]), (n + 1, "Garden"))
        self.assertIn("--t-garden:", b.type_css(False))

    def test_template_taxonomy(self):
        b.set_types(b.sections(TEMPLATE.read_text())["By work type"])
        self.assertEqual(b.TYPES, [("admin", "Admin"), ("writing", "Writing"), ("building", "Building"), ("research", "Research")])
        self.assertEqual(b.type_key("research"), "research")

    def test_group_headings_key_on_the_name_after_the_colon(self):
        """The rule SKILL.md states: the tag is the first word of <Name>, after any `<Group>:`.
        Boards written with the old fixed taxonomy keep the tags they use today."""
        tags = {"admin": "admin", "writing": "writing", "data": "data", "services": "services",
                "agents": "agents", "apps": "apps", "infra": "infra", "data & science": "data",
                "Apps & UI": "apps", "Building: infra & ops (cloud)": "infra"}
        for tag, key in tags.items():
            self.assertEqual(b.type_key(tag), key, tag)
        self.assertEqual(len(b.TYPES), 7)
        b.set_types("### Admin: access and approvals\n\n### Writing\n")
        self.assertEqual([k for k, _ in b.TYPES], ["access", "writing"])

    def test_exact_label_beats_a_word_match(self):
        b.set_types("### Admin\n\n### Research admin\n")
        self.assertEqual(b.TYPES, [("admin", "Admin"), ("research", "Research admin")])
        self.assertEqual(b.type_key("Research admin"), "research")
        self.assertEqual(b.type_key("research"), "research")
        self.assertEqual(b.type_key("admin"), "admin")

    def test_template_builds_with_no_placeholder_type(self):
        text = TEMPLATE.read_text()
        secs = b.sections(text)
        b.set_types(secs["By work type"])
        ids = set()
        cards = (b.parse_questions(secs["Open, by rank"]) + b.parse_work_types(secs["By work type"], ids)
                 + b.parse_column(secs["Waiting on others"], "others", ids)
                 + b.parse_column(secs["Someday"], "someday", ids)
                 + b.parse_column(secs["Done"], "done", ids))
        self.assertTrue(cards)
        self.assertEqual({c["type"] for c in cards} - {"admin", "writing", "building", "research"}, set())
        self.assertEqual([k for k, _ in b.TYPES], ["admin", "writing", "building", "research"])


class OpenPage(unittest.TestCase):
    """--open: Chrome on macOS when `open -a` succeeds, the default browser otherwise."""

    def run_with(self, platform, code):
        calls, opened = [], []
        run = lambda cmd: (calls.append(cmd), type("R", (), {"returncode": code})())[1]
        import webbrowser
        real, webbrowser.open = webbrowser.open, opened.append
        try:
            used = b.open_page("http://127.0.0.1:8799/", platform, run)
        finally:
            webbrowser.open = real
        return used, calls, opened

    def test_macos_with_chrome(self):
        used, calls, opened = self.run_with("darwin", 0)
        self.assertEqual((used, calls[0][:3], opened), ("chrome", ["open", "-a", "Google Chrome"], []))

    def test_macos_without_chrome(self):
        self.assertEqual(self.run_with("darwin", 1)[::2], ("default", ["http://127.0.0.1:8799/"]))

    def test_linux_and_windows(self):
        for platform in ("linux", "win32"):
            used, calls, opened = self.run_with(platform, 0)
            self.assertEqual((used, calls, opened), ("default", [], ["http://127.0.0.1:8799/"]))


def load_server():
    spec = importlib.util.spec_from_file_location("docket_server", BUILD.parent / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AttachPlan(unittest.TestCase):
    s = load_server()
    BG = {"kind": "background", "id": "0123abcd"}
    FG = {"kind": "interactive", "pid": 4242}

    def test_macos(self):
        code, script = self.s.attach_plan(self.BG, "darwin")
        self.assertEqual(code, 200)
        self.assertIn("claude attach 0123abcd", script)
        code, script = self.s.attach_plan(self.FG, "darwin", tty_of=lambda pid: "ttys007")
        self.assertEqual(code, 200)
        self.assertIn('"/dev/ttys007"', script)
        self.assertEqual(self.s.attach_plan(self.FG, "darwin", tty_of=lambda pid: "??")[0], 404)

    def test_off_macos_refuses_with_the_command(self):
        for platform in ("linux", "win32"):
            code, msg = self.s.attach_plan(self.BG, platform, tty_of=lambda pid: self.fail("no ps off macOS"))
            self.assertEqual((code, "claude attach 0123abcd" in msg), (501, True))
            self.assertEqual(self.s.attach_plan(self.FG, platform, tty_of=lambda pid: self.fail())[0], 501)


if __name__ == "__main__":
    unittest.main()
