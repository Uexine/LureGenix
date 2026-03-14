from fastapi import FastAPI, HTTPException, Request
import requests
from jose import jwt, JWTError
import os

app = FastAPI()

SECRET = os.getenv("JWT_SECRET", "luregenix_secret")
AUTH = "http://auth_service:8000"
TOKEN = "http://honeytoken_service:8000"
EVENT = "http://event_service:8000"

def validate_token(token: str):
    try:
        jwt.decode(token, SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "Invalid token")

@app.post("/login")
def login(data: dict):
    r = requests.post(AUTH + "/login", json=data)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code)
    return r.json()

@app.post("/generate")
async def generate(request: Request, data: dict):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)
    r = requests.post(TOKEN + "/generate", json=data)
    return r.json()

@app.post("/event")
def event(data: dict):
    r = requests.post(EVENT + "/event", json=data)
    return r.json()

@app.get("/events")
async def get_events(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)
    r = requests.get(EVENT + "/events")
    return r.json()

@app.get("/nodes")
async def get_nodes(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)
    return [{"id": 1, "hostname": "agent1", "ip": "172.17.0.1"}]

@app.get("/tokens")
async def get_tokens(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)
    return [{"id": "demo", "type": "txt", "path": "/tokens/demo.txt"}]  # Dummy, TODO: from DB