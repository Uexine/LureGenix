import os
import secrets
from contextlib import asynccontextmanager, closing
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import psycopg2
from fastapi import HTTPException

from common.api import create_app
from common.database import connect as get_db


@asynccontextmanager
async def lifespan(app):
    bootstrap()
    yield


app = create_app(lifespan=lifespan, database=lambda: get_db())
SECRET = os.getenv("JWT_SECRET", "")


def hash_password(password):
    if (
        not isinstance(password, str)
        or len(password) < 12
        or len(password.encode("utf-8")) > 72
    ):
        raise HTTPException(
            400,
            "Пароль должен содержать не менее 12 символов и не более 72 байт UTF-8.",
        )
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "ascii"
    )


def bootstrap():
    if len(SECRET) < 32 or SECRET == "your_super_secret_key_here_min_32_chars":
        raise RuntimeError(
            "Задайте секрет JWT_SECRET длиной не менее 32 символов в .env."
        )
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not password:
        return
    username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin").strip().lower()
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM admins LIMIT 1")
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO admins(username, password_hash) VALUES(%s,%s)",
                (username, hash_password(password)),
            )


@app.post("/login")
def login(data: dict):
    username = str(data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if (
        not username
        or not isinstance(password, str)
        or not password
        or len(password.encode("utf-8")) > 72
    ):
        raise HTTPException(401, "Неверный логин или пароль.")
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, password_hash, is_active FROM admins WHERE LOWER(username) = %s",
            (username,),
        )
        row = cur.fetchone()
        valid = False
        if row and row[3] and row[2]:
            try:
                valid = bcrypt.checkpw(password.encode("utf-8"), row[2].encode("ascii"))
            except (ValueError, UnicodeError):
                pass
        if not valid:
            raise HTTPException(401, "Неверный логин или пароль.")
        cur.execute("UPDATE admins SET last_login=now() WHERE id=%s", (row[0],))
    token = jwt.encode(
        {
            "sub": str(row[0]),
            "user": row[1],
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"token": token, "username": row[1]}


@app.post("/admins")
def create_admin(data: dict):
    secret = os.getenv("ADMIN_SECRET", "")
    provided = data.get("_secret")
    if (
        not secret
        or not isinstance(provided, str)
        or not secrets.compare_digest(secret.encode(), provided.encode())
    ):
        raise HTTPException(403, "Недостаточно прав для выполнения действия.")
    username = str(data.get("username") or "").strip().lower()
    if not username or len(username) > 100:
        raise HTTPException(400, "Укажите логин длиной от 1 до 100 символов.")
    password_hash = hash_password(data.get("password"))
    try:
        with closing(get_db()) as conn, conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admins(username, password_hash) VALUES(%s,%s)",
                (username, password_hash),
            )
    except psycopg2.IntegrityError:
        raise HTTPException(409, "Пользователь с таким логином уже существует.")
    return {"status": "ok", "username": username}


@app.put("/password")
def change_password(data: dict):
    current = data.get("current_password")
    if not isinstance(current, str) or not current or len(current.encode("utf-8")) > 72:
        raise HTTPException(400, "Введите текущий пароль.")
    new_hash = hash_password(data.get("new_password"))
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute(
            "SELECT password_hash FROM admins WHERE id=%s AND is_active=true FOR UPDATE",
            (data.get("_admin_id"),),
        )
        row = cur.fetchone()
        valid = False
        if row:
            try:
                valid = bcrypt.checkpw(current.encode("utf-8"), row[0].encode("ascii"))
            except (ValueError, UnicodeError):
                pass
        if not valid:
            raise HTTPException(403, "Текущий пароль неверен.")
        cur.execute(
            "UPDATE admins SET password_hash=%s WHERE id=%s",
            (new_hash, data["_admin_id"]),
        )
    return {"status": "ok"}
