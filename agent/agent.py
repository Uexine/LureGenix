"""
Агент ноды: регистрируется в discovery, отправляет heartbeat и события компрометации.
При обнаружении доступа к файлу-приманке вызывайте send_compromise(token_id, file_path).
"""
import requests
import time
import logging
import os
import socket

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8000")
NODE_ID = os.getenv("NODE_ID", "1")
NODE_HOSTNAME = os.getenv("NODE_HOSTNAME") or socket.gethostname() or f"agent{NODE_ID}"
NODE_IP = os.getenv("NODE_IP", "127.0.0.1")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "60"))


def register_node():
    """Регистрация ноды в discovery_service (через gateway)."""
    try:
        r = requests.post(
            f"{GATEWAY_URL}/api/register",
            json={"hostname": NODE_HOSTNAME, "ip": NODE_IP},
            timeout=5,
        )
        if r.status_code in (200, 201):
            logger.info("Node registered: %s (%s)", NODE_HOSTNAME, NODE_IP)
        else:
            logger.warning("Register %s: %s", r.status_code, r.text)
    except Exception as e:
        logger.warning("Register failed: %s", e)


def send_event(token_id: str, action: str, file_path: str = "", source_hostname: str = ""):
    """Отправка события в event_service (heartbeat, alert при компрометации)."""
    try:
        r = requests.post(
            f"{GATEWAY_URL}/event",
            json={
                "token_id": token_id,
                "action": action,
                "file_path": file_path or "",
                "source_hostname": source_hostname or NODE_HOSTNAME,
            },
            timeout=5,
        )
        if r.status_code != 200:
            logger.error("Event failed %s: %s", r.status_code, r.text)
        else:
            logger.info("Event sent: %s %s", action, token_id)
    except Exception as e:
        logger.error("Error sending event: %s", e)


def send_heartbeat(token_id: str = ""):
    send_event(token_id or f"node_{NODE_ID}", "heartbeat", "")


def send_compromise(token_id: str, file_path: str = ""):
    """
    Вызвать при обнаружении использования приманки (доступ к файлу, использование ключа).
    На дашборде появится тревога и уведомление.
    """
    send_event(token_id, "alert", file_path)


if __name__ == "__main__":
    logger.info("Agent starting: node_id=%s hostname=%s", NODE_ID, NODE_HOSTNAME)
    register_node()
    while True:
        send_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)
