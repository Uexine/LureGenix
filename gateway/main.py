from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, HTTPHeader
import requests
import os
from jose import jwt, JWTError

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
        return resp.json() if resp.content else {}, resp.status_code
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------- LOGIN (публичный) ----------
@app.post("/login")
@app.post("/api/login")
async def login(data: dict):
    result, status = forward_request(AUTH_SERVICE, "/login", "POST", data=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- GENERATE (требуется JWT) ----------
@app.post("/generate")
@app.post("/api/generate")
async def generate(data: dict, _: dict = Depends(verify_token)):
    result, status = forward_request(TOKEN_SERVICE, "/generate", "POST", data=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- EVENTS ----------
@app.post("/event")
@app.post("/api/event")
async def event(data: dict):
    result, status = forward_request(EVENT_SERVICE, "/event", "POST", data=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

@app.get("/events")
@app.get("/api/events")
async def events(_: dict = Depends(verify_token)):
    result, status = forward_request(EVENT_SERVICE, "/events", "GET")
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- TOKENS ----------
@app.get("/tokens")
@app.get("/api/tokens")
async def tokens(_: dict = Depends(verify_token)):
    result, status = forward_request(TOKEN_SERVICE, "/tokens", "GET")
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- NODES ----------
@app.get("/nodes")
@app.get("/api/nodes")
async def nodes(_: dict = Depends(verify_token)):
    return [{"id": 1, "hostname": "agent1", "ip": "127.0.0.1"}]

# ---------- CREATE ADMIN (требуется JWT + ADMIN_SECRET в env) ----------
@app.post("/api/admins")
async def create_admin(data: dict, _: dict = Depends(verify_token)):
    admin_secret = os.getenv("ADMIN_SECRET", "")
    payload = {k: v for k, v in data.items() if k in ("username", "password")}
    if admin_secret:
        payload["_secret"] = admin_secret
    result, status = forward_request(AUTH_SERVICE, "/admins", "POST", data=payload)
    if status not in (200, 201):
        raise HTTPException(status_code=status, detail=result)
    return result
