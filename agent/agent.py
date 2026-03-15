"""
Агент ноды: отправляет heartbeat и события компрометации приманок в event_service.
В распределённой сети агент может запускаться на каждой ноде с honeytoken'ами.
"""
import requests
import time
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8000")
NODE_ID = os.getenv("NODE_ID", "1")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "60"))


def send_event(token_id: str, action: str, file_path: str = ""):
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/event",
            json={
                "token_id": token_id,
                "action": action,
                "file_path": file_path or "",
            },
            timeout=5,
        )
        if resp.status_code != 200:
            logger.error("Event failed %s: %s", resp.status_code, resp.text)
        else:
            logger.info("Event sent: %s %s", action, token_id)
    except Exception as e:
        logger.error("Error sending event: %s", e)


def send_heartbeat(token_id: str = "agent_node"):
    send_event(token_id, "heartbeat", "")


def send_compromise(token_id: str, file_path: str = ""):
    """Вызвать при обнаружении использования приманки (например, доступ к файлу)."""
    send_event(token_id, "alert", file_path)


def register():
    """Регистрация ноды при старте (появляется в списке нод в админке)."""
    try:
        hostname = os.getenv("NODE_HOSTNAME", f"agent{NODE_ID}")
        ip = os.getenv("NODE_IP", "127.0.0.1")
        resp = requests.post(
            f"{GATEWAY_URL}/register",
            json={"hostname": hostname, "ip": ip},
            timeout=5,
        )
        if resp.status_code == 200:
            logger.info("Node registered: %s (%s)", hostname, ip)
    except Exception as e:
        logger.warning("Register failed: %s", e)


if __name__ == "__main__":
    logger.info("Agent started, node_id=%s", NODE_ID)
    register()
    while True:
        send_heartbeat(f"node_{NODE_ID}")
        time.sleep(HEARTBEAT_INTERVAL)
