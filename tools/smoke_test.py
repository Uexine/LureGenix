"""Live Linux acceptance check: authentication, placement, read event, acknowledgement."""

import argparse
import getpass
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from setup_env import read_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--directory", default="/opt")
    parser.add_argument("--ca-file")
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument(
        "--node-id",
        type=int,
        help="ID агента этого Linux-сервера, если его hostname переопределён",
    )
    args = parser.parse_args()
    if args.node_id is not None and args.node_id < 1:
        parser.error("ID сервера должен быть положительным")
    if not args.api_only and sys.platform != "linux":
        parser.error(
            "File monitoring checks must run on the Linux agent host; use --api-only here"
        )
    env = read_env(Path(".env"))
    password = getpass.getpass(
        "Administrator password (Enter = .env bootstrap password): "
    ) or env.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    token = None
    tls_context = ssl.create_default_context(cafile=args.ca_file)

    def request(path, method="GET", data=None, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if token and authenticated:
            headers["Authorization"] = "Bearer " + token
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(
            args.url.rstrip("/") + "/api/" + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                req, timeout=240, context=tls_context
            ) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                result = json.load(error)
            except ValueError:
                result = {"detail": "HTTP " + str(error.code)}
            return error.code, result
        except urllib.error.URLError as error:
            raise SystemExit(
                "Application connection failed; check URL, service status and TLS CA"
            ) from error

    def require(condition, message):
        if not condition:
            raise SystemExit("FAIL: " + message)
        print("PASS:", message)

    require(
        request("nodes", authenticated=False)[0] == 401, "Anonymous access is blocked"
    )
    require(
        request("agent/tasks?node_id=1", authenticated=False)[0] == 401,
        "Anonymous agent requests are blocked",
    )
    require(request("readiness")[0] == 200, "All backend services are ready")
    status, result = request(
        "login", "POST", {"username": args.username, "password": password}, False
    )
    require(status == 200, "Administrator login")
    token = result["token"]
    require(
        request(
            "generate",
            "POST",
            {"node_id": 1, "type": "api_key", "node_path": "/opt/../etc"},
        )[0]
        == 400,
        "Path traversal is rejected",
    )
    status, nodes = request("nodes")
    require(status == 200, "Nodes can be listed")
    status, types = request("token-types")
    require(status == 200 and bool(types), "Generator types can be listed")
    if args.api_only:
        print(
            "API check completed. Full file monitoring requires the Linux host agent."
        )
        return
    candidates = [
        node
        for node in nodes
        if (
            node["id"] == args.node_id
            if args.node_id is not None
            else node["hostname"] == socket.gethostname()
        )
        and node["status"] == "online"
        and node.get("enrolled", True)
    ]
    require(
        len(candidates) == 1,
        "Ровно один агент этого Linux-сервера в сети; при совпадении hostname укажите --node-id",
    )
    filename = "service-backup-" + uuid.uuid4().hex[:12] + ".key"
    status, job = request(
        "generate",
        "POST",
        {
            "node_id": candidates[0]["id"],
            "type": "api_key",
            "node_path": args.directory,
            "filename": filename,
            "name": "Acceptance check",
        },
    )
    require(status == 200, "Generation enqueued")
    deadline = time.monotonic() + 120
    deployed = None
    while time.monotonic() < deadline:
        status, tokens = request("tokens")
        if status != 200:
            raise SystemExit("Token service unavailable")
        deployed = next(
            (item for item in tokens if item["id"] == job["token_id"]), None
        )
        if deployed and deployed["deployment_status"] == "failed":
            raise SystemExit(
                "Deployment failed: " + deployed.get("deployment_error", "")
            )
        if deployed and deployed["deployment_status"] == "deployed":
            break
        time.sleep(2)
    require(
        bool(deployed) and deployed["deployment_status"] == "deployed",
        "Agent confirmed deployment",
    )
    path = Path(deployed["deployed_path"])
    require(
        path == Path(args.directory) / filename,
        "File was placed in the selected directory",
    )
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(
            stream.read().startswith(b"API_KEY="), "The real deployed file can be read"
        )
    deadline = time.monotonic() + 45
    event = None
    while time.monotonic() < deadline:
        status, events = request("events")
        if status == 200:
            event = next(
                (
                    item
                    for item in events
                    if item["token_id"] == job["token_id"]
                    and item["action"] in ("open", "access")
                ),
                None,
            )
        if event:
            break
        time.sleep(2)
    require(event is not None, "File access produced a security event")
    require(
        request(f"events/{event['id']}/read", "PUT", {})[0] == 200,
        "Administrator acknowledged the event",
    )
    print("Acceptance check completed. Test decoy left under monitoring:", path)


if __name__ == "__main__":
    main()
