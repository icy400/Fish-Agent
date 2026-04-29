import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "server" / "static"


class RealtimeFrontendTests(unittest.TestCase):
    def test_realtime_page_contains_required_api_calls(self):
        html = (STATIC / "realtime.html").read_text(encoding="utf-8")
        self.assertIn("/api/realtime/sessions", html)
        self.assertIn("/segments?limit=20", html)
        self.assertIn("latest-body", html)
        self.assertIn("timeline", html)

    def test_existing_pages_link_to_realtime(self):
        for page in ["index.html", "upload.html", "detail.html"]:
            html = (STATIC / page).read_text(encoding="utf-8")
            self.assertIn("/realtime.html", html)
            self.assertIn("实时监测", html)


if __name__ == "__main__":
    unittest.main()
