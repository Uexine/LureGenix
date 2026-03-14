import requests
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GATEWAY_URL = "http://gateway:8000"

def send_heartbeat(token_id="demo_token_id"):
    try:
        resp = requests.post(f"{GATEWAY_URL}/event", json={
            "token_id": token_id,
            "action": "heartbeat"
        }, timeout=5)
        if resp.status_code != 200:
            logger.error(f"Failed to send heartbeat: {resp.text}")
    except Exception as e:
        logger.error(f"Error sending heartbeat: {e}")

if __name__ == "__main__":
    while True:
        send_heartbeat()
        time.sleep(60)