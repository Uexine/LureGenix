from fastapi import FastAPI,WebSocket
import psycopg2

app=FastAPI()

connections=[]


def db():

    return psycopg2.connect(
        host="postgres",
        database="luregenix",
        user="admin",
        password="admin"
    )


@app.websocket("/ws")
async def websocket(ws:WebSocket):

    await ws.accept()
    connections.append(ws)

    while True:
        await ws.receive_text()


async def notify(event):

    for ws in connections:
        await ws.send_json(event)


@app.post("/event")
async def event(data:dict):

    conn=db()
    cur=conn.cursor()

    cur.execute(
        "INSERT INTO events(node_id,token_id,action,file_path) VALUES(%s,%s,%s,%s)",
        (
            data["node_id"],
            data["token_id"],
            data["action"],
            data["file"]
        )
    )

    conn.commit()

    await notify(data)

    return {"status":"ok"}