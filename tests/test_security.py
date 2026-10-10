import datetime
import hashlib
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_deployment import ROOT, database, gateway, load_module, service

discovery = load_module("tested_discovery", "services/discovery_service/main.py")
events = load_module("tested_events", "services/event_service/main.py")
setup_env = load_module("tested_setup_env", "tools/setup_env.py")


class GatewaySecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(gateway.app)
        self.headers = {"X-Agent-Id": str(uuid.uuid4()), "X-Agent-Token": "a" * 48}

    def test_agent_cannot_read_another_node(self):
        with patch.object(
            gateway,
            "forward_request",
            return_value=({"node_id": 7, "hostname": "linux"}, 200),
        ) as forward:
            self.assertEqual(
                self.client.get(
                    "/api/agent/tasks?node_id=9", headers=self.headers
                ).status_code,
                403,
            )
            self.assertEqual(forward.call_count, 1)

    def test_agent_cannot_report_another_node(self):
        with patch.object(
            gateway,
            "forward_request",
            return_value=({"node_id": 7, "hostname": "linux"}, 200),
        ) as forward:
            response = self.client.put(
                "/api/agent/tasks/1/result",
                headers=self.headers,
                json={"node_id": 9, "status": "deployed"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(forward.call_count, 1)

    def test_event_identity_is_server_bound(self):
        with patch.object(
            gateway,
            "forward_request",
            side_effect=[
                ({"node_id": 7, "hostname": "linux"}, 200),
                ({"status": "ok"}, 200),
            ],
        ) as forward:
            response = self.client.post(
                "/api/agent/event",
                headers=self.headers,
                json={"node_id": 9, "source_hostname": "spoofed", "action": "access"},
            )
            self.assertEqual(response.status_code, 200)
            data = forward.call_args.kwargs["data"]
            self.assertEqual(data["node_id"], 7)
            self.assertEqual(data["source_hostname"], "linux")

    def test_jwt_without_expiration_is_rejected(self):
        with patch.object(gateway, "JWT_SECRET", "a" * 48):
            token = gateway.jwt.encode(
                {"sub": "1"}, gateway.JWT_SECRET, algorithm="HS256"
            )
            self.assertEqual(
                self.client.get(
                    "/api/nodes", headers={"Authorization": "Bearer " + token}
                ).status_code,
                401,
            )

    def test_public_event_endpoint_is_not_public(self):
        self.assertEqual(self.client.post("/api/event", json={}).status_code, 401)

    def test_event_deletion_requires_administrator_token(self):
        with patch.object(gateway, "forward_request") as forward:
            self.assertEqual(
                self.client.request(
                    "DELETE", "/api/events", json={"clear_all": True}
                ).status_code,
                401,
            )
            self.assertEqual(
                self.client.request(
                    "DELETE",
                    "/api/events",
                    headers=self.headers,
                    json={"clear_all": True},
                ).status_code,
                401,
            )
            forward.assert_not_called()

    def test_authorized_event_deletion_is_forwarded(self):
        gateway.app.dependency_overrides[gateway.verify_token] = lambda: {"sub": "7"}
        try:
            with patch.object(
                gateway, "forward_request", return_value=({"deleted": 2}, 200)
            ) as forward:
                response = self.client.request(
                    "DELETE", "/api/events", json={"ids": [1, 2]}
                )
            self.assertEqual(response.status_code, 200)
            forward.assert_called_once_with(
                gateway.EVENT_SERVICE, "/events", "DELETE", data={"ids": [1, 2]}
            )
        finally:
            gateway.app.dependency_overrides.pop(gateway.verify_token, None)

    def test_invalid_json_is_rejected_before_backend_access(self):
        with patch.object(gateway, "forward_request") as forward:
            response = self.client.post(
                "/api/login", content="{", headers={"Content-Type": "application/json"}
            )
        self.assertEqual(response.status_code, 400)
        forward.assert_not_called()

    def test_invalid_backend_json_is_not_reported_as_success(self):
        response = MagicMock(status_code=200, content=b"not json")
        response.json.side_effect = ValueError()
        with patch.object(gateway.requests, "request", return_value=response):
            _, status = gateway.forward_request("http://backend", "/test", "GET")
        self.assertEqual(status, 502)

    def test_backend_errors_have_one_detail_layer(self):
        with patch.object(
            gateway, "forward_request", return_value=({"detail": "A clear error"}, 400)
        ):
            with self.assertRaises(HTTPException) as caught:
                gateway.proxy_request("http://backend", "/test")
        self.assertEqual(caught.exception.detail, "A clear error")

    def test_nginx_stripped_routes_exist(self):
        gateway.app.dependency_overrides[gateway.verify_token] = lambda: {"sub": "7"}
        try:
            with patch.object(
                gateway, "forward_request", return_value=({"status": "ok"}, 200)
            ):
                self.assertEqual(self.client.get("/generation-status").status_code, 200)
                self.assertEqual(
                    self.client.post(
                        "/scan", json={"subnet": "192.0.2.0/24"}
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    self.client.post("/tokens/test/retry", json={}).status_code, 200
                )
                self.assertEqual(self.client.put("/password", json={}).status_code, 200)
        finally:
            gateway.app.dependency_overrides.pop(gateway.verify_token, None)

    def test_password_change_identity_cannot_be_overridden(self):
        gateway.app.dependency_overrides[gateway.verify_token] = lambda: {"sub": "7"}
        try:
            with patch.object(
                gateway, "forward_request", return_value=({"status": "ok"}, 200)
            ) as forward:
                self.assertEqual(
                    self.client.put(
                        "/password",
                        json={
                            "_admin_id": 9,
                            "current_password": "old",
                            "new_password": "New-Test-Password",
                        },
                    ).status_code,
                    200,
                )
                self.assertEqual(forward.call_args.kwargs["data"]["_admin_id"], "7")
        finally:
            gateway.app.dependency_overrides.pop(gateway.verify_token, None)

    def test_websocket_without_authentication_is_rejected(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws/events"):
                pass

    def test_login_attempt_limit(self):
        gateway.login_attempts.clear()
        try:
            with (
                patch.object(
                    gateway,
                    "forward_request",
                    return_value=({"detail": "invalid"}, 401),
                ),
                patch.object(gateway.time, "monotonic", return_value=1000),
            ):
                for _ in range(10):
                    self.assertEqual(
                        self.client.post(
                            "/api/login", json={"username": "test", "password": "wrong"}
                        ).status_code,
                        401,
                    )
                self.assertEqual(
                    self.client.post(
                        "/api/login", json={"username": "test", "password": "wrong"}
                    ).status_code,
                    429,
                )
        finally:
            gateway.login_attempts.clear()

    def test_backend_outage_is_not_an_empty_node_list(self):
        gateway.app.dependency_overrides[gateway.verify_token] = lambda: {}
        try:
            with patch.object(gateway, "forward_request", return_value=({}, 503)):
                self.assertEqual(self.client.get("/api/nodes").status_code, 503)
        finally:
            gateway.app.dependency_overrides.pop(gateway.verify_token, None)


class DiscoverySecurityTests(unittest.TestCase):
    def test_discovery_outside_allowlist_rejected(self):
        with patch.dict(os.environ, {"DISCOVERY_ALLOWED_CIDRS": "10.124.21.0/24"}):
            with self.assertRaises(HTTPException) as caught:
                discovery.scan_network("192.0.2.0/24")
        self.assertEqual(caught.exception.status_code, 403)

    def test_large_scan_rejected(self):
        with patch.dict(os.environ, {"DISCOVERY_ALLOWED_CIDRS": "10.0.0.0/8"}):
            with self.assertRaises(HTTPException) as caught:
                discovery.scan_network("10.0.0.0/16")
        self.assertEqual(caught.exception.status_code, 400)

    def test_bounded_scan_returns_only_open_ssh_ports(self):
        with (
            patch.dict(os.environ, {"DISCOVERY_ALLOWED_CIDRS": "192.0.2.0/30"}),
            patch.object(discovery.socket, "socket") as socket,
        ):
            socket.return_value.__enter__.return_value.connect_ex.return_value = 0
            result = discovery.scan_network("192.0.2.0/30")
        self.assertEqual(
            [host["ip"] for host in result["hosts"]], ["192.0.2.1", "192.0.2.2"]
        )

    def test_identity_takeover_rejected(self):
        connection, cursor = database([(7, hashlib.sha256(b"original").hexdigest())])
        data = discovery.Registration(
            hostname="linux",
            ip="192.0.2.1",
            agent_id=str(uuid.uuid4()),
            credential="a" * 48,
        )
        with patch.object(discovery, "get_db", return_value=connection):
            with self.assertRaises(HTTPException) as caught:
                discovery.register(data)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(cursor.execute.call_count, 2)


class EventSecurityTests(unittest.TestCase):
    def setUp(self):
        self.data = events.Event(
            event_id=uuid.uuid4(),
            node_id=7,
            token_id="token",
            action="access",
            file_path="/opt/file",
            source_hostname="linux",
        )

    def row(self):
        return (
            1,
            "token",
            "access",
            "/opt/file",
            datetime.datetime.now(),
            "linux",
            None,
            str(self.data.event_id),
            7,
        )

    def test_foreign_token_is_rejected(self):
        connection, _ = database([None])
        with patch.object(events, "get_db", return_value=connection):
            with self.assertRaises(HTTPException) as caught:
                events.add_event(self.data, BackgroundTasks())
        self.assertEqual(caught.exception.status_code, 403)

    def test_duplicate_delivery_does_not_broadcast_again(self):
        connection, _ = database([(1,), None, self.row()])
        background = MagicMock()
        with patch.object(events, "get_db", return_value=connection):
            result = events.add_event(self.data, background)
        self.assertEqual(result["status"], "ok")
        background.add_task.assert_not_called()

    def test_storage_failure_returns_error_status(self):
        with patch.object(
            events, "get_db", side_effect=events.psycopg2.OperationalError("offline")
        ):
            with self.assertRaises(HTTPException) as caught:
                events.add_event(self.data, BackgroundTasks())
        self.assertEqual(caught.exception.status_code, 503)

    def test_event_deletion_requires_explicit_nonempty_selection(self):
        client = TestClient(events.app)
        for payload in (
            {},
            {"ids": []},
            {"ids": [-1]},
            {"ids": [1], "clear_all": True},
            {"ids": [1] * 501},
            {"clear_all": True, "extra": "field"},
        ):
            with (
                self.subTest(payload=payload),
                patch.object(events, "get_db") as connect,
            ):
                self.assertEqual(
                    client.request("DELETE", "/events", json=payload).status_code, 422
                )
                connect.assert_not_called()

    def test_selected_event_deletion_does_not_touch_tokens(self):
        connection, cursor = database([])
        cursor.rowcount = 2
        background = MagicMock()
        with patch.object(events, "get_db", return_value=connection):
            result = events.delete_events(events.DeleteEvents(ids=[1, 2]), background)
        cursor.execute.assert_called_once_with(
            "DELETE FROM event_log WHERE id = ANY(%s)", ([1, 2],)
        )
        self.assertEqual(result["deleted"], 2)
        background.add_task.assert_called_once_with(
            events.broadcast_event, {"type": "events_deleted"}
        )

    def test_clear_all_preserves_event_sequence(self):
        connection, cursor = database([])
        cursor.rowcount = 10
        with patch.object(events, "get_db", return_value=connection):
            result = events.delete_events(
                events.DeleteEvents(clear_all=True), MagicMock()
            )
        cursor.execute.assert_called_once_with("DELETE FROM event_log")
        self.assertEqual(result["deleted"], 10)

    def test_deletion_storage_failure_returns_russian_error(self):
        with patch.object(
            events,
            "get_db",
            side_effect=events.psycopg2.OperationalError("secret in database error"),
        ):
            with self.assertRaises(HTTPException) as caught:
                events.delete_events(events.DeleteEvents(ids=[1]), MagicMock())
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("Не удалось очистить журнал", caught.exception.detail)
        self.assertNotIn("secret", caught.exception.detail)


class ConfigurationTests(unittest.TestCase):
    def test_existing_database_volume_is_discovered(self):
        results = [MagicMock(stdout="container-id\n"), MagicMock(stdout="old-volume\n")]
        with patch.object(setup_env.subprocess, "run", side_effect=results):
            self.assertEqual(setup_env.existing_database_volume(), "old-volume")

    def test_database_bind_mount_is_not_silently_replaced(self):
        results = [MagicMock(stdout="container-id\n"), MagicMock(stdout="\n")]
        with patch.object(setup_env.subprocess, "run", side_effect=results):
            with self.assertRaisesRegex(ValueError, "bind mount"):
                setup_env.existing_database_volume()

    def test_configured_volume_cannot_replace_existing_data(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / ".env"
            setup_env.configure(path, ROOT / ".env.example", volume="old-volume")
            before = path.read_text()
            with self.assertRaisesRegex(ValueError, "refusing to switch"):
                setup_env.configure(
                    path, ROOT / ".env.example", volume="different-volume"
                )
            self.assertEqual(path.read_text(), before)

    def test_secrets_created_once_and_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / ".env"
            first, created = setup_env.configure(path, ROOT / ".env.example")
            second, created_again = setup_env.configure(path, ROOT / ".env.example")
            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first["AGENT_SECRET"]), 32)
            self.assertNotEqual(first["DB_PASSWORD"], first["APP_DB_PASSWORD"])

    def test_compose_isolates_database_and_gateway(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        self.assertNotIn("ports", compose["services"]["postgres"])
        self.assertNotIn("ports", compose["services"]["gateway"])
        for name in (
            "auth_service",
            "honeytoken_service",
            "event_service",
            "discovery_service",
            "gateway",
        ):
            self.assertTrue(compose["services"][name]["read_only"])
            self.assertEqual(compose["services"][name]["cap_drop"], ["ALL"])
        self.assertEqual(sorted((ROOT / "db").glob("*.sql"))[0].name, "00_init.sql")

    def test_no_inline_javascript_handlers(self):
        for filename in ("index.html", "dashboard.html"):
            html = (ROOT / "frontend" / filename).read_text(encoding="utf-8")
            for handler in ("onclick=", "oninput=", "onchange=", "onsubmit="):
                self.assertNotIn(handler, html)

    def test_compose_waits_for_migrations(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        self.assertEqual(compose["name"], "luregenix")
        for name in (
            "auth_service",
            "honeytoken_service",
            "event_service",
            "discovery_service",
        ):
            self.assertEqual(
                compose["services"][name]["depends_on"]["database_init"]["condition"],
                "service_completed_successfully",
            )
        self.assertEqual(compose["services"]["ollama"]["profiles"], ["llm"])

    def test_stale_deployment_result_is_rejected(self):
        connection, cursor = database(
            [(11, "pending", None, "backup", "/opt", "backup.sql", "directory", 2)]
        )
        with patch.object(service, "get_db", return_value=connection):
            response = TestClient(service.app).put(
                "/agent/tasks/12/result",
                json={
                    "node_id": 7,
                    "status": "deployed",
                    "deployed_path": "/opt/backup.sql",
                    "attempt": 1,
                },
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_legacy_node_cannot_receive_new_deployments(self):
        connection, _ = database([(7, None)])
        with (
            patch.object(service, "get_db", return_value=connection),
            patch.object(service, "generate_file") as generate,
        ):
            response = TestClient(service.app).post(
                "/generate", json={"node_id": 7, "type": "api_key"}
            )
        self.assertEqual(response.status_code, 409)
        generate.assert_not_called()
