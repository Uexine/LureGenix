from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import requests
import os

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

def forward_request(service_url: str, path: str, method: str, data=None, headers=None):
    """Универсальная функция для проксирования запросов."""
    try:
        if method == "GET":
            resp = requests.get(f"{service_url}{path}", headers=headers, timeout=5)
        elif method == "POST":
            resp = requests.post(f"{service_url}{path}", json=data, headers=headers, timeout=5)
        else:
            raise HTTPException(status_code=405, detail="Method not allowed")
        
        # Возвращаем ответ как есть
        return resp.json() if resp.content else {}, resp.status_code
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")

# ---------- LOGIN ----------
@app.post("/login")
@app.post("/api/login")
async def login(data: dict):
    # Просто проксируем запрос к auth_service
    result, status = forward_request(AUTH_SERVICE, "/login", "POST", data=data)
    if status != 200:
        raise HTTPException(status_code=status, detail=result)
    return result

# ---------- GENERATE (без проверки токена) ----------
@app.post("/generate")
@app.post("/api/generate")
async def generate(data: dict):
    result, status = forward_request(TOKEN_SERVICE, "/generate", "POST", data=data)
    return result

# ---------- EVENTS ----------
@app.post("/event")
@app.post("/api/event")
async def event(data: dict):
    result, status = forward_request(EVENT_SERVICE, "/event", "POST", data=data)
    return result

@app.get("/events")
@app.get("/api/events")
async def events():
    result, status = forward_request(EVENT_SERVICE, "/events", "GET")
    return result

# ---------- TOKENS (список сгенерированных) ----------
@app.get("/tokens")
@app.get("/api/tokens")
async def tokens():
    result, status = forward_request(TOKEN_SERVICE, "/tokens", "GET")
    return result

# ---------- NODES ----------
@app.get("/nodes")
@app.get("/api/nodes")
async def nodes():
    # Заглушка для тестирования
    return [{"id": 1, "hostname": "agent1", "ip": "127.0.0.1"}]