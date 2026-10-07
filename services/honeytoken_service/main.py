import base64
import hashlib
import os
import posixpath
import uuid
from contextlib import closing
from typing import Literal

import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from generator import GenerationError, TOKEN_TYPES, generate_file

app = FastAPI()

DEPLOYMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS honeytoken_deployments (
    id SERIAL PRIMARY KEY,
    honeytoken_file_id INTEGER UNIQUE NOT NULL REFERENCES honeytoken_files(id) ON DELETE CASCADE,
    node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    token_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    target_path TEXT NOT NULL DEFAULT '',
    target_kind TEXT NOT NULL DEFAULT 'directory' CHECK (target_kind IN ('directory', 'file')),
    content_base64 TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    generation_source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'deployed', 'failed')),
    deployed_path TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT now(),
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_honeytoken_deployments_node_status
    ON honeytoken_deployments(node_id, status);
"""


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


@app.on_event("startup")
def ensure_schema():
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute(DEPLOYMENT_SCHEMA)


class GenerateRequest(BaseModel):
    node_id: int = Field(gt=0)
    type: str = "txt"
    name: str = Field(default="", max_length=200)
    filename: str = Field(default="", max_length=255)
    node_path: str = Field(default="", max_length=4096)
    target_kind: Literal["directory", "file"] = "directory"
    save_path: str = Field(default="", max_length=4096)


class DeploymentResult(BaseModel):
    node_id: int = Field(gt=0)
    status: Literal["deployed", "failed"]
    deployed_path: str = Field(default="", max_length=4096)
    error: str = Field(default="", max_length=1000)


def validate_target(path):
    if path and (not path.startswith("/") or path.startswith("//") or ".." in path.split("/") or "\x00" in path):
        raise HTTPException(status_code=400, detail="Specify an absolute Linux path without '..'")
    return posixpath.normpath(path) if path else ""


def validate_filename(filename):
    if not filename or filename in (".", "..") or any(c in filename for c in "/\\\x00\r\n"):
        raise HTTPException(status_code=400, detail="Filename must contain only a filename, without directories")
    return filename


@app.get("/token-types")
def token_types():
    return [{"id": index, "name": key, "description": value[0]} for index, (key, value) in enumerate(TOKEN_TYPES.items(), 1)]


@app.post("/generate")
def generate(data: GenerateRequest):
    token_type = {"env": "env_file", "sql": "db_dump"}.get(data.type.lower(), data.type.lower())
    if token_type not in TOKEN_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported honeytoken type")
    target = validate_target(data.node_path.strip() or data.save_path.strip())
    if data.target_kind == "file" and not target:
        raise HTTPException(status_code=400, detail="A full file path is required for target_kind=file")
    filename = validate_filename(data.filename.strip() or TOKEN_TYPES[token_type][1])
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM nodes WHERE id = %s", (data.node_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Node not found; install and register a Linux agent first")
    try:
        payload, source = generate_file(token_type)
    except GenerationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    token_id = str(uuid.uuid4())
    intended_path = target if data.target_kind == "file" else posixpath.join(target, filename) if target else ""
    placement = f"node:{data.node_id}, path:{intended_path or 'auto'}, name:{data.name}, status:pending"
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO honeytoken_files(token_type, file_path, placement) VALUES (%s, %s, %s) RETURNING id",
            (token_type, intended_path, placement),
        )
        file_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO honeytoken_deployments
               (honeytoken_file_id, node_id, token_id, filename, target_path, target_kind,
                content_base64, sha256, generation_source, display_name)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (file_id, data.node_id, token_id, filename, target, data.target_kind,
             base64.b64encode(payload).decode("ascii"), hashlib.sha256(payload).hexdigest(), source, data.name),
        )
        task_id = cur.fetchone()[0]
    return {"token_id": token_id, "deployment_task_id": task_id, "node_id": data.node_id,
            "type": token_type, "status": "pending", "target_path": target, "generation_source": source}


@app.get("/tokens")
def list_tokens():
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT hf.id, hf.token_type, hf.file_path, hf.placement, hf.created_at,
                      d.token_id, d.status, d.deployed_path, d.error, d.node_id, d.generation_source, d.display_name
               FROM honeytoken_files hf LEFT JOIN honeytoken_deployments d ON d.honeytoken_file_id = hf.id
               ORDER BY hf.id DESC LIMIT 500"""
        )
        rows = cur.fetchall()
    return [{"id": r[5] or f"legacy-{r[0]}", "type": r[1], "path": r[2], "placement": r[3] or "",
             "created_at": r[4].isoformat() if r[4] else None, "deployment_status": r[6] or "legacy",
             "deployed_path": r[7] or "", "deployment_error": r[8] or "", "node_id": r[9],
             "generation_source": r[10] or "", "name": r[11] or ""} for r in rows]


@app.get("/agent/tasks")
def agent_tasks(node_id: int):
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT d.id, d.token_id, hf.token_type, d.filename, d.target_path,
                      d.target_kind, d.content_base64, d.sha256, d.status, d.deployed_path
               FROM honeytoken_deployments d JOIN honeytoken_files hf ON hf.id = d.honeytoken_file_id
               WHERE d.node_id = %s AND d.status IN ('pending', 'deployed') ORDER BY d.id""",
            (node_id,),
        )
        rows = cur.fetchall()
    return [{"id": r[0], "token_id": r[1], "type": r[2], "filename": r[3], "target_path": r[4],
             "target_kind": r[5], "content_base64": r[6] if r[8] == "pending" else "",
             "sha256": r[7], "status": r[8], "deployed_path": r[9] or ""} for r in rows]


@app.put("/agent/tasks/{task_id}/result")
def report_result(task_id: int, data: DeploymentResult):
    if data.status == "deployed" and not data.deployed_path:
        raise HTTPException(status_code=400, detail="deployed_path required")
    path = validate_target(data.deployed_path)
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "SELECT honeytoken_file_id, status, deployed_path, display_name, target_path, filename, target_kind FROM honeytoken_deployments WHERE id = %s AND node_id = %s FOR UPDATE",
            (task_id, data.node_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found for this node")
        if row[1] == "deployed" and (data.status != "deployed" or path != row[2]):
            raise HTTPException(status_code=409, detail="A deployed task cannot be changed")
        cur.execute(
            """UPDATE honeytoken_deployments SET status = %s, deployed_path = %s, error = %s,
               completed_at = now(), updated_at = now() WHERE id = %s""",
            (data.status, path or None, data.error or None, task_id),
        )
        if data.status == "deployed":
            cur.execute("UPDATE honeytoken_files SET file_path = %s WHERE id = %s", (path, row[0]))
        intended_path = row[4] if row[6] == "file" else posixpath.join(row[4], row[5]) if row[4] else "auto"
        placement = f"node:{data.node_id}, path:{path or intended_path}, name:{row[3]}, status:{data.status}"
        cur.execute("UPDATE honeytoken_files SET placement = %s WHERE id = %s", (placement, row[0]))
    return {"status": "ok", "deployment_status": data.status, "path": path}
