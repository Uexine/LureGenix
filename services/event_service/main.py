from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import psycopg2
import os
from typing import List, Dict

app = FastAPI()

# Хранилище активных WebSocket-соединений
active_connections: List[WebSocket] = []

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin")
    )

async def broadcast_event(message: str):
    """Отправить сообщение всем подключённым клиентам."""
    for connection in active_connections:
        try:
            await connection.send_text(message)
        except:
            pass  # Если соединение оборвалось, оно отвалится само

@app.post("/event")
async def create_event(data: dict):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO events(token_id, action, file_path) VALUES(%s, %s, %s)",
        (data.get("token_id"), data.get("action", "heartbeat"), data.get("file_path", ""))
    )
    conn.commit()
    cur.close()
    conn.close()
    
    # Оповещаем всех через WebSocket
    await broadcast_event(f"New event: {data.get('action')} for token {data.get('token_id')}")
    
    return {"status": "saved"}

@app.get("/events")
def get_events() -> List[Dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, token_id, action, file_path, created_at FROM events ORDER BY created_at DESC LIMIT 50")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "token_id": r[1], "action": r[2], "file_path": r[3], "created_at": r[4]} for r in rows]

@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            # Ждём сообщения от клиента (необязательно)
            data = await websocket.receive_text()
            # Можно просто игнорировать или эхо
            # await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        active_connections.remove(websocket)