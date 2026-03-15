from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import os
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

# Подписчики WebSocket для рассылки событий
ws_subscribers: list[WebSocket] = []

@app.post("/event")
def add_event(data: dict, background_tasks: BackgroundTasks):
    conn = get_db()
    cur = conn.cursor()
    token_id = data.get("token_id") or ""
    action = data.get("action") or "event"
    file_path = data.get("file_path") or ""
    cur.execute(
        "INSERT INTO events(token_id, action, file_path) VALUES(%s,%s,%s) RETURNING id, token_id, action, file_path, created_at",
        (token_id, action, file_path),
    )
    row = cur.fetchone()
    conn.commit()
    event_row = {
        "id": row[0],
        "token_id": row[1],
        "action": row[2],
        "file_path": row[3],
        "created_at": row[4].isoformat() if row[4] else None,
    }
    cur.close()
    conn.close()
    background_tasks.add_task(broadcast_event, event_row)
    return {"status": "ok", "event": event_row}


async def broadcast_event(event: dict):
    dead = []
    for ws in ws_subscribers:
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_subscribers:
            ws_subscribers.remove(ws)


@app.get("/events")
def events():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, token_id, action, file_path, created_at FROM events ORDER BY id DESC LIMIT 200"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0],
            "token_id": r[1] or "",
            "action": r[2] or "",
            "file_path": r[3] or "",
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    ws_subscribers.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in ws_subscribers:
            ws_subscribers.remove(websocket)
