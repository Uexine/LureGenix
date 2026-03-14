from fastapi import FastAPI, HTTPException, Request
import requests
from jose import jwt, JWTError
import os

app = FastAPI()

SECRET = os.getenv("JWT_SECRET")

def validate_token(token: str):
    try:
        jwt.decode(token, SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/api/login")
def login(data: dict):
    r = requests.post("http://auth_service:8000/login", json=data)

    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)

    return r.json()


@app.post("/api/generate")
async def generate(request: Request, data: dict):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)

    r = requests.post("http://honeytoken_service:8000/generate", json=data)

    return r.json()


@app.post("/api/event")
def event(data: dict):
    r = requests.post("http://event_service:8000/event", json=data)
    return r.json()


@app.get("/api/events")
async def get_events(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)

    r = requests.get("http://event_service:8000/events")
    return r.json()


@app.get("/api/nodes")
async def get_nodes(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)

    return [{"id": 1, "hostname": "agent1", "ip": "172.17.0.1"}]


@app.get("/api/tokens")
async def get_tokens(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    validate_token(token)

    return [{"id": "demo", "type": "txt", "path": "/tokens/demo.txt"}]
