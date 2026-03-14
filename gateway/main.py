from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import requests
from jose import jwt, JWTError
import os

app = FastAPI()

SECRET = os.getenv("JWT_SECRET", "changeme")

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

def validate_token(token: str):
    try:
        jwt.decode(token, SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def forward_request(service_url: str, path: str, method: str, data=None, headers=None):
    """Универсальная функция для проксирования запросов."""
    try:
        if method == "GET":
            resp = requests.get(f"{service_url}{path}", headers=headers, timeout=5)
        elif method == "POST":
            resp = requests.post(f"{service_url}{path}", json=data, headers=headers, timeout=5)
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")
        return resp.json(), resp.status_code
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")

# ---------- LOGIN (не требует токена) ----------
@app.post("/login")
@app.post("/api/login")
async def login(data: dict):
    result, status = forward_request(AUTH_SERVICE, "/login", "POST", data=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- GENERATE (требует токен) ----------
@app.post("/generate")
@app.post("/api/generate")
async def generate(request: Request, data: dict):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)
    result, status = forward_request(TOKEN_SERVICE, "/generate", "POST", data=data)
    return result

# ---------- EVENTS ----------
@app.post("/event")
@app.post("/api/event")
async def event(data: dict):
    # События могут приходить от агентов без токена (или с токеном, но пока без проверки)
    result, status = forward_request(EVENT_SERVICE, "/event", "POST", data=data)
    return result

@app.get("/events")
@app.get("/api/events")
async def events(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)
    result, status = forward_request(EVENT_SERVICE, "/events", "GET")
    return result

# ---------- TOKENS (список сгенерированных) ----------
@app.get("/tokens")
@app.get("/api/tokens")
async def tokens(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)
    result, status = forward_request(TOKEN_SERVICE, "/tokens", "GET")
    return result

# ---------- NODES (заглушка, можно заменить реальными данными) ----------
@app.get("/nodes")
@app.get("/api/nodes")
async def nodes(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)
    # Здесь можно получать список узлов из БД или другого сервиса
    return [{"id": 1, "hostname": "agent1", "ip": "127.0.0.1"}]