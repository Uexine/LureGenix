from fastapi import FastAPI
import os
import uuid
from groq import Groq
from generator import generate_env, generate_passwords
import glob

app = FastAPI()

api_key = os.getenv("GROK_API_KEY")
client = Groq(api_key=api_key) if api_key else None

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

    if client and file_type in ["pdf", "docx"]:
        try:
            prompt = f"Generate realistic fake document content for honeytoken, type: {file_type}"
            response = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="grok-beta",
            )
            content = response.choices[0].message.content
        except Exception as e:
            content = f"Dummy content (error: {str(e)})"

    filename = f"{file_type}_{token_id}.{file_type}"
    path = f"/tokens/{filename}"
    with open(path, "w") as f:
        f.write(content)

    return {"token_id": token_id, "file": path, "node_id": node_id}

@app.get("/tokens")
def list_tokens():
    """Возвращает список файлов-токенов из /tokens."""
    files = glob.glob("/tokens/*.*")
    tokens = []
    for f in files:
        basename = os.path.basename(f)
        # Пример имени: pdf_abc123.pdf
        parts = basename.split('_', 1)
        if len(parts) == 2:
            token_type = parts[0]
            token_id = parts[1].split('.')[0]  # обрезаем расширение
        else:
            token_type = "unknown"
            token_id = basename
        tokens.append({
            "id": token_id,
            "type": token_type,
            "path": f
        })
    return tokens