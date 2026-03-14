from fastapi import FastAPI
import os
import uuid

app = FastAPI()


@app.post("/generate")
def generate(data: dict):

    token_id = str(uuid.uuid4())

    filename = data.get("type", "token") + "_" + token_id + ".txt"

    path = "/tokens/" + filename

    os.makedirs("/tokens", exist_ok=True)

    with open(path, "w") as f:
        f.write("FAKE_SECRET_" + token_id)

    return {
        "token_id": token_id,
        "file": path
    }
