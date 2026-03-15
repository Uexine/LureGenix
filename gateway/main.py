from fastapi import FastAPI, HTTPException, Depends, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import requests
import os
import jwt

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUTH_SERVICE = "http://auth_service:8000"
EVENT_SERVICE = "http://event_service:8000"
TOKEN_SERVICE = "http://honeytoken_service:8000"
DISCOVERY_SERVICE = "http://discovery_service:8000"
JWT_SECRET = os.getenv("JWT_SECRET", "temp_secret_key_for_testing")
security = HTTPBearer(auto_error=False)


def forward_request(service_url: str, path: str, method: str, data=None, headers=None):
    try:
        if method == "GET":
            resp = requests.get(f"{service_url}{path}", headers=headers, timeout=5)
        elif method == "POST":
            resp = requests.post(f"{service_url}{path}", json=data, headers=headers, timeout=5)
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")
        if not resp.content:
            return {}, resp.status_code
        try:
            return resp.json(), resp.status_code
        except ValueError:
            return {"detail": "Invalid JSON from upstream"}, resp.status_code
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_exp": True},
        )
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------- HEALTH (для проверки готовности) ----------
@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------- LOGIN (публичный) ----------
@app.post("/login")
@app.post("/api/login")
async def login(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    result, status = forward_request(AUTH_SERVICE, "/login", "POST", data=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- GENERATE (требуется JWT) ----------
@app.post("/generate")
@app.post("/api/generate")
async def generate(request: Request, _: dict = Depends(verify_token)):
    try:
        data = await request.json()
    except Exception:
        data = {}
    result, status = forward_request(TOKEN_SERVICE, "/generate", "POST", data=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- EVENTS ----------
@app.post("/event")
@app.post("/api/event")
async def event(data: dict = Body(default=None)):
    if data is None:
        data = {}
    result, status = forward_request(EVENT_SERVICE, "/event", "POST", data=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

@app.get("/events")
@app.get("/api/events")
async def events(_: dict = Depends(verify_token)):
    try:
        result, status = forward_request(EVENT_SERVICE, "/events", "GET")
        if status != 200:
            return []
        return result if isinstance(result, list) else []
    except HTTPException:
        return []  # при недоступности event_service отдаём пустой список, чтобы дашборд не падал
    except Exception:
        return []

# ---------- TOKENS ----------
@app.get("/tokens")
@app.get("/api/tokens")
async def tokens(_: dict = Depends(verify_token)):
    result, status = forward_request(TOKEN_SERVICE, "/tokens", "GET")
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

@app.get("/token-types")
@app.get("/api/token-types")
async def token_types(_: dict = Depends(verify_token)):
    try:
        result, status = forward_request(TOKEN_SERVICE, "/token-types", "GET")
        if status == 200 and isinstance(result, list):
            return result
    except Exception:
        pass
    return [
        {"id": 1, "name": "ssh_key", "description": "Приватный SSH-ключ"},
        {"id": 2, "name": "env_file", "description": "Файл .env"},
        {"id": 3, "name": "api_key", "description": "Ключ API"},
        {"id": 4, "name": "password", "description": "Пароль"},
        {"id": 5, "name": "pdf", "description": "PDF"},
        {"id": 6, "name": "docx", "description": "Word"},
    ]

# ---------- NODES (из discovery_service или заглушка) ----------
@app.get("/nodes")
@app.get("/api/nodes")
async def nodes(_: dict = Depends(verify_token)):
    try:
        result, status = forward_request(DISCOVERY_SERVICE, "/nodes", "GET")
        if status == 200 and isinstance(result, list):
            return result if result else [{"id": 1, "hostname": "agent1", "ip": "127.0.0.1"}]
    except Exception:
        pass
    return [{"id": 1, "hostname": "agent1", "ip": "127.0.0.1"}]


@app.post("/api/register")
async def register_node(request: Request):
    """Регистрация ноды агентом (прокси в discovery_service)."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    result, status = forward_request(DISCOVERY_SERVICE, "/register", "POST", data=data)
    if status not in (200, 201):
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- CREATE ADMIN (требуется JWT + ADMIN_SECRET в env) ----------
@app.post("/api/admins")
async def create_admin(data: dict = Body(default=None), _: dict = Depends(verify_token)):
    if data is None:
        data = {}
    admin_secret = os.getenv("ADMIN_SECRET", "")
    payload = {k: v for k, v in data.items() if k in ("username", "password")}
    if admin_secret:
        payload["_secret"] = admin_secret
    result, status = forward_request(AUTH_SERVICE, "/admins", "POST", data=payload)
    if status not in (200, 201):
        raise HTTPException(status_code=status, detail=result)
    return result
