from fastapi import FastAPI, HTTPException
import requests

app = FastAPI()

AUTH = "http://auth_service:8000"
TOKEN = "http://honeytoken_service:8000"
EVENT = "http://event_service:8000"


@app.post("/login")
def login(data: dict):

    r = requests.post(AUTH + "/login", json=data)

    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code)

    return r.json()


@app.post("/generate")
def generate(data: dict):

    r = requests.post(TOKEN + "/generate", json=data)

    return r.json()


@app.post("/event")
def event(data: dict):

    r = requests.post(EVENT + "/event", json=data)

    return r.json()
