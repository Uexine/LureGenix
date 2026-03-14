import requests
import time

while True:

    requests.post(
        "http://gateway:8000/event",
        json={
            "token_id": "demo",
            "description": "agent heartbeat"
        }
    )

    time.sleep(30)
