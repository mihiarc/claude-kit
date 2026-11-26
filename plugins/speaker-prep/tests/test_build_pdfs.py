"""build_pdfs.py finds Chrome on macOS, Linux and Windows, with the platform forced so every
branch runs on any machine."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills/speaker-prep/scripts/build_pdfs.py"
spec = importlib.util.spec_from_file_location("build_pdfs", SCRIPT)
bp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bp)


class FindChrome(unittest.TestCase):
    def find(self, platform, present=(), env=None, on_path=None):
        which = (lambda n: f"/usr/bin/{n}" if n == on_path else None)
        return bp.find_chrome(platform, env or {}, which, lambda p: p in present)

    def test_macos_app_bundle(self):
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        self.assertEqual(self.find("darwin", {mac}), mac)

    def test_linux_on_path(self):
        self.assertEqual(self.find("linux", on_path="chromium"), "/usr/bin/chromium")
        self.assertEqual(self.find("linux", on_path="google-chrome-stable"), "/usr/bin/google-chrome-stable")

    def test_linux_ignores_macos_paths(self):
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        self.assertIsNone(self.find("linux", {mac}))

    def test_windows_program_files(self):
        env = {"PROGRAMFILES": "C:/Program Files"}
        exe = str(Path("C:/Program Files") / "Google/Chrome/Application/chrome.exe")
        self.assertEqual(self.find("win32", {exe}, env), exe)

    def test_env_override_first(self):
        self.assertEqual(self.find("linux", {"/opt/chrome"}, {"CHROME": "/opt/chrome"}, "chromium"), "/opt/chrome")

    def test_nothing_found(self):
        self.assertIsNone(self.find("linux"))

    def test_install_hint(self):
        self.assertIn("brew", bp.install_hint("pandoc", "darwin"))
        self.assertIn("apt", bp.install_hint("pandoc", "linux"))
        self.assertIn("winget", bp.install_hint("pandoc", "win32"))


if __name__ == "__main__":
    unittest.main()
