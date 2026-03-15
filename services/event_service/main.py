from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import os
import json

app = FastAPI()
EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "30"))

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

ws_subscribers: list[WebSocket] = []

# Используем event_log (token_id, action, file_path) для совместимости с агентом и фронтом
EVENT_LOG_TABLE = "event_log"

def _event_row_from_row(row, num_cols):
    """Собираем dict события из строки (поддержка старых БД без source_hostname/read_at)."""
    e = {
        "id": row[0],
        "token_id": row[1] or "",
        "action": row[2] or "",
        "file_path": row[3] or "",
        "created_at": row[4].isoformat() if row[4] else None,
    }
    if num_cols >= 7:
        e["source_hostname"] = row[5] if row[5] else ""
        e["read_at"] = row[6].isoformat() if row[6] else None
    elif num_cols >= 6:
        e["source_hostname"] = row[5] if row[5] else ""
        e["read_at"] = None
    else:
        e["source_hostname"] = ""
        e["read_at"] = None
    return e


@app.post("/event")
def add_event(data: dict, background_tasks: BackgroundTasks):
    try:
        conn = get_db()
        cur = conn.cursor()
        token_id = data.get("token_id") or ""
        action = data.get("action") or "event"
        file_path = data.get("file_path") or ""
        source_hostname = (data.get("source_hostname") or "").strip()[:255]
        try:
            cur.execute(
                f"INSERT INTO {EVENT_LOG_TABLE}(token_id, action, file_path, source_hostname) VALUES(%s,%s,%s,%s) RETURNING id, token_id, action, file_path, created_at, source_hostname",
                (token_id, action, file_path, source_hostname or None),
            )
            row = cur.fetchone()
            event_row = {
                "id": row[0],
                "token_id": row[1] or "",
                "action": row[2] or "",
                "file_path": row[3] or "",
                "created_at": row[4].isoformat() if row[4] else None,
                "source_hostname": row[5] if len(row) > 5 and row[5] else "",
                "read_at": None,
            }
        except psycopg2.Error:
            cur.execute(
                f"INSERT INTO {EVENT_LOG_TABLE}(token_id, action, file_path) VALUES(%s,%s,%s) RETURNING id, token_id, action, file_path, created_at",
                (token_id, action, file_path),
            )
            row = cur.fetchone()
            event_row = {
                "id": row[0],
                "token_id": row[1] or "",
                "action": row[2] or "",
                "file_path": row[3] or "",
                "created_at": row[4].isoformat() if row[4] else None,
                "source_hostname": "",
                "read_at": None,
            }
        conn.commit()
        cur.close()
        conn.close()
        background_tasks.add_task(broadcast_event, event_row)
        return {"status": "ok", "event": event_row}
    except Exception as e:
        print(f"event_service add_event error: {e}")
        return {"status": "error", "detail": str(e)}


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
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                f"SELECT id, token_id, action, file_path, created_at, source_hostname, read_at FROM {EVENT_LOG_TABLE} ORDER BY id DESC LIMIT 200"
            )
        except psycopg2.Error:
            cur.execute(
                f"SELECT id, token_id, action, file_path, created_at FROM {EVENT_LOG_TABLE} ORDER BY id DESC LIMIT 200"
            )
        rows = cur.fetchall()
        num_cols = len(rows[0]) if rows else 0
        cur.close()
        conn.close()
        return [_event_row_from_row(r, num_cols) for r in rows]
    except Exception as e:
        print(f"event_service events error: {e}")
        return []


@app.get("/events/unread_count")
def events_unread_count():
    """Количество непрочитанных событий (для бейджа)."""
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                f"SELECT COUNT(*) FROM {EVENT_LOG_TABLE} WHERE read_at IS NULL"
            )
        except psycopg2.Error:
            cur.execute(f"SELECT COUNT(*) FROM {EVENT_LOG_TABLE}")
        n = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {"count": n}
    except Exception as e:
        print(f"event_service unread_count error: {e}")
        return {"count": 0}


@app.put("/events/{event_id}/read")
def event_mark_read(event_id: int):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            f"UPDATE {EVENT_LOG_TABLE} SET read_at = now() WHERE id = %s",
            (event_id,),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        print(f"event_service mark_read error: {e}")
        return {"status": "error", "detail": str(e)}


@app.put("/events/read_all")
def events_mark_all_read():
    try:
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(f"UPDATE {EVENT_LOG_TABLE} SET read_at = now() WHERE read_at IS NULL")
        except psycopg2.Error:
            pass
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        print(f"event_service mark_all_read error: {e}")
        return {"status": "error", "detail": str(e)}


def cleanup_old_events():
    """Удаление событий старше EVENT_RETENTION_DAYS."""
    if EVENT_RETENTION_DAYS <= 0:
        return
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM {EVENT_LOG_TABLE} WHERE created_at < now() - (%s || ' days')::interval",
            (EVENT_RETENTION_DAYS,),
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if deleted:
            print(f"event_service cleanup: deleted {deleted} old events")
    except Exception as e:
        print(f"event_service cleanup error: {e}")


@app.on_event("startup")
async def startup_cleanup():
    def run():
        import time
        while True:
            time.sleep(3600)
            cleanup_old_events()

    import threading
    threading.Thread(target=run, daemon=True).start()
    cleanup_old_events()


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
