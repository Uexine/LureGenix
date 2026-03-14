from fastapi import FastAPI, HTTPException
from passlib.context import CryptContext
from jose import jwt
import psycopg2
import os

app = FastAPI()

SECRET = os.getenv("JWT_SECRET", "secret")

pwd = CryptContext(schemes=["bcrypt"])

def db():

    return psycopg2.connect(
        host="postgres",
        database="luregenix",
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

@app.post("/login")
def login(data: dict):

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT password_hash FROM admins WHERE username=%s",
        (data["username"],)
    )

    row = cur.fetchone()

    if not row:
        raise HTTPException(401,"Invalid login")

    if not pwd.verify(data["password"], row[0]):
        raise HTTPException(401,"Invalid login")

    token = jwt.encode(
        {"user":data["username"]},
        SECRET,
        algorithm="HS256"
    )

    return {"token":token}
