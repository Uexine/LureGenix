from fastapi import FastAPI
import os
import uuid
from groq import Groq
import generator  # импорт generator.py

app = FastAPI()

client = Groq(api_key=os.getenv("GROK_API_KEY"))

@app.post("/generate")
def generate(data: dict):
    token_id = str(uuid.uuid4())
    file_type = data.get("file_type", "txt")
    node_id = data.get("node_id")

    os.makedirs("/tokens", exist_ok=True)

    if file_type == "env":
        content = generator.generate_env()
    elif file_type == "passwords":
        content = generator.generate_passwords()
    else:
        # LLM для других типов
        prompt = f"Generate realistic fake {file_type} content for honeytoken."
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="grok-beta",
        )
        content = response.choices[0].message.content

    filename = f"{file_type}_{token_id}.{file_type if file_type != 'passwords' else 'txt'}"
    path = f"/tokens/{filename}"
    with open(path, "w") as f:
        f.write(content)

    # TODO: docker-py для размещения в node

    return {"token_id": token_id, "file": path, "node_id": node_id}