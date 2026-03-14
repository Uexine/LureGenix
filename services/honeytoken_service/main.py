from fastapi import FastAPI
import os
import uuid
from groq import Groq
from generator import generate_env, generate_passwords

app = FastAPI()

client = Groq(api_key=os.getenv("GROK_API_KEY"))

@app.post("/generate")
def generate(data: dict):
    token_id = str(uuid.uuid4())
    file_type = data.get("type", "txt")
    node_id = data.get("node_id")

    os.makedirs("/tokens", exist_ok=True)

    if file_type == "ssh_key":
        content = generate_env()
    else:
        content = generate_passwords()

    if file_type in ["pdf", "docx"]:
        prompt = f"Generate realistic fake document content for honeytoken, type: {file_type}"
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="grok-beta",
        )
        content = response.choices[0].message.content

    filename = f"{file_type}_{token_id}.{file_type}"
    path = f"/tokens/{filename}"
    with open(path, "w") as f:
        f.write(content)

    return {"token_id": token_id, "file": path, "node_id": node_id}