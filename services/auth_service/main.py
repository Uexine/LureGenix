from fastapi import FastAPI, HTTPException
from passlib.context import CryptContext
import psycopg2
from jose import jwt

app = FastAPI()

pwd_context = CryptContext(schemes=["bcrypt"])

SECRET = "supersecret"

conn = psycopg2.connect(
    host="postgres",
    database="luregenix",
    user="admin",
    password="admin"
)

@app.post("/login")
def login(data:dict):

    cur = conn.cursor()

    cur.execute(
        "SELECT password_hash FROM admins WHERE username=%s",
        (data["username"],)
    )

    row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not pwd_context.verify(data["password"], row[0]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = jwt.encode(
        {"user": data["username"]},
        SECRET,
        algorithm="HS256"
    )

    return {"token": token}
