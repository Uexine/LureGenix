from fastapi import FastAPI, HTTPException
from jose import jwt
import psycopg2
import os
from datetime import datetime, timedelta

app = FastAPI()

SECRET = os.getenv("JWT_SECRET", "temp_secret_key_for_testing")

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin")
    )

@app.post("/login")
def login(data: dict):
    username = data.get("username")
    password = data.get("password")  # пока не используем для проверки
    
    if not username:
        raise HTTPException(status_code=400, detail="Username required")
    
    # ВРЕМЕННО: пропускаем любого пользователя с любым паролем
    # Просто проверяем, существует ли пользователь в БД
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute(
        "SELECT username FROM admins WHERE username=%s",
        (username,)
    )
    
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    # Если пользователя нет в БД, создадим его автоматически (для теста)
    if not row:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (%s, 'temp_hash_not_used')",
            (username,)
        )
        conn.commit()
        cur.close()
        conn.close()
    
    # Генерируем токен
    token = jwt.encode(
        {"user": username, "exp": datetime.utcnow() + timedelta(days=1)},
        SECRET,
        algorithm="HS256"
    )
    
    return {"token": token}