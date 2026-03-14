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


# ---------- LOGIN ----------

@app.post("/login")
@app.post("/api/login")
async def login(data: dict):

    r = requests.post(
        f"{AUTH_SERVICE}/login",
        json=data,
        timeout=5
    )

    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    return r.json()


# ---------- TOKEN GENERATION ----------

@app.post("/generate")
@app.post("/api/generate")
async def generate(request: Request, data: dict):

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)

    r = requests.post(
        f"{TOKEN_SERVICE}/generate",
        json=data,
        timeout=5
    )

    return r.json()


# ---------- EVENTS ----------

@app.post("/event")
@app.post("/api/event")
async def event(data: dict):

    r = requests.post(
        f"{EVENT_SERVICE}/event",
        json=data,
        timeout=5
    )

    return r.json()


@app.get("/events")
@app.get("/api/events")
async def events(request: Request):

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)

    r = requests.get(
        f"{EVENT_SERVICE}/events",
        timeout=5
    )

    return r.json()


# ---------- NODES ----------

@app.get("/nodes")
@app.get("/api/nodes")
async def nodes(request: Request):

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)

    return [
        {"id": 1, "hostname": "agent1", "ip": "127.0.0.1"}
    ]


# ---------- TOKENS ----------

@app.get("/tokens")
@app.get("/api/tokens")
async def tokens(request: Request):

    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)

    return [
        {"id": "demo", "type": "txt", "path": "/tokens/demo.txt"}
    ]
