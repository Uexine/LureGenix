import os
import secrets
from contextlib import closing
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from jose import jwt
import psycopg2
from passlib.hash import bcrypt

app = FastAPI()
SECRET = os.getenv("JWT_SECRET", "")


def get_db():
    return psycopg2.connect(host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"))


def hash_password(password):
    if not isinstance(password, str) or not password or len(password.encode("utf-8")) > 72:
        raise HTTPException(400, "Password must contain 1 to 72 UTF-8 bytes")
    return bcrypt.hash(password, rounds=12)


@app.on_event("startup")
def bootstrap():
    if not SECRET or SECRET == "your_super_secret_key_here_min_32_chars":
        raise RuntimeError("Set a private JWT_SECRET in .env")
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not password:
        return
    username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin").strip().lower()
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM admins LIMIT 1")
        if cur.fetchone() is None:
            cur.execute("INSERT INTO admins(username, password_hash) VALUES(%s,%s)",
                (username, hash_password(password)))


@app.post("/login")
def login(data: dict):
    username = str(data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if not username or not isinstance(password, str) or not password or len(password.encode("utf-8")) > 72:
        raise HTTPException(401, "Invalid username or password")
    with closing(get_db()) as conn, conn, conn.cursor() as cur:
        cur.execute("SELECT id, username, password_hash, is_active FROM admins WHERE LOWER(username) = %s", (username,))
        row = cur.fetchone()
        valid = False
        if row and row[3] and row[2]:
            try:
                valid = bcrypt.verify(password, row[2])
            except ValueError:
                pass
        if not valid:
            raise HTTPException(401, "Invalid username or password")
        cur.execute("UPDATE admins SET last_login=now() WHERE id=%s", (row[0],))
    token = jwt.encode({"sub": str(row[0]), "user": row[1],
        "exp": datetime.now(timezone.utc) + timedelta(days=1)}, SECRET, algorithm="HS256")
    return {"token": token, "username": row[1]}


@app.post("/admins")
def create_admin(data: dict):
    secret = os.getenv("ADMIN_SECRET", "")
    provided = data.get("_secret")
    if not secret or not isinstance(provided, str) or not secrets.compare_digest(secret, provided):
        raise HTTPException(403, "Forbidden")
    username = str(data.get("username") or "").strip().lower()
    if not username or len(username) > 100:
        raise HTTPException(400, "Invalid username")
    password_hash = hash_password(data.get("password"))
    try:
        with closing(get_db()) as conn, conn, conn.cursor() as cur:
            cur.execute("INSERT INTO admins(username, password_hash) VALUES(%s,%s)", (username, password_hash))
    except psycopg2.IntegrityError:
        raise HTTPException(409, "Username already exists")
    return {"status": "ok", "username": username}
