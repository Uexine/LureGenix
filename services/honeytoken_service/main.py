from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import uuid
from groq import Groq
from generator import generate_env, generate_passwords
import psycopg2

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key = os.getenv("GROK_API_KEY")
client = Groq(api_key=api_key) if api_key else None

# Модель Groq для генерации текста (реалистичный контент приманки)
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def save_token_to_db(token_id: str, token_type: str, file_path: str, placement: str):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO honeytokens(token_type, file_path, placement) VALUES(%s,%s,%s)",
            (token_type, file_path, placement or ""),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB save honeytoken error: {e}")


@app.post("/generate")
def generate(data: dict):
    token_id = str(uuid.uuid4())
    file_type = (data.get("type") or "txt").lower()
    node_id = data.get("node_id") or ""
    name = data.get("name") or ""

    os.makedirs("/tokens", exist_ok=True)

    if file_type in ("ssh_key", "env"):
        content = generate_env()
    elif file_type == "password":
        content = generate_passwords()
    else:
        content = generate_passwords()

    if client and file_type in ("pdf", "docx"):
        try:
            prompt = (
                f"Generate short realistic fake document content for a honeytoken (1-2 paragraphs), "
                f"type: {file_type}. Text only, no markdown."
            )
            response = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=GROQ_MODEL,
            )
            content = (response.choices[0].message.content or "").strip() or content
        except Exception as e:
            content = f"Confidential draft (error: {str(e)})"

    ext = "txt"
    if file_type in ("pdf", "docx"):
        ext = file_type
    elif file_type in ("ssh_key", "env"):
        ext = "env" if file_type == "env" else "txt"

    filename = f"{file_type}_{token_id}.{ext}"
    path = f"/tokens/{filename}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    placement = f"node:{node_id}" + (f",name:{name}" if name else "")
    save_token_to_db(token_id, file_type, path, placement)

    return {"token_id": token_id, "file": path, "node_id": node_id, "type": file_type}


@app.get("/tokens")
def list_tokens():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, token_type, file_path, placement, created_at FROM honeytokens ORDER BY id DESC LIMIT 500"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        out = []
        for r in rows:
            path = r[2] or ""
            # token_id из имени файла: /tokens/type_uuid.ext
            token_id = ""
            if path:
                basename = os.path.basename(path)
                parts = basename.replace(".", "_").split("_")
                if len(parts) >= 2:
                    token_id = parts[1]
            out.append({
                "id": token_id,
                "type": r[1],
                "path": path,
                "placement": r[3] or "",
                "created_at": r[4].isoformat() if r[4] else None,
            })
        return out
    except Exception as e:
        print(f"DB tokens error: {e}")
    # Fallback: список по файлам
    import glob
    files = glob.glob("/tokens/*.*")
    tokens = []
    for f in files:
        basename = os.path.basename(f)
        parts = basename.split("_", 1)
        if len(parts) == 2:
            token_type = parts[0]
            token_id = parts[1].split(".")[0]
        else:
            token_type = "unknown"
            token_id = basename
        tokens.append({
            "id": token_id,
            "type": token_type,
            "path": f,
            "placement": "-",
            "created_at": None,
        })
    return tokens
