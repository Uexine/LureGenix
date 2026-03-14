from fastapi import FastAPI, WebSocket
import requests

app = FastAPI()

AUTH = "http://auth_service:8000"
TOKEN = "http://honeytoken_service:8000"
EVENT = "http://event_service:8000"


@app.post("/login")
def login(data: dict):
    return requests.post(AUTH + "/login", json=data).json()


@app.post("/generate")
def generate(data: dict):
    return requests.post(TOKEN + "/generate", json=data).json()


@app.post("/event")
def event(data: dict):
    return requests.post(EVENT + "/event", json=data).json()


@app.websocket("/ws")
async def ws_proxy(ws: WebSocket):

    await ws.accept()

    async with requests.Session() as s:
        while True:
            data = await ws.receive_text()
            await ws.send_text(data)