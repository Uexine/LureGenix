"""Authenticated public API and agent boundary for the private backend services."""

import asyncio
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager, suppress

import jwt
import requests
import websockets
from fastapi import (
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

AUTH_SERVICE = "http://auth_service:8000"
EVENT_SERVICE = "http://event_service:8000"
EVENT_WS_URL = "ws://event_service:8000/ws/events"
TOKEN_SERVICE = "http://honeytoken_service:8000"
DISCOVERY_SERVICE = "http://discovery_service:8000"
JWT_SECRET = os.getenv("JWT_SECRET", "")
security = HTTPBearer(auto_error=False)
login_attempts = {}
login_lock = threading.Lock()
generation_limit = asyncio.Semaphore(2)


@asynccontextmanager
async def lifespan(app):
    if len(JWT_SECRET) < 32 or len(os.getenv("AGENT_SECRET", "")) < 32:
        raise RuntimeError(
            "Run python3 tools/setup_env.py to configure private secrets"
        )
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def forward_request(service_url, path, method, data=None, headers=None, timeout=5):
    if method not in ("GET", "POST", "PUT"):
        raise HTTPException(405, "Method not allowed")
    try:
        response = requests.request(
            method, service_url + path, json=data, headers=headers, timeout=timeout
        )
    except requests.RequestException as exc:
        raise HTTPException(503, "Backend service unavailable") from exc
    if not response.content:
        return {}, response.status_code
    try:
        return response.json(), response.status_code
    except ValueError:
        return {"detail": "Invalid response from backend service"}, 502


def proxy_request(service, path, method="GET", **kwargs):
    result, status = forward_request(service, path, method, **kwargs)
    if not 200 <= status < 300:
        detail = (
            result.get("detail", "Backend request failed")
            if isinstance(result, dict)
            else "Backend request failed"
        )
        raise HTTPException(status, detail)
    return result


def decode_token(token):
    return jwt.decode(
        token, JWT_SECRET, algorithms=["HS256"], options={"require": ["exp", "sub"]}
    )


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Authorization header missing")
    try:
        return decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc


def verify_enrollment(x_agent_secret: str = Header(default="")):
    expected = os.getenv("AGENT_SECRET", "")
    if not expected:
        raise HTTPException(503, "Enrollment is not configured")
    if not secrets.compare_digest(x_agent_secret.encode(), expected.encode()):
        raise HTTPException(401, "Invalid enrollment secret")


def verify_agent(
    x_agent_id: str = Header(default=""), x_agent_token: str = Header(default="")
):
    if not x_agent_id or not x_agent_token:
        raise HTTPException(401, "Agent identity and credential required")
    return proxy_request(
        DISCOVERY_SERVICE,
        "/authenticate",
        "POST",
        data={"agent_id": x_agent_id, "credential": x_agent_token},
    )


async def json_object(request):
    try:
        data = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "A JSON object is required") from exc
    if not isinstance(data, dict):
        raise HTTPException(400, "A JSON object is required")
    return data


def check_login_limit(request, username):
    key = (request.client.host if request.client else "unknown", str(username)[:100])
    now = time.monotonic()
    with login_lock:
        expired = [
            key
            for key, values in login_attempts.items()
            if not values or values[-1] < now - 60
        ]
        for expired_key in expired:
            login_attempts.pop(expired_key, None)
        if key not in login_attempts and len(login_attempts) >= 1000:
            raise HTTPException(429, "Too many login requests")
        attempts = [stamp for stamp in login_attempts.get(key, []) if stamp > now - 60]
        if len(attempts) >= 10:
            raise HTTPException(429, "Too many login attempts; wait one minute")
        login_attempts[key] = attempts + [now]


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/readiness")
@app.get("/api/readiness")
def readiness():
    for service in (AUTH_SERVICE, TOKEN_SERVICE, EVENT_SERVICE, DISCOVERY_SERVICE):
        proxy_request(service, "/health")
    return {"status": "ok"}


# Root aliases keep internal clients compatible with the public /api/ routes.
@app.post("/login")
@app.post("/api/login")
async def login(request: Request):
    data = await json_object(request)
    check_login_limit(request, data.get("username", ""))
    return await run_in_threadpool(
        proxy_request, AUTH_SERVICE, "/login", "POST", data=data
    )


@app.post("/generate")
@app.post("/api/generate")
async def generate(request: Request, _: dict = Depends(verify_token)):
    data = await json_object(request)
    if generation_limit.locked():
        raise HTTPException(429, "Generation capacity exceeded; try again later")
    async with generation_limit:
        return await run_in_threadpool(
            proxy_request,
            TOKEN_SERVICE,
            "/generate",
            "POST",
            data=data,
            timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "180")) + 15,
        )


@app.get("/events")
@app.get("/api/events")
def events(_: dict = Depends(verify_token)):
    return proxy_request(EVENT_SERVICE, "/events")


@app.get("/events/unread_count")
@app.get("/api/events/unread_count")
def events_unread_count(_: dict = Depends(verify_token)):
    return proxy_request(EVENT_SERVICE, "/events/unread_count")


@app.put("/events/{event_id}/read")
@app.put("/api/events/{event_id}/read")
def event_mark_read(event_id: int, _: dict = Depends(verify_token)):
    return proxy_request(EVENT_SERVICE, f"/events/{event_id}/read", "PUT")


@app.put("/events/read_all")
@app.put("/api/events/read_all")
def events_mark_all_read(_: dict = Depends(verify_token)):
    return proxy_request(EVENT_SERVICE, "/events/read_all", "PUT")


@app.get("/tokens")
@app.get("/api/tokens")
def tokens(_: dict = Depends(verify_token)):
    return proxy_request(TOKEN_SERVICE, "/tokens")


@app.get("/token-types")
@app.get("/api/token-types")
def token_types(_: dict = Depends(verify_token)):
    return proxy_request(TOKEN_SERVICE, "/token-types")


@app.get("/nodes")
@app.get("/api/nodes")
def nodes(_: dict = Depends(verify_token)):
    return proxy_request(DISCOVERY_SERVICE, "/nodes")


@app.post("/register")
@app.post("/api/register")
async def register_node(request: Request, _: None = Depends(verify_enrollment)):
    data = await json_object(request)
    return await run_in_threadpool(
        proxy_request, DISCOVERY_SERVICE, "/register", "POST", data=data
    )


@app.get("/agent/tasks")
@app.get("/api/agent/tasks")
def agent_tasks(node_id: int, agent: dict = Depends(verify_agent)):
    if node_id != agent["node_id"]:
        raise HTTPException(403, "Cannot access another node")
    return proxy_request(TOKEN_SERVICE, f"/agent/tasks?node_id={node_id}")


@app.put("/agent/tasks/{task_id}/result")
@app.put("/api/agent/tasks/{task_id}/result")
def agent_task_result(task_id: int, data: dict, agent: dict = Depends(verify_agent)):
    if data.get("node_id") != agent["node_id"]:
        raise HTTPException(403, "Cannot report results for another node")
    return proxy_request(
        TOKEN_SERVICE, f"/agent/tasks/{task_id}/result", "PUT", data=data
    )


@app.post("/agent/event")
@app.post("/api/agent/event")
@app.post("/event")
@app.post("/api/event")
def agent_event(data: dict, agent: dict = Depends(verify_agent)):
    # Neither the node nor hostname is trusted from an agent's event payload.
    payload = {
        **data,
        "node_id": agent["node_id"],
        "source_hostname": agent["hostname"],
    }
    return proxy_request(EVENT_SERVICE, "/event", "POST", data=payload)


@app.post("/admins")
@app.post("/api/admins")
def create_admin(data: dict = Body(default=None), _: dict = Depends(verify_token)):
    payload = {
        key: value
        for key, value in (data or {}).items()
        if key in ("username", "password")
    }
    payload["_secret"] = os.getenv("ADMIN_SECRET", "")
    return proxy_request(AUTH_SERVICE, "/admins", "POST", data=payload)


@app.post("/scan")
@app.post("/api/scan")
def scan(data: dict, _: dict = Depends(verify_token)):
    return proxy_request(DISCOVERY_SERVICE, "/scan", "POST", data=data, timeout=20)


@app.put("/password")
@app.put("/api/password")
def change_password(data: dict, user: dict = Depends(verify_token)):
    payload = {
        "_admin_id": user["sub"],
        "current_password": data.get("current_password"),
        "new_password": data.get("new_password"),
    }
    return proxy_request(AUTH_SERVICE, "/password", "PUT", data=payload)


@app.get("/generation-status")
@app.get("/api/generation-status")
def generation_status(_: dict = Depends(verify_token)):
    return proxy_request(TOKEN_SERVICE, "/generation-status")


@app.post("/tokens/{token_id}/retry")
@app.post("/api/tokens/{token_id}/retry")
def retry(token_id: str, _: dict = Depends(verify_token)):
    return proxy_request(TOKEN_SERVICE, f"/tokens/{token_id}/retry", "POST", data={})


@app.websocket("/ws/events")
async def websocket_proxy(websocket: WebSocket):
    protocols = websocket.scope.get("subprotocols", [])
    try:
        token_protocol = next(
            protocol for protocol in protocols if protocol.startswith("bearer.")
        )
        claims = decode_token(token_protocol[7:])
    except (StopIteration, jwt.PyJWTError):
        await websocket.close(code=1008)
        return
    await websocket.accept(
        subprotocol="luregenix" if "luregenix" in protocols else token_protocol
    )
    try:
        async with websockets.connect(EVENT_WS_URL) as backend:

            async def receive():
                try:
                    while True:
                        await backend.send(await websocket.receive_text())
                except WebSocketDisconnect:
                    pass

            async def send():
                async for message in backend:
                    await websocket.send_text(message)

            tasks = {asyncio.create_task(receive()), asyncio.create_task(send())}
            try:
                done, _ = await asyncio.wait(
                    tasks,
                    timeout=max(0, claims["exp"] - time.time()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    task.result()
                if not done:
                    await websocket.close(code=1008, reason="Session expired")
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, websockets.WebSocketException, WebSocketDisconnect, RuntimeError):
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=1011, reason="Notification service unavailable")
