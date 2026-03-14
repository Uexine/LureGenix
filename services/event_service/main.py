from fastapi import FastAPI
import psycopg2
import os

app = FastAPI()


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER", "admin"),
        password=os.getenv("DB_PASSWORD", "admin")
    )


@app.post("/event")
def event(data: dict):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO events(token_id,description) VALUES(%s,%s)",
        (data.get("token_id"), data.get("description"))
    )

    conn.commit()

    cur.close()
    conn.close()

    return {"status": "saved"}
