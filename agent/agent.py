"""Host-installed Linux agent: deployment tasks, inotify monitoring, durable delivery."""
import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import stat
import sys
import time
from urllib.parse import urlsplit

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
AGENT_SECRET = os.getenv("AGENT_SECRET", "")
NODE_HOSTNAME = os.getenv("NODE_HOSTNAME") or socket.gethostname()
NODE_IP = os.getenv("NODE_IP", "")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "60"))
TASK_POLL_INTERVAL = int(os.getenv("TASK_POLL_INTERVAL", "10"))
ALLOWED_DIRS = [p.strip() for p in os.getenv("AGENT_ALLOWED_DIRS", "/etc,/var/www,/home,/opt").split(",") if p.strip()]
AUTO_DIRS = [p.strip() for p in os.getenv("AGENT_AUTO_DIRS", "/var/www/html,/var/www,/opt,/home,/etc").split(",") if p.strip()]
STATE_FILE = Path(os.getenv("AGENT_STATE_FILE", "~/.local/state/luregenix/agent.json")).expanduser()


def allowed_path(path):
    resolved = os.path.realpath(path)
    return any(os.path.commonpath([resolved, os.path.realpath(root)]) == os.path.realpath(root) for root in ALLOWED_DIRS)


def target_file(task):
    filename = task["filename"]
    if filename in ("", ".", "..") or any(c in filename for c in "/\\\x00\r\n"):
        raise ValueError("Invalid filename")
    target = task.get("target_path", "")
    if target:
        if not os.path.isabs(target) or ".." in Path(target).parts:
            raise ValueError("Target must be an absolute path without '..'")
        path = target if task.get("target_kind") == "file" else os.path.join(target, filename)
    else:
        directory = next((p for p in AUTO_DIRS if os.path.isdir(p) and allowed_path(p) and os.access(p, os.W_OK | os.X_OK)), None)
        if not directory:
            raise ValueError("No existing writable directory in AGENT_AUTO_DIRS")
        path = os.path.join(directory, filename)
    if not allowed_path(path):
        raise ValueError("Target is outside AGENT_ALLOWED_DIRS")
    if not os.path.isdir(os.path.dirname(path)):
        raise ValueError("Target directory does not exist")
    return os.path.abspath(path)


def open_directory(path):
    # Walk using directory descriptors so a symlink swap cannot redirect a privileged write.
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in Path(path).parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def write_file(path, payload, token_id):
    directory = open_directory(os.path.dirname(path))
    try:
        descriptor = os.open(
            os.path.basename(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.setxattr(stream.fileno(), "user.luregenix.token_id", token_id.encode())
        os.fsync(directory)
    finally:
        os.close(directory)


def owned_file(path, token_id):
    try:
        return stat.S_ISREG(os.lstat(path).st_mode) and os.getxattr(path, "user.luregenix.token_id", follow_symlinks=False).decode() == token_id
    except OSError:
        return False


def discover_ip():
    if NODE_IP:
        return NODE_IP
    parsed = urlsplit(GATEWAY_URL)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.connect((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)))
        return connection.getsockname()[0]


class Agent:
    def __init__(self, monitor):
        self.monitor = monitor
        self.node_id = None
        self.session = requests.Session()
        self.session.headers["X-Agent-Secret"] = AGENT_SECRET
        self.state = {"tasks": {}, "events": []}
        if STATE_FILE.exists():
            # Stop on a corrupt journal rather than risk duplicating deployment.
            self.state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        self.watches = {}
        self.last_alert = {}
        self.monitor_failures = set()
        for record in self.state["tasks"].values():
            if record["status"] == "deployed":
                try:
                    self.watch(record["token_id"], record["path"])
                except (OSError, ValueError) as exc:
                    logger.warning("Could not restore monitoring for %s: %s", record["path"], exc)

    def persist(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = STATE_FILE.with_suffix(".tmp")
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(self.state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE_FILE)

    def request(self, method, path, **kwargs):
        response = self.session.request(method, f"{GATEWAY_URL}/api/{path}", timeout=10, **kwargs)
        response.raise_for_status()
        return response.json()

    def register(self):
        result = self.request("POST", "register", json={"hostname": NODE_HOSTNAME, "ip": discover_ip()})
        self.node_id = result["node_id"]

    def queue_event(self, token_id, action, path=""):
        self.state["events"].append({"token_id": token_id, "action": action, "file_path": path, "source_hostname": NODE_HOSTNAME})
        self.persist()

    def flush_events(self):
        deadline = time.monotonic() + 2
        while self.state["events"] and time.monotonic() < deadline:
            result = self.request("POST", "agent/event", json=self.state["events"][0])
            if result.get("status") != "ok":
                raise RuntimeError("Event was not saved")
            self.state["events"].pop(0)
            self.persist()

    def watch(self, token_id, path):
        from inotify_simple import flags
        if not allowed_path(path):
            raise ValueError("Monitor path is outside AGENT_ALLOWED_DIRS")
        parent = os.path.dirname(path)
        for descriptor, entry in self.watches.items():
            if entry["parent"] == parent:
                entry["files"][os.path.basename(path)] = token_id
                return
        mask = (flags.OPEN | flags.ACCESS | flags.MODIFY | flags.CLOSE_WRITE | flags.ATTRIB |
                flags.DELETE | flags.MOVED_FROM | flags.DELETE_SELF | flags.MOVE_SELF |
                flags.ONLYDIR | flags.DONT_FOLLOW)
        descriptor = self.monitor.add_watch(parent, mask)
        self.watches[descriptor] = {"parent": parent, "files": {os.path.basename(path): token_id}}

    def deploy(self, task):
        key = task["token_id"]
        record = self.state["tasks"].get(key)
        if record and record["status"] in ("deployed", "failed"):
            return record
        try:
            payload = base64.b64decode(task["content_base64"], validate=True)
            if hashlib.sha256(payload).hexdigest() != task["sha256"]:
                raise ValueError("File payload checksum mismatch")
            path = record["path"] if record else target_file(task)
            if record is None:
                record = {"status": "writing", "path": path, "token_id": task["token_id"]}
                self.state["tasks"][key] = record
                self.persist()
            if os.path.lexists(path):
                if not owned_file(path, task["token_id"]):
                    raise FileExistsError("File already exists; choose a different filename")
                # Recovery after a crash between write and acknowledgement. Verify before watching.
                with open(path, "rb") as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != task["sha256"]:
                        raise ValueError("Previously deployed file has changed; refusing to overwrite")
            else:
                write_file(path, payload, task["token_id"])
            self.monitor_events(timeout=0)
            self.watch(task["token_id"], path)
            record.update(status="deployed", error="")
        except Exception as exc:
            record = {"status": "failed", "path": record["path"] if record else "", "token_id": task["token_id"], "error": str(exc)[:1000]}
        self.state["tasks"][key] = record
        self.persist()
        return record

    def poll_tasks(self):
        tasks = self.request("GET", "agent/tasks", params={"node_id": self.node_id})
        for task in tasks:
            key = task["token_id"]
            if task["status"] == "deployed":
                try:
                    self.watch(task["token_id"], task["deployed_path"])
                    self.monitor_failures.discard(key)
                    if key not in self.state["tasks"]:
                        self.state["tasks"][key] = {"status": "deployed", "path": task["deployed_path"], "token_id": key, "announced": True}
                        self.persist()
                except (OSError, ValueError) as exc:
                    if key not in self.monitor_failures:
                        self.queue_event(task["token_id"], "monitor_error", task["deployed_path"])
                        self.monitor_failures.add(key)
                    logger.warning("Monitoring failed for %s: %s", task["deployed_path"], exc)
                continue
            record = self.deploy(task)
            result = self.request(
                "PUT", f"agent/tasks/{task['id']}/result",
                json={"node_id": self.node_id, "status": record["status"],
                      "deployed_path": record["path"] if record["status"] == "deployed" else "",
                      "error": record.get("error", "")},
            )
            if result.get("status") != "ok":
                raise RuntimeError("Deployment result was not saved")
            if not record.get("announced"):
                self.queue_event(task["token_id"], "deployed" if record["status"] == "deployed" else "deployment_failed", record["path"])
                record["announced"] = True
                self.persist()

    def monitor_events(self, timeout=1000):
        from inotify_simple import flags
        batch = {}
        for event in self.monitor.read(timeout=timeout):
            if event.mask & flags.Q_OVERFLOW:
                self.queue_event(f"node_{self.node_id}", "monitor_error", "inotify queue overflow")
                continue
            entry = self.watches.get(event.wd)
            if not entry:
                continue
            if event.mask & (flags.DELETE_SELF | flags.MOVE_SELF | flags.IGNORED):
                for filename, token_id in entry["files"].items():
                    batch[token_id] = ("delete", os.path.join(entry["parent"], filename), 4)
                self.watches.pop(event.wd, None)
                if not event.mask & flags.IGNORED:
                    try:
                        self.monitor.rm_watch(event.wd)
                    except OSError:
                        pass
                continue
            token_id = entry["files"].get(event.name)
            if not token_id:
                continue
            action, priority = "open", 1
            if event.mask & (flags.DELETE | flags.MOVED_FROM):
                action, priority = "delete", 4
            elif event.mask & (flags.MODIFY | flags.CLOSE_WRITE | flags.ATTRIB):
                action, priority = "modify", 3
            elif event.mask & flags.ACCESS:
                action, priority = "access", 2
            previous = batch.get(token_id)
            if not previous or priority > previous[2]:
                batch[token_id] = (action, os.path.join(entry["parent"], event.name), priority)
        now = time.monotonic()
        for token_id, (action, path, _) in batch.items():
            cooldown_key = (token_id, action)
            if now - self.last_alert.get(cooldown_key, -10) >= 2:
                self.queue_event(token_id, action, path)
                self.last_alert[cooldown_key] = now


def main():
    if sys.platform != "linux":
        raise SystemExit("Run this agent directly on the target Linux server")
    if not AGENT_SECRET:
        raise SystemExit("Set AGENT_SECRET to the same value configured on the gateway")
    from inotify_simple import INotify
    import fcntl

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # One writer per journal; duplicate processes must not deploy the same task.
    with open(STATE_FILE.with_suffix(".lock"), "w") as lock, INotify() as monitor:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        agent = Agent(monitor)
        heartbeat_at = poll_at = delivery_at = 0
        while True:
            now = time.monotonic()
            if now >= heartbeat_at:
                try:
                    agent.register()
                    agent.queue_event(f"node_{agent.node_id}", "heartbeat")
                    heartbeat_at = now + HEARTBEAT_INTERVAL
                except Exception as exc:
                    logger.warning("Registration/heartbeat failed: %s", exc)
                    heartbeat_at = now + 10
            if agent.node_id and now >= poll_at:
                try:
                    agent.poll_tasks()
                except Exception as exc:
                    logger.warning("Task poll failed: %s", exc)
                poll_at = now + TASK_POLL_INTERVAL
            agent.monitor_events()
            if time.monotonic() >= delivery_at:
                try:
                    agent.flush_events()
                except Exception as exc:
                    logger.warning("Event delivery failed: %s", exc)
                delivery_at = time.monotonic() + 5


if __name__ == "__main__":
    main()
