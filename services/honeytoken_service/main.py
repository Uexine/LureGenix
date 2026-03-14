from fastapi import FastAPI
import os
import uuid
from groq import Groq  # xAI Grok via Groq API (fast)
from generator import generate_env, generate_passwords  # Импорт

app = FastAPI()

client = Groq(api_key=os.getenv("GROK_API_KEY"))

@app.post("/generate")
def generate(data: dict):
    token_id = str(uuid.uuid4())
    file_type = data.get("type", "txt")
    node_id = data.get("node_id")  # Для размещения

    # LLM для реалистичного контента
    if file_type == "pdf" or file_type == "docx":
        prompt = f"Generate realistic fake document content for honeytoken, type: {file_type}"
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="grok-beta",  # Или актуальный модель в 2026
        )
        content = response.choices[0].message.content
    elif file_type == "ssh_key":
        content = generate_env()  # Из generator.py
    else:
        content = generate_passwords()

    filename = f"{file_type}_{token_id}.{file_type}"
    path = f"/tokens/{filename}"
    with open(path, "w") as f:
        f.write(content)

    # TODO: Размещение в node via docker.sock (добавь docker-py)

    return {"token_id": token_id, "file": path, "node_id": node_id}