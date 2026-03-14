from fastapi import FastAPI
import psycopg2
import os

app = FastAPI()

def db():
    return psycopg2.connect(
        host="postgres",
        database="luregenix",
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD")
    )

@app.post("/event")
def add_event(data:dict):

    conn=db()
    cur=conn.cursor()

    cur.execute(
        "INSERT INTO events(type,source) VALUES(%s,%s)",
        (data["type"],data["source"])
    )

    conn.commit()

    return {"status":"ok"}

@app.get("/events")
def events():

    conn=db()
    cur=conn.cursor()

    cur.execute(
        "SELECT id,type,source,created_at FROM events ORDER BY id DESC"
    )

    rows=cur.fetchall()

    return [
        {
            "id":r[0],
            "type":r[1],
            "source":r[2],
            "time":str(r[3])
        }
        for r in rows
    ]
