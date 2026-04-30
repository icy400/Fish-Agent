import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "server" / "static"


class RealtimeFrontendTests(unittest.TestCase):
    def test_realtime_page_contains_required_api_calls(self):
        html = (STATIC / "realtime.html").read_text(encoding="utf-8")
        self.assertIn("/api/realtime/clients", html)
        self.assertIn("/commands/start", html)
        self.assertIn("/commands/stop", html)
        self.assertIn("/api/realtime/sessions", html)
        self.assertIn("/segments?limit=20", html)
        self.assertIn("clients-body", html)
        self.assertIn("latest-body", html)
        self.assertIn("timeline", html)

    def test_realtime_page_renders_multi_client_controls(self):
        html = (STATIC / "realtime.html").read_text(encoding="utf-8")
        self.assertIn("采集端列表", html)
        self.assertIn("selected-client", html)
        self.assertIn("startClient", html)
        self.assertIn("stopClient", html)
        self.assertIn("viewClient", html)

    def test_existing_pages_link_to_realtime(self):
        for page in ["index.html", "upload.html", "detail.html"]:
            html = (STATIC / page).read_text(encoding="utf-8")
            self.assertIn("/realtime.html", html)
            self.assertIn("实时监测", html)

    def test_timeline_uses_dom_api_for_title_attributes(self):
        html = (STATIC / "realtime.html").read_text(encoding="utf-8")
        render_start = html.index("function renderTimeline")
        render_end = html.index("function renderTable")
        render_code = html[render_start:render_end]
        self.assertIn("document.createElement('div')", render_code)
        self.assertIn("bar.title = title", render_code)
        self.assertNotIn('title="${', render_code)

    def test_client_and_segment_tables_escape_server_strings(self):
        html = (STATIC / "realtime.html").read_text(encoding="utf-8")
        self.assertIn("escapeHtml(client.client_id", html)
        self.assertIn("escapeHtml(client.message", html)
        self.assertIn("escapeHtml(row.feeding_message", html)


if __name__ == "__main__":
    unittest.main()
