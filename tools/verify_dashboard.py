"""Browser regression check against fixture API responses; no running backend required."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/dashboard"):
            self.path = "/dashboard.html"
        super().do_GET()

    def log_message(self, *args):
        pass


def main():
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "frontend")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    nodes = [{"id": 7, "hostname": "main-linux", "ip": "10.124.21.50", "status": "online"},
             {"id": 9, "hostname": "network-linux", "ip": "10.124.21.51", "status": "offline"}]
    tokens = [{"id": "example-token", "type": "db_dump", "path": "/var/www/html/database_backup.sql",
               "placement": "node:7, path:auto", "node_id": 7, "deployment_status": "deployed",
               "deployed_path": "/var/www/html/database_backup.sql", "created_at": "2026-10-07T10:00:00"}]
    requests = []

    def api(route):
        path = route.request.url.split("/api/")[-1]
        data = []
        if path == "nodes":
            data = nodes
        elif path == "tokens":
            data = tokens
        elif path == "token-types":
            data = [{"name": "db_dump", "description": "SQL database backup"}]
        elif path == "events/unread_count":
            data = {"count": 0}
        elif path == "generate":
            requests.append(route.request.post_data_json)
            data = {"status": "pending", "deployment_task_id": 12}
        route.fulfill(json=data)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            for width, height in [(1440, 1000), (390, 844)]:
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script("localStorage.setItem('token', 'fixture-token'); localStorage.setItem('username', 'Admin');")
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                # CDN availability must not make a fixture-based workflow check hang.
                page.route("https://**", lambda route: route.abort())
                page.route("**/api/**", api)
                page.route_web_socket("**/ws/events", lambda ws: None)
                page.goto(f"http://127.0.0.1:{server.server_port}/dashboard", wait_until="domcontentloaded")
                page.wait_for_function("document.querySelector('#nodeSelect').options.length === 2")
                page.select_option("#nodeSelect", "9")
                page.fill("#tokenNodePath", "/home/app")
                page.fill("#tokenFilename", "backup.sql")
                page.click("#btnGenerate")
                page.wait_for_function("!document.querySelector('#btnGenerate').disabled")
                assert requests[-1]["node_id"] == "9"
                assert requests[-1]["node_path"] == "/home/app"
                assert requests[-1]["filename"] == "backup.sql"
                page.select_option("#deploymentMode", "auto")
                assert page.locator("#tokenNodePath").is_disabled()
                page.click("#btnGenerate")
                page.wait_for_function("!document.querySelector('#btnGenerate').disabled")
                assert "node_path" not in requests[-1]
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=str(output / f"dashboard-{width}.png"), full_page=True)
                page.evaluate("showSection('tokens')")
                page.wait_for_timeout(250)
                assert page.locator("#tokensTable").inner_text().find("Размещён") >= 0
                page.screenshot(path=str(output / f"tokens-{width}.png"), full_page=True)
                page.evaluate("showSection('map')")
                page.wait_for_function("document.querySelector('#networkMap').innerText.includes('database_backup.sql')")
                assert not errors, errors
                print(f"Browser workflows and layout passed at {width}x{height}")
                context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
