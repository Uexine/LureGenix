"""
Сервис обнаружения нод: список из БД (таблица nodes) + опционально контейнеры Docker.
Агент может регистрироваться через POST /register.
"""
from fastapi import FastAPI, HTTPException
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


def _list_nodes_from_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, hostname, ip, status, last_heartbeat FROM nodes ORDER BY id"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0],
                "hostname": r[1] or "node",
                "ip": str(r[2]) if r[2] else "-",
                "status": r[3] or "offline",
                "last_heartbeat": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"discovery nodes from db error: {e}")
        return []


def _list_containers_docker():
    """Список контейнеров через Docker API (если доступен сокет)."""
    out = []
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "DOCKER_HOST": os.getenv("DOCKER_HOST", "")},
        )
        if result.returncode != 0:
            return out
        for line in result.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("\t", 2)
            cid = parts[0][:12] if len(parts) > 0 else ""
            name = parts[1] if len(parts) > 1 else cid
            out.append({
                "id": name,
                "hostname": name,
                "ip": "container",
                "status": "online",
            })
    except Exception as e:
        print(f"docker ps error: {e}")
    return out


@app.get("/nodes")
def nodes():
    """Список нод: из БД + при отсутствии записей — из Docker (если доступен)."""
    from_db = _list_nodes_from_db()
    if from_db:
        return from_db
    from_docker = _list_containers_docker()
    if from_docker:
        return [{"id": i + 1, **n} for i, n in enumerate(from_docker)]
    return []


@app.post("/register")
def register(data: dict):
    """Регистрация ноды агентом (hostname, ip)."""
    hostname = (data.get("hostname") or "agent").strip()
    ip = (data.get("ip") or "127.0.0.1").strip()
    if not hostname:
        raise HTTPException(status_code=400, detail="hostname required")
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO nodes (hostname, ip, status, last_heartbeat)
            VALUES (%s, %s, 'online', now())
            ON CONFLICT (hostname, ip) DO UPDATE SET
                status = 'online',
                last_heartbeat = now(),
                updated_at = now()
            """,
            (hostname, ip),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "hostname": hostname, "ip": ip}
    except Exception as e:
        print(f"register error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/containers")
def containers():
    """Список контейнеров Docker (для отладки)."""
    return _list_containers_docker()
