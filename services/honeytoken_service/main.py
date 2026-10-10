import base64
import hashlib
import os
import posixpath
import uuid
from contextlib import asynccontextmanager, closing
from typing import Literal

import requests
from fastapi import HTTPException
from generator import TOKEN_TYPES, GenerationError, generate_file
from pydantic import BaseModel, ConfigDict, Field

from common.api import create_app
from common.database import connect as get_db
from common.database import utc_timestamp


@asynccontextmanager
async def lifespan(app):
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute("SELECT attempt FROM honeytoken_deployments LIMIT 0")
    yield


app = create_app(lifespan=lifespan, database=lambda: get_db())


@app.get("/generation-status")
def generation_status():
    mode = os.getenv("GENERATION_MODE", "template")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    try:
        result = requests.get(
            os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
            + "/api/tags",
            timeout=3,
        )
        result.raise_for_status()
        llm_ready = model in {
            item.get("name") for item in result.json().get("models", [])
        }
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        llm_ready = False
    return {
        "mode": mode,
        "model": model,
        "ready": mode == "template" or llm_ready,
        "llm_ready": llm_ready,
    }


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: int = Field(gt=0)
    type: str = "txt"
    name: str = Field(default="", max_length=200)
    filename: str = Field(default="", max_length=255)
    node_path: str = Field(default="", max_length=4096)
    target_kind: Literal["directory", "file"] = "directory"
    generation_mode: Literal["template", "llm"] | None = None


class DeploymentResult(BaseModel):
    node_id: int = Field(gt=0)
    status: Literal["deployed", "failed"]
    deployed_path: str = Field(default="", max_length=4096)
    error: str = Field(default="", max_length=1000)
    attempt: int = Field(default=1, ge=1)


def validate_target(path):
    if path and (
        not path.startswith("/")
        or path.startswith("//")
        or ".." in path.split("/")
        or any(ord(c) < 32 for c in path)
    ):
        raise HTTPException(
            status_code=400, detail="Укажите абсолютный путь Linux без '..'."
        )
    return posixpath.normpath(path) if path else ""


def validate_filename(filename):
    if (
        not filename
        or filename in (".", "..")
        or len(filename.encode("utf-8")) > 255
        or any(c in filename for c in "/\\")
        or any(ord(c) < 32 for c in filename)
    ):
        raise HTTPException(
            status_code=400,
            detail="Укажите только имя файла, без каталогов.",
        )
    return filename


@app.get("/token-types")
def token_types():
    return [
        {"id": index, "name": key, "description": value[0]}
        for index, (key, value) in enumerate(TOKEN_TYPES.items(), 1)
    ]


@app.post("/generate")
def generate(data: GenerateRequest):
    token_type = {"env": "env_file", "sql": "db_dump"}.get(
        data.type.lower(), data.type.lower()
    )
    if token_type not in TOKEN_TYPES:
        raise HTTPException(status_code=400, detail="Неподдерживаемый тип приманки.")
    target = validate_target(data.node_path.strip())
    if data.target_kind == "file" and not target:
        raise HTTPException(
            status_code=400, detail="Для размещения файлом укажите полный путь к файлу."
        )
    token_id = str(uuid.uuid4())
    default_name = TOKEN_TYPES[token_type][1]
    stem, extension = posixpath.splitext(default_name)
    if default_name.endswith(".tar.gz"):
        stem, extension = default_name[:-7], ".tar.gz"
    filename = validate_filename(
        data.filename.strip() or f"{stem}_{token_id[:8]}{extension}"
    )
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, credential_hash FROM nodes WHERE id = %s", (data.node_id,)
        )
        node = cur.fetchone()
        if not node:
            raise HTTPException(
                status_code=404,
                detail="Сервер не найден. Сначала установите и зарегистрируйте Linux-агент.",
            )
        if not node[1]:
            raise HTTPException(
                409, "Для этой старой ноды не зарегистрирован Linux-агент."
            )
    try:
        payload, source = generate_file(token_type, mode=data.generation_mode)
    except GenerationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    intended_path = (
        target
        if data.target_kind == "file"
        else posixpath.join(target, filename)
        if target
        else ""
    )
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
            (
                file_id,
                data.node_id,
                token_id,
                filename,
                target,
                data.target_kind,
                base64.b64encode(payload).decode("ascii"),
                hashlib.sha256(payload).hexdigest(),
                source,
                data.name,
            ),
        )
        task_id = cur.fetchone()[0]
    return {
        "token_id": token_id,
        "deployment_task_id": task_id,
        "node_id": data.node_id,
        "type": token_type,
        "status": "pending",
        "target_path": target,
        "generation_source": source,
    }


@app.get("/tokens")
def list_tokens():
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT hf.id, hf.token_type, hf.file_path, hf.placement, hf.created_at,
                      d.token_id, d.status, d.deployed_path, d.error, d.node_id, d.generation_source, d.display_name,
                      d.integrity_status, d.last_event_at
               FROM honeytoken_files hf LEFT JOIN honeytoken_deployments d ON d.honeytoken_file_id = hf.id
               ORDER BY hf.id DESC LIMIT 500"""
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[5] or f"legacy-{r[0]}",
            "type": r[1],
            "path": r[2],
            "placement": r[3] or "",
            "created_at": utc_timestamp(r[4]),
            "deployment_status": r[6] or "legacy",
            "deployed_path": r[7] or "",
            "deployment_error": r[8] or "",
            "node_id": r[9],
            "generation_source": r[10] or "",
            "name": r[11] or "",
            "integrity_status": r[12] or "unknown",
            "last_event_at": utc_timestamp(r[13]),
        }
        for r in rows
    ]


@app.get("/agent/tasks")
def agent_tasks(node_id: int):
    with closing(get_db()) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT d.id, d.token_id, hf.token_type, d.filename, d.target_path,
                      d.target_kind, CASE WHEN d.status='pending' THEN d.content_base64 ELSE '' END, d.sha256, d.status, d.deployed_path, d.attempt
               FROM honeytoken_deployments d JOIN honeytoken_files hf ON hf.id = d.honeytoken_file_id
               WHERE d.node_id = %s AND d.status IN ('pending', 'deployed') ORDER BY d.id""",
            (node_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "token_id": r[1],
            "type": r[2],
            "filename": r[3],
            "target_path": r[4],
            "target_kind": r[5],
            "content_base64": r[6] if r[8] == "pending" else "",
            "sha256": r[7],
            "status": r[8],
            "deployed_path": r[9] or "",
            "attempt": r[10],
        }
        for r in rows
    ]


@app.post("/tokens/{token_id}/retry")
def retry(token_id: uuid.UUID):
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE honeytoken_deployments SET status='pending',error=NULL,completed_at=NULL,attempt=attempt+1,updated_at=now() WHERE token_id=%s AND status='failed' RETURNING id",
            (str(token_id),),
        )
        if not cur.fetchone():
            raise HTTPException(409, "Повторить можно только неудачное размещение.")
    return {"status": "ok"}


@app.put("/agent/tasks/{task_id}/result")
def report_result(task_id: int, data: DeploymentResult):
    if data.status == "deployed" and not data.deployed_path:
        raise HTTPException(
            status_code=400, detail="Не указан путь размещённого файла."
        )
    path = validate_target(data.deployed_path)
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "SELECT honeytoken_file_id, status, deployed_path, display_name, target_path, filename, target_kind, attempt FROM honeytoken_deployments WHERE id = %s AND node_id = %s FOR UPDATE",
            (task_id, data.node_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=404, detail="Задание для этого сервера не найдено."
            )
        if data.attempt != row[7]:
            raise HTTPException(
                409, "Результат относится к устаревшей попытке размещения."
            )
        if row[1] == "deployed" and (data.status != "deployed" or path != row[2]):
            raise HTTPException(
                status_code=409, detail="Завершённое размещение нельзя изменить."
            )
        if row[1] == "deployed":
            return {"status": "ok", "deployment_status": "deployed", "path": path}
        expected_path = row[4] if row[6] == "file" else posixpath.join(row[4], row[5])
        if data.status == "deployed" and row[4] and path != expected_path:
            raise HTTPException(
                400, "Путь размещённого файла не совпадает с выбранным."
            )
        cur.execute(
            """UPDATE honeytoken_deployments SET status = %s, deployed_path = %s, error = %s,
               integrity_status=CASE WHEN %s='deployed' THEN 'intact' ELSE 'error' END,
               completed_at = now(), updated_at = now() WHERE id = %s""",
            (data.status, path or None, data.error or None, data.status, task_id),
        )
        if data.status == "deployed":
            cur.execute(
                "UPDATE honeytoken_files SET file_path = %s WHERE id = %s",
                (path, row[0]),
            )
        intended_path = expected_path if row[4] else "auto"
        placement = f"node:{data.node_id}, path:{path or intended_path}, name:{row[3]}, status:{data.status}"
        cur.execute(
            "UPDATE honeytoken_files SET placement = %s WHERE id = %s",
            (placement, row[0]),
        )
    return {"status": "ok", "deployment_status": data.status, "path": path}
