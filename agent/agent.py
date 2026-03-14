import requests
import time

while True:
    requests.post("http://gateway:8000/event", json={"token_id": "demo_token_id", "action": "heartbeat"})
    time.sleep(60)