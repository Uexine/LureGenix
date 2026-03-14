from fastapi import FastAPI
import requests

app = FastAPI()


@app.post("/login")
def login(data: dict):

    r = requests.post(
        "http://auth_service:8000/login",
        json=data
    )

    if r.status_code != 200:
        return {"error": "invalid"}

    return r.json()
