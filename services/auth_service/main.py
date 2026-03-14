from fastapi import FastAPI, HTTPException
import psycopg2
import os

app = FastAPI()


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        dbname=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin")
    )


@app.post("/login")
def login(data: dict):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT password FROM admins WHERE username=%s",
        (data["username"],)
    )

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        raise HTTPException(status_code=401)

    if row[0] != data["password"]:
        raise HTTPException(status_code=401)

    return {
        "status": "ok",
        "token": "demo-token"
    }
