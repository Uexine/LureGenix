"""Transactional, idempotent security-event storage and live notifications."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager, closing, suppress
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg2
from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from common.database import connect as get_db
from common.database import utc_timestamp


@asynccontextmanager
async def lifespan(app):
    await run_in_threadpool(cleanup_old_events)
    task = asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
logger = logging.getLogger(__name__)
ws_subscribers = []
EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "30"))


def event_row(row):
    return dict(
        zip(
            (
                "id",
                "token_id",
                "action",
                "file_path",
                "created_at",
                "source_hostname",
                "read_at",
                "event_id",
                "node_id",
                "observed_at",
            ),
            [utc_timestamp(value) for value in row],
        )
    )


FIELDS = "id,token_id,action,file_path,created_at,source_hostname,read_at,event_id,node_id,observed_at"


class Event(BaseModel):
    event_id: UUID
    node_id: int = Field(gt=0)
    token_id: str = Field(min_length=1, max_length=100)
    action: Literal[
        "open",
        "access",
        "modify",
        "delete",
        "deployed",
        "deployment_failed",
        "monitor_error",
    ]
    file_path: str = Field(default="", max_length=4096)
    source_hostname: str = Field(default="", max_length=255)
    observed_at: datetime | None = None


@app.get("/health")
def health():
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/event")
def add_event(data: Event, background_tasks: BackgroundTasks):
    try:
        with closing(get_db()) as conn, conn, conn.cursor() as cur:
            if not (
                data.action == "monitor_error"
                and data.token_id == f"node_{data.node_id}"
            ):
                cur.execute(
                    "SELECT id FROM honeytoken_deployments WHERE token_id=%s AND node_id=%s",
                    (data.token_id, data.node_id),
                )
                if cur.fetchone() is None:
                    raise HTTPException(403, "Token does not belong to this node")
            cur.execute(
                f"INSERT INTO event_log(event_id,node_id,token_id,action,file_path,source_hostname,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (event_id) WHERE event_id IS NOT NULL DO NOTHING RETURNING {FIELDS}",
                (
                    str(data.event_id),
                    data.node_id,
                    data.token_id,
                    data.action,
                    data.file_path,
                    data.source_hostname,
                    data.observed_at,
                ),
            )
            row = cur.fetchone()
            created = row is not None
            if not created:
                cur.execute(
                    f"SELECT {FIELDS} FROM event_log WHERE event_id=%s",
                    (str(data.event_id),),
                )
                row = cur.fetchone()
                if (
                    not row
                    or row[8] != data.node_id
                    or row[1:4] != (data.token_id, data.action, data.file_path)
                ):
                    raise HTTPException(
                        409, "Event identifier conflicts with another event"
                    )
            if created:
                integrity = {
                    "deployed": "intact",
                    "modify": "modified",
                    "delete": "missing",
                    "monitor_error": "error",
                    "deployment_failed": "error",
                }.get(data.action)
                cur.execute(
                    "UPDATE honeytoken_deployments SET last_event_at=now(), integrity_status=COALESCE(%s,integrity_status) WHERE token_id=%s AND node_id=%s",
                    (integrity, data.token_id, data.node_id),
                )
        result = event_row(row)
        if created:
            background_tasks.add_task(broadcast_event, result)
        return {"status": "ok", "event": result}
    except psycopg2.Error as exc:
        logger.error("Event storage failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Event storage unavailable") from exc


async def broadcast_event(event):
    for subscriber in list(ws_subscribers):
        try:
            await asyncio.wait_for(subscriber.send_text(json.dumps(event)), timeout=2)
        except Exception:
            if subscriber in ws_subscribers:
                ws_subscribers.remove(subscriber)


@app.get("/events")
def events():
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {FIELDS} FROM event_log WHERE action <> 'heartbeat' ORDER BY id DESC LIMIT 500"
        )
        return [event_row(row) for row in cur.fetchall()]


@app.get("/events/unread_count")
def events_unread_count():
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM event_log WHERE read_at IS NULL AND action IN ('open','access','modify','delete','monitor_error','deployment_failed')"
        )
        return {"count": cur.fetchone()[0]}


@app.put("/events/{event_id}/read")
def event_mark_read(event_id: int):
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE event_log SET read_at=COALESCE(read_at,now()) WHERE id=%s RETURNING id",
            (event_id,),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Event not found")
    return {"status": "ok"}


@app.put("/events/read_all")
def events_mark_all_read():
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute("UPDATE event_log SET read_at=now() WHERE read_at IS NULL")
    return {"status": "ok"}


def cleanup_old_events():
    if EVENT_RETENTION_DAYS > 0:
        try:
            with closing(get_db()) as conn, conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM event_log WHERE created_at < now() - %s * interval '1 day'",
                    (EVENT_RETENTION_DAYS,),
                )
        except psycopg2.Error:
            logger.warning("Event retention cleanup unavailable")


async def retention_loop():
    while True:
        await asyncio.sleep(3600)
        await run_in_threadpool(cleanup_old_events)


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
