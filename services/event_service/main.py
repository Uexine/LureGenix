from fastapi import FastAPI, WebSocket
import psycopg2
import os
from typing import List

app = FastAPI()

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin")
    )

@app.post("/event")
def create_event(data: dict):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO events(token_id, action, file_path) VALUES(%s, %s, %s)",
        (data.get("token_id"), data.get("description", "heartbeat"), data.get("file_path", ""))
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "saved"}

@app.get("/events")
def get_events() -> List[dict]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 50")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "token_id": r[1], "action": r[2], "file_path": r[3], "created_at": r[4]} for r in rows]

@app.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()  # Или poll DB for new events
        await websocket.send_text(f"Event: {data}")