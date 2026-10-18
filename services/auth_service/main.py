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
    """Готовит первого администратора перед приёмом запросов."""
    bootstrap()
    yield


app = create_app(lifespan=lifespan, database=lambda: get_db())
SECRET = os.getenv("JWT_SECRET", "")


def hash_password(password):
    """Проверяет длину нового пароля и сохраняет только его bcrypt-хеш."""
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


def password_matches(password, stored_hash):
    """Сравнивает пароль с bcrypt-хешем; повреждённый хеш не открывает доступ."""
    if (
        not isinstance(password, str)
        or not password
        or not isinstance(stored_hash, str)
    ):
        return False
    try:
        encoded = password.encode("utf-8")
        return len(encoded) <= 72 and bcrypt.checkpw(
            encoded, stored_hash.encode("ascii")
        )
    except (ValueError, UnicodeError):
        return False


def normalized_username(value):
    """Приводит логин к единому регистру и отклоняет пустые или слишком длинные значения."""
    if not isinstance(value, str):
        return ""
    username = value.strip().lower()
    return username if 0 < len(username) <= 100 else ""


def bootstrap():
    """Создаёт начальную учётную запись только в БД без администраторов."""
    if len(SECRET) < 32 or SECRET == "your_super_secret_key_here_min_32_chars":
        raise RuntimeError(
            "Задайте секрет JWT_SECRET длиной не менее 32 символов в .env."
        )
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not password:
        return
    username = normalized_username(os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin"))
    if not username:
        raise RuntimeError(
            "Задайте BOOTSTRAP_ADMIN_USERNAME длиной от 1 до 100 символов."
        )
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM admins LIMIT 1")
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO admins(username, password_hash) VALUES(%s,%s)",
                (username, hash_password(password)),
            )


@app.post("/login")
def login(data: dict):
    """Проверяет активного администратора и выдаёт JWT сроком на один час."""
    username = normalized_username(data.get("username"))
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
        if not row or not row[3] or not password_matches(password, row[2]):
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
    """Создаёт администратора по запросу шлюза с внутренним секретом."""
    secret = os.getenv("ADMIN_SECRET", "")
    provided = data.get("_secret")
    if (
        not secret
        or not isinstance(provided, str)
        or not secrets.compare_digest(secret.encode(), provided.encode())
    ):
        raise HTTPException(403, "Недостаточно прав для выполнения действия.")
    username = normalized_username(data.get("username"))
    if not username:
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
    """Меняет пароль действующего администратора после проверки текущего."""
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
        if not row or not password_matches(current, row[0]):
            raise HTTPException(403, "Текущий пароль неверен.")
        cur.execute(
            "UPDATE admins SET password_hash=%s WHERE id=%s",
            (new_hash, data["_admin_id"]),
        )
    return {"status": "ok"}


"""Вход администраторов, создание учётных записей и смена пароля."""
