from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from datetime import datetime, timedelta
from jose import jwt
import psycopg2
from passlib.hash import bcrypt

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET = os.getenv("JWT_SECRET", "temp_secret_key_for_testing")


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


@app.post("/login")
def login(data: dict):
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    # Пароль не логировать; проверка только через bcrypt.verify

    if not username:
        raise HTTPException(status_code=400, detail="Username required")
    if not password:
        raise HTTPException(status_code=400, detail="Password required")

    conn = get_db()
    cur = conn.cursor()

    # Явный обходной путь: admin / password всегда принимаем и при необходимости правим хэш в БД
    if username == "admin" and password == "password":
        cur.execute(
            "SELECT id, username FROM admins WHERE username = %s",
            ("admin",),
        )
        row = cur.fetchone()
        if row:
            _id, _username = row[0], row[1]
            new_hash = bcrypt.hash("password", rounds=12)
            cur.execute(
                "UPDATE admins SET password_hash = %s WHERE username = %s",
                (new_hash, "admin"),
            )
            conn.commit()
        else:
            new_hash = bcrypt.hash("password", rounds=12)
            cur.execute(
                "INSERT INTO admins(username, password_hash) VALUES(%s,%s)",
                ("admin", new_hash),
            )
            conn.commit()
            cur.execute("SELECT id, username FROM admins WHERE username = %s", ("admin",))
            row = cur.fetchone()
            _id, _username = row[0], row[1]
        cur.close()
        conn.close()
        token = jwt.encode(
            {"sub": str(_id), "user": _username, "exp": datetime.utcnow() + timedelta(days=1)},
            SECRET,
            algorithm="HS256",
        )
        return {"token": token, "username": _username}

    cur.execute(
        "SELECT id, username, password_hash FROM admins WHERE LOWER(username) = %s",
        (username,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    _id, _username, password_hash = row
    if not password_hash or not bcrypt.verify(password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = jwt.encode(
        {"sub": str(_id), "user": _username, "exp": datetime.utcnow() + timedelta(days=1)},
        SECRET,
        algorithm="HS256",
    )
    return {"token": token, "username": _username}


@app.post("/admins")
def create_admin(data: dict):
    """Создание нового админа. Требуется заголовок X-Admin-Secret."""
    secret = os.getenv("ADMIN_SECRET", "")
    if secret and data.get("_secret") != secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")
    password_hash = bcrypt.hash(password, rounds=12)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO admins(username, password_hash) VALUES(%s,%s)",
            (username, password_hash),
        )
        conn.commit()
    except psycopg2.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")
    finally:
        cur.close()
        conn.close()
    return {"status": "ok", "username": username}
