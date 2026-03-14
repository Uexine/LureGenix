from fastapi import FastAPI, HTTPException
from passlib.context import CryptContext
from jose import jwt
import psycopg2
import os

app = FastAPI()

SECRET = os.getenv("JWT_SECRET", "luregenix_secret")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin")
    )

@app.post("/login")
def login(data: dict):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT password_hash FROM admins WHERE username=%s",
        (data["username"],)
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid login")
    if not pwd_context.verify(data["password"], row[0]):
        raise HTTPException(status_code=401, detail="Invalid login")
    token = jwt.encode({"user": data["username"]}, SECRET, algorithm="HS256")
    cur.close()
    conn.close()
    return {"token": token}