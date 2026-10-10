"""Browser regression check against fixture API responses; no running backend required."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws:",
        )
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/dashboard"):
            self.path = "/dashboard.html"
        super().do_GET()

    def log_message(self, *args):
        pass


def main():
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "frontend"))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    nodes = [
        {"id": 7, "hostname": "main-linux", "ip": "10.124.21.50", "status": "online"},
        {
            "id": 9,
            "hostname": "network-linux",
            "ip": "10.124.21.51",
            "status": "offline",
        },
    ]
    tokens = [
        {
            "id": "example-token",
            "type": "db_dump",
            "path": "/var/www/html/database_backup.sql",
            "placement": "node:7, path:auto",
            "node_id": 7,
            "deployment_status": "deployed",
            "deployed_path": "/var/www/html/database_backup.sql",
            "created_at": "2026-10-07T10:00:00",
        }
    ]
    requests = []
    event = {
        "id": 1,
        "token_id": "example-token",
        "action": "access",
        "file_path": "/var/www/html/database_backup.sql",
        "source_hostname": "main-linux",
        "created_at": "2026-10-07T10:01:00Z",
        "read_at": None,
    }

    def api(route):
        path = route.request.url.split("/api/")[-1]
        data = []
        if path == "login":
            assert route.request.post_data_json["username"] == "admin"
            data = {"token": "fixture-token", "username": "Admin"}
        elif path == "nodes":
            data = nodes
        elif path == "tokens":
            data = tokens
        elif path == "token-types":
            data = [{"name": "db_dump", "description": "SQL database backup"}]
        elif path == "events/unread_count":
            data = {"count": int(event["read_at"] is None)}
        elif path == "events":
            data = [event]
        elif path in ("events/1/read", "events/read_all"):
            event["read_at"] = "2026-10-07T10:02:00Z"
            data = {"status": "ok"}
        elif path == "generation-status":
            data = {"mode": "template", "ready": True, "model": "qwen2.5:3b"}
        elif path == "scan":
            data = {
                "subnet": "10.124.21.0/24",
                "hosts": [{"ip": "10.124.21.51", "ssh_port": 22}],
            }
        elif path == "password":
            data = {"status": "ok"}
        elif path == "generate":
            requests.append(route.request.post_data_json)
            data = {"status": "pending", "deployment_task_id": 12}
        route.fulfill(json=data)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            for width, height in [(1440, 1000), (390, 844)]:
                event["id"] = 1
                event["read_at"] = None
                context = browser.new_context(
                    viewport={"width": width, "height": height}
                )
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                # CDN availability must not make a fixture-based workflow check hang.
                page.route("https://**", lambda route: route.abort())
                page.route("**/api/**", api)
                page.route_web_socket("**/ws/events", lambda ws: None)
                page.goto(
                    f"http://127.0.0.1:{server.server_port}/",
                    wait_until="domcontentloaded",
                )
                page.fill("#username", "admin")
                page.fill("#password", "Test-Admin-Password-2026")
                page.screenshot(path=str(output / f"login-{width}.png"))
                page.click("#loginBtn")
                page.wait_for_url("**/dashboard")
                assert page.locator("#userAvatar").inner_text() == "A"
                if width < 780:
                    page.click(".mobile-menu-toggle")
                    page.locator(".sidebar-nav [data-section='nodes']").click()
                    assert not page.locator("#sidebar").evaluate(
                        "element => element.classList.contains('collapsed')"
                    )
                    page.click(".mobile-menu-toggle")
                    page.locator(".sidebar-nav [data-section='dashboard']").click()
                assert (
                    page.evaluate("sessionStorage.getItem('token')") == "fixture-token"
                )
                page.wait_for_function(
                    "() => document.querySelector('#nodeSelect').options.length === 2"
                )
                page.wait_for_function(
                    "() => document.querySelector('#eventCount').textContent === '1'"
                )
                event["id"] = 2
                page.wait_for_function(
                    "() => document.querySelector('#notification')?.textContent.includes('/var/www/html/database_backup.sql')",
                    timeout=10000,
                )
                page.evaluate("document.querySelector('#notification').remove(); loadEvents()")
                page.wait_for_timeout(300)
                assert page.locator("#notification").count() == 0
                event["id"] = 1
                page.select_option("#nodeSelect", "9")
                page.fill("#tokenNodePath", "/home/app")
                page.fill("#tokenFilename", "backup.sql")
                page.click("#btnGenerate")
                page.wait_for_function(
                    "() => !document.querySelector('#btnGenerate').disabled"
                )
                assert requests[-1]["node_id"] == "9"
                assert requests[-1]["node_path"] == "/home/app"
                assert requests[-1]["filename"] == "backup.sql"
                page.select_option("#deploymentMode", "auto")
                assert page.locator("#tokenNodePath").is_disabled()
                page.click("#btnGenerate")
                page.wait_for_function(
                    "() => !document.querySelector('#btnGenerate').disabled"
                )
                assert "node_path" not in requests[-1]
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                assert (
                    page.locator("#generatorStatus").inner_text()
                    == "Генератор: шаблоны"
                )
                page.wait_for_timeout(3100)
                page.screenshot(
                    path=str(output / f"dashboard-{width}.png"), full_page=True
                )
                page.evaluate("showSection('tokens')")
                page.wait_for_timeout(250)
                assert page.locator("#tokensTable").inner_text().find("Размещён") >= 0
                page.screenshot(
                    path=str(output / f"tokens-{width}.png"), full_page=True
                )
                page.evaluate("showSection('events')")
                page.locator("#eventsListFull [data-action='markEventRead']").wait_for()
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                page.screenshot(
                    path=str(output / f"events-{width}.png"), full_page=True
                )
                page.click("#eventsListFull [data-action='markEventRead']")
                page.locator("#eventsListFull .event-item-read").wait_for()
                page.evaluate("showSection('nodes')")
                page.fill("#scanSubnet", "10.124.21.0/24")
                page.click("#btnScan")
                page.wait_for_function(
                    "() => document.querySelector('#scanResults').innerText.includes('10.124.21.51:22')"
                )
                assert page.locator("#nodeCount").inner_text() == "1"
                page.screenshot(path=str(output / f"nodes-{width}.png"), full_page=True)
                page.click("[data-action='passwordDialog']")
                page.fill("#currentPassword", "Previous-Test-Password")
                page.fill("#newPassword", "New-Test-Password-2026")
                page.fill("#confirmPassword", "New-Test-Password-2026")
                assert page.locator("#passwordDialog").is_visible()
                page.screenshot(path=str(output / f"password-{width}.png"))
                page.click("#passwordForm button[type='submit']")
                page.wait_for_function(
                    "() => !document.querySelector('#passwordDialog').open"
                )
                page.evaluate("showSection('map')")
                page.wait_for_function(
                    "() => document.querySelector('#networkMap').innerText.includes('database_backup.sql')"
                )
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
