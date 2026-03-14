from fastapi import FastAPI,HTTPException
from passlib.context import CryptContext
import psycopg2
from jose import jwt

SECRET="SECRET"

pwd_context=CryptContext(schemes=["bcrypt"],deprecated="auto")

app=FastAPI()


def db():

    return psycopg2.connect(
        host="postgres",
        database="luregenix",
        user="admin",
        password="admin"
    )


@app.post("/login")
def login(data:dict):

    conn=db()
    cur=conn.cursor()

    cur.execute(
        "SELECT password_hash FROM admins WHERE username=%s",
        (data["username"],)
    )

    row=cur.fetchone()

    if not row:
        raise HTTPException(401)

    if not pwd_context.verify(data["password"],row[0]):
        raise HTTPException(401)

    token=jwt.encode({"user":data["username"]},SECRET,algorithm="HS256")

    return {"token":token}