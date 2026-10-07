import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


generator = load_module("generator", "services/honeytoken_service/generator.py")
service = load_module("token_service", "services/honeytoken_service/main.py")
agent_module = load_module("linux_agent", "agent/agent.py")
gateway = load_module("api_gateway", "gateway/main.py")


def database(rows):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = rows
    return connection, cursor


class GenerationTests(unittest.TestCase):
    def test_missing_local_service_fails(self):
        with patch.object(generator.requests, "post", side_effect=generator.requests.exceptions.ConnectionError):
            with self.assertRaises(generator.GenerationError) as error:
                generator.generate_file("db_dump")
        self.assertIn("Cannot connect to local Ollama", str(error.exception))

    def test_provider_response_used_for_sql(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "done": True, "done_reason": "stop", "message": {"content": json.dumps({
                "content": "CREATE TABLE users(id int); INSERT INTO users VALUES (1);"
            })}
        }
        with patch.dict(os.environ, {}, clear=True), patch.object(generator.requests, "post", return_value=response) as post:
            payload, source = generator.generate_file("db_dump")
            self.assertIn(b"CREATE TABLE", payload)
            self.assertEqual(source, "llm")
            self.assertEqual(post.call_args.args[0], "http://ollama:11434/api/chat")
            self.assertFalse(post.call_args.kwargs["json"]["stream"])
            self.assertEqual(post.call_args.kwargs["json"]["format"]["required"], ["content"])
            self.assertNotIn("headers", post.call_args.kwargs)

    def test_provider_failure_does_not_generate_placeholder(self):
        with patch.object(generator.requests, "post", side_effect=RuntimeError("secret in provider error")):
            with self.assertRaises(generator.GenerationError) as error:
                generator.generate_file("db_dump")
            self.assertNotIn("secret", str(error.exception))

    def test_unloaded_model_returns_clear_error(self):
        with patch.object(generator.requests, "post", return_value=MagicMock(status_code=404)):
            with self.assertRaises(generator.GenerationError) as error:
                generator.generate_file("db_dump")
        self.assertIn("model not found", str(error.exception))

    def test_local_model_timeout_is_reported(self):
        with patch.object(generator.requests, "post", side_effect=generator.requests.exceptions.Timeout):
            with self.assertRaises(generator.GenerationError) as error:
                generator.generate_file("db_dump")
        self.assertIn("timed out", str(error.exception))

    def test_truncated_local_response_is_rejected(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {"done": True, "done_reason": "length"}
        with patch.object(generator.requests, "post", return_value=response):
            with self.assertRaises(generator.GenerationError) as error:
                generator.generate_file("db_dump")
        self.assertIn("truncated", str(error.exception))

    def test_real_binary_file_formats(self):
        with patch.object(generator, "llm_content", return_value="Internal operations\nExample document contents."):
            pdf, _ = generator.generate_file("pdf")
            self.assertTrue(pdf.startswith(b"%PDF-"))
            docx, _ = generator.generate_file("docx")
            with zipfile.ZipFile(io.BytesIO(docx)) as archive:
                self.assertIn("word/document.xml", archive.namelist())
        sql = "CREATE TABLE users(id int); INSERT INTO users VALUES (1);\n"
        with patch.object(generator, "llm_content", return_value=sql):
            payload, _ = generator.generate_file("backup_archive")
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
                self.assertEqual(archive.extractfile("database_backup.sql").read(), sql.encode())

    def test_ssh_key_is_parseable(self):
        from cryptography.hazmat.primitives.serialization import load_ssh_private_key
        payload, source = generator.generate_file("ssh_key")
        self.assertEqual(load_ssh_private_key(payload, password=None).key_size, 2048)
        self.assertEqual(source, "local")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(service.app)

    def test_generation_enqueues_selected_host_path(self):
        connection, cursor = database([(7,), (11,), (31,)])
        with patch.object(service, "get_db", return_value=connection), patch.object(service, "generate_file", return_value=(b"SQL content", "llm")):
            response = self.client.post("/generate", json={"node_id": 7, "type": "db_dump", "node_path": "/var/www/html", "filename": "backup.sql"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")
        insert_file = cursor.execute.call_args_list[1].args[1]
        self.assertEqual(insert_file[1], "/var/www/html/backup.sql")
        task = cursor.execute.call_args_list[2].args[1]
        self.assertEqual(task[1], 7)
        self.assertEqual(task[4], "/var/www/html")
        self.assertEqual(base64.b64decode(task[6]), b"SQL content")

    def test_nonexistent_node_is_rejected_before_llm(self):
        connection, _ = database([None])
        with patch.object(service, "get_db", return_value=connection), patch.object(service, "generate_file") as generate:
            response = self.client.post("/generate", json={"node_id": 999, "type": "db_dump"})
            self.assertEqual(response.status_code, 404)
            generate.assert_not_called()

    def test_llm_failure_does_not_enqueue(self):
        connection, cursor = database([(7,)])
        with patch.object(service, "get_db", return_value=connection), patch.object(service, "generate_file", side_effect=generator.GenerationError("Provider unavailable")):
            response = self.client.post("/generate", json={"node_id": 7, "type": "db_dump"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(cursor.execute.call_count, 1)

    def test_invalid_paths_and_filenames_are_rejected(self):
        for values in ({"node_path": "relative"}, {"node_path": "/etc/../home"}, {"filename": "../passwd"}, {"target_kind": "file"}):
            with self.subTest(values=values):
                response = self.client.post("/generate", json={"node_id": 7, "type": "db_dump", **values})
                self.assertEqual(response.status_code, 400)

    def test_result_is_bound_to_node(self):
        connection, cursor = database([None])
        with patch.object(service, "get_db", return_value=connection):
            response = self.client.put("/agent/tasks/12/result", json={"node_id": 9, "status": "deployed", "deployed_path": "/opt/backup.sql"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(cursor.execute.call_args.args[1], (12, 9))

    def test_successful_acknowledgement_stores_actual_path(self):
        connection, cursor = database([(11, "pending", None, "backup", "/opt", "backup.sql", "directory")])
        with patch.object(service, "get_db", return_value=connection):
            response = self.client.put("/agent/tasks/12/result", json={"node_id": 7, "status": "deployed", "deployed_path": "/opt/backup.sql"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(cursor.execute.call_args_list[2].args[1], ("/opt/backup.sql", 11))

    def test_completed_task_path_cannot_be_changed(self):
        connection, cursor = database([(11, "deployed", "/opt/original.sql", "backup", "/opt", "original.sql", "directory")])
        with patch.object(service, "get_db", return_value=connection):
            response = self.client.put("/agent/tasks/12/result", json={"node_id": 7, "status": "deployed", "deployed_path": "/opt/changed.sql"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_runtime_schema_matches_migration(self):
        self.assertEqual(service.DEPLOYMENT_SCHEMA.strip(), (ROOT / "db/05_honeytoken_deployments.sql").read_text().strip())

    def test_agent_endpoints_require_secret(self):
        client = TestClient(gateway.app)
        with patch.dict(os.environ, {"AGENT_SECRET": "test-only"}), patch.object(gateway, "forward_request", return_value=([], 200)) as forward:
            self.assertEqual(client.get("/agent/tasks?node_id=7").status_code, 401)
            forward.assert_not_called()
            self.assertEqual(client.get("/api/agent/tasks?node_id=7", headers={"X-Agent-Secret": "test-only"}).status_code, 200)
            self.assertEqual(forward.call_args.args[1], "/agent/tasks?node_id=7")

    def test_gateway_uses_local_model_timeout(self):
        client = TestClient(gateway.app)
        gateway.app.dependency_overrides[gateway.verify_token] = lambda: {}
        try:
            with patch.dict(os.environ, {"LLM_TIMEOUT_SECONDS": "180"}), patch.object(gateway, "forward_request", return_value=({"status": "pending"}, 200)) as forward:
                response = client.post("/api/generate", json={"node_id": 7, "type": "db_dump"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(forward.call_args.kwargs["timeout"], 195)
        finally:
            gateway.app.dependency_overrides.pop(gateway.verify_token, None)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(agent_module, "STATE_FILE", self.root / "agent.json"),
            patch.object(agent_module, "ALLOWED_DIRS", [str(self.root)]),
            patch.object(agent_module, "AUTO_DIRS", [str(self.root)]),
        ]
        for item in self.patches:
            item.start()
        self.agent = agent_module.Agent(MagicMock())
        self.agent.watch = MagicMock()
        self.agent.monitor_events = MagicMock()
        self.agent.persist = MagicMock()
        self.task = {"id": 12, "token_id": "token-uuid", "type": "db_dump", "filename": "backup.sql",
                     "target_path": str(self.root), "target_kind": "directory", "status": "pending",
                     "content_base64": base64.b64encode(b"SQL content").decode(),
                     "sha256": hashlib.sha256(b"SQL content").hexdigest()}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_existing_file_is_never_overwritten(self):
        path = self.root / "backup.sql"
        path.write_text("real data")
        with patch.object(agent_module, "owned_file", return_value=False), patch.object(agent_module, "write_file") as write:
            result = self.agent.deploy(self.task)
            self.assertEqual(result["status"], "failed")
            write.assert_not_called()
            self.assertEqual(path.read_text(), "real data")

    def test_duplicate_task_uses_journal(self):
        with patch.object(agent_module, "write_file") as write:
            first = self.agent.deploy(self.task)
            second = self.agent.deploy(self.task)
            self.assertEqual(first["status"], "deployed")
            self.assertEqual(first["path"], str(self.root / "backup.sql"))
            self.assertIs(second, first)
            write.assert_called_once()

    def test_tampered_payload_is_rejected(self):
        self.task["sha256"] = "invalid"
        with patch.object(agent_module, "write_file") as write:
            self.assertEqual(self.agent.deploy(self.task)["status"], "failed")
            write.assert_not_called()

    def test_auto_placement_and_missing_directory(self):
        self.task["target_path"] = ""
        self.assertEqual(agent_module.target_file(self.task), str(self.root / "backup.sql"))
        self.task["target_path"] = str(self.root / "missing")
        with self.assertRaises(ValueError):
            agent_module.target_file(self.task)
        self.assertFalse((self.root / "missing").exists())

    def test_allowed_path_does_not_accept_sibling_prefix(self):
        self.assertFalse(agent_module.allowed_path(str(self.root) + "-sibling/backup.sql"))

    def test_unsent_event_remains_queued(self):
        self.agent.queue_event("token-uuid", "access", "/opt/backup.sql")
        with patch.object(self.agent, "request", side_effect=ConnectionError):
            with self.assertRaises(ConnectionError):
                self.agent.flush_events()
        self.assertEqual(self.agent.state["events"][0]["action"], "access")

    def test_lost_acknowledgement_does_not_duplicate_file(self):
        self.agent.node_id = 7
        with patch.object(agent_module, "write_file") as write, patch.object(self.agent, "request", side_effect=[
            [self.task], ConnectionError("Lost acknowledgement"), [self.task], {"status": "ok"}
        ]):
            with self.assertRaises(ConnectionError):
                self.agent.poll_tasks()
            self.agent.poll_tasks()
            write.assert_called_once()
        self.assertEqual(self.agent.state["events"][0]["action"], "deployed")

    def test_restore_monitors_without_backend(self):
        path = str(self.root / "backup.sql")
        (self.root / "agent.json").write_text(json.dumps({"tasks": {"uuid": {
            "status": "deployed", "path": path, "token_id": "uuid"
        }}, "events": []}))
        with patch.object(agent_module.Agent, "watch") as watch:
            restored = agent_module.Agent(MagicMock())
            self.assertIsNone(restored.node_id)
            watch.assert_called_once_with("uuid", path)

    def test_backend_deployed_task_is_saved_for_offline_restore(self):
        self.agent.node_id = 7
        task = {**self.task, "status": "deployed", "deployed_path": str(self.root / "backup.sql")}
        with patch.object(self.agent, "request", return_value=[task]):
            self.agent.poll_tasks()
        self.assertEqual(self.agent.state["tasks"]["token-uuid"]["path"], task["deployed_path"])


@unittest.skipUnless(sys.platform == "linux", "Real deployment and inotify require Linux")
class LinuxIntegrationTests(unittest.TestCase):
    def test_real_deployment_read_and_delete(self):
        from inotify_simple import INotify
        with tempfile.TemporaryDirectory() as directory, patch.object(agent_module, "ALLOWED_DIRS", [directory]), patch.object(agent_module, "STATE_FILE", Path(directory) / "state.json"), INotify() as monitor:
            agent = agent_module.Agent(monitor)
            payload = b"CREATE TABLE users(id int);\n"
            task = {"id": 1, "token_id": "test-token", "filename": "backup.sql", "target_path": directory,
                    "target_kind": "directory", "content_base64": base64.b64encode(payload).decode(),
                    "sha256": hashlib.sha256(payload).hexdigest()}
            result = agent.deploy(task)
            self.assertEqual(result["status"], "deployed", result.get("error"))
            agent.monitor_events(timeout=0)
            self.assertEqual(agent.state["events"], [], "Agent's own deployment must not trigger an alert")
            second = {**task, "id": 2, "token_id": "second-token", "filename": "second.sql"}
            self.assertEqual(agent.deploy(second)["status"], "deployed")
            agent.monitor_events(timeout=0)
            self.assertEqual(agent.state["events"], [], "Writing into a watched directory must not trigger an alert")
            path = Path(result["path"])
            self.assertEqual(path.read_bytes(), payload)
            agent.monitor_events(timeout=1000)
            self.assertTrue(any(e["action"] == "access" for e in agent.state["events"]))
            path.unlink()
            agent.monitor_events(timeout=1000)
            self.assertTrue(any(e["action"] == "delete" for e in agent.state["events"]))


if __name__ == "__main__":
    unittest.main()
