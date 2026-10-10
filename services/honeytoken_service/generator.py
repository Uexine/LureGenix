import base64
import io
import json
import os
import secrets
import tarfile

import requests

TOKEN_TYPES = {
    "ssh_key": ("Закрытый SSH-ключ", "id_rsa_backup"),
    "env_file": ("Файл окружения", "credentials.env"),
    "db_dump": ("Резервная копия БД (SQL)", "database_backup.sql"),
    "api_key": ("API-ключ", "service-api.key"),
    "password": ("Пароли", "credentials.txt"),
    "bash_history": ("История команд", "bash_history_backup.txt"),
    "log_file": ("Журнал доступа", "access-backup.log"),
    "backup_archive": ("Архив резервной копии (tar.gz)", "database_backup.tar.gz"),
    "docker_config": ("Конфигурация реестра", "registry-config.json"),
    "pdf": ("Документ PDF", "operations_notes.pdf"),
    "docx": ("Документ Word", "operations_notes.docx"),
    "txt": ("Текстовый документ", "operations_notes.txt"),
}

FORMAT_INSTRUCTIONS = {
    "env_file": "Valid dotenv KEY=value lines for a fictional application.",
    "db_dump": "Valid PostgreSQL SQL with CREATE TABLE and INSERT statements for fictional users and settings.",
    "bash_history": "Plausible shell command history with fictional backup and administration paths.",
    "log_file": "Plausible web access log lines using documentation IP addresses.",
    "backup_archive": "Valid PostgreSQL SQL backup text; it will be packaged into a tar.gz archive.",
    "docker_config": "Valid JSON registry configuration with fictional authentication data.",
    "pdf": "An internal operations document in English with a title and several paragraphs.",
    "docx": "An internal operations document in English with a title and several paragraphs.",
    "txt": "An internal operations document in English with a title and several paragraphs.",
}


class GenerationError(Exception):
    pass


def llm_content(token_type):
    base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    try:
        response = requests.post(
            f"{base_url}/api/chat",
            timeout=(5, float(os.getenv("LLM_TIMEOUT_SECONDS", "180"))),
            json={
                "model": model,
                "stream": False,
                "format": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                    "additionalProperties": False,
                },
                "options": {"num_predict": 2000, "num_ctx": 4096, "temperature": 0.6},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Generate realistic fictional file content for a defensive honeytoken. "
                            "Return a JSON object with exactly one string field named content. "
                            "Use only invented names and credentials, reserved example domains, "
                            "and documentation IP addresses. Do not label the content as a decoy. "
                            "Do not include markdown code fences."
                        ),
                    },
                    {"role": "user", "content": FORMAT_INSTRUCTIONS[token_type]},
                ],
            },
        )
        if response.status_code == 404:
            raise GenerationError(
                f"Локальная модель {model} не найдена. Загрузите её в Ollama."
            )
        response.raise_for_status()
        result = response.json()
        if result.get("error"):
            raise GenerationError("Ошибка генерации Ollama. Проверьте журнал сервиса.")
        if result.get("done") is not True or result.get("done_reason") == "length":
            raise GenerationError("Ответ модели обрезан. Повторите генерацию.")
        content = json.loads(result["message"]["content"])["content"]
        if (
            not isinstance(content, str)
            or not content.strip()
            or len(content.encode("utf-8")) > 100_000
        ):
            raise GenerationError("Модель вернула пустой или слишком большой файл.")
        if token_type == "docker_config" and not isinstance(json.loads(content), dict):
            raise GenerationError("Модель вернула некорректную конфигурацию реестра.")
        if token_type in ("db_dump", "backup_archive"):
            if (
                "CREATE TABLE" not in content.upper()
                or "INSERT INTO" not in content.upper()
            ):
                raise GenerationError("Ответ модели не содержит резервную копию SQL.")
        return content.strip() + "\n"
    except GenerationError:
        raise
    except requests.exceptions.Timeout as exc:
        raise GenerationError(
            "Модель не ответила вовремя. Выберите меньшую модель или увеличьте LLM_TIMEOUT_SECONDS."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise GenerationError(
            "Нет соединения с локальной Ollama. Проверьте сервис и OLLAMA_BASE_URL."
        ) from exc
    except Exception as exc:
        raise GenerationError(
            "Не удалось сгенерировать файл. Проверьте Ollama и OLLAMA_MODEL."
        ) from exc


def generate_file(token_type, mode=None):
    if token_type not in TOKEN_TYPES:
        raise GenerationError("Неподдерживаемый тип приманки.")
    mode = mode or os.getenv("GENERATION_MODE", "template")
    if mode not in ("llm", "template"):
        raise GenerationError("Выберите режим генерации: шаблоны или LLM.")
    if token_type == "ssh_key":
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        ), "local"
    if token_type == "api_key":
        return ("API_KEY=" + secrets.token_urlsafe(32) + "\n").encode(), "local"
    if token_type == "password":
        return ("backup_admin:" + secrets.token_urlsafe(18) + "\n").encode(), "local"

    content = (
        template_content(token_type) if mode == "template" else llm_content(token_type)
    )
    payload = encode_content(token_type, content)
    if len(payload) > 1_000_000:
        raise GenerationError("Размер файла превышает ограничение агента (1 МБ).")
    return payload, mode


def encode_content(token_type, content):
    # Generated text is packaged as data; SQL and shell-history decoys are never executed.
    if token_type == "backup_archive":
        buffer = io.BytesIO()
        payload = content.encode("utf-8")
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            entry = tarfile.TarInfo("database_backup.sql")
            entry.size = len(payload)
            entry.mode = 0o600
            archive.addfile(entry, io.BytesIO(payload))
        return buffer.getvalue()
    if token_type == "docx":
        from docx import Document

        document = Document()
        for line in content.splitlines():
            document.add_paragraph(line)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()
    if token_type == "pdf":
        from html import escape

        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        buffer = io.BytesIO()
        styles = getSampleStyleSheet()
        paragraphs = []
        for line in content.splitlines():
            if line.strip():
                paragraphs.extend(
                    [Paragraph(escape(line), styles["BodyText"]), Spacer(1, 8)]
                )
        SimpleDocTemplate(buffer).build(paragraphs)
        return buffer.getvalue()
    return content.encode("utf-8")


def template_content(token_type):
    password = secrets.token_urlsafe(24)
    sql = (
        "-- Application database backup\n"
        "CREATE TABLE backup_settings (name TEXT PRIMARY KEY, value TEXT);\n"
        f"INSERT INTO backup_settings VALUES ('backup_password', '{password}');\n"
        "INSERT INTO backup_settings VALUES ('endpoint', 'https://backup.example.com');\n"
    )
    templates = {
        "env_file": f"APP_ENV=production\nDB_HOST=db.example.com\nDB_USER=backup_admin\nDB_PASSWORD={password}\n",
        "db_dump": sql,
        "backup_archive": sql,
        "bash_history": "cd /var/www\nls -la\npg_dump -h db.example.com -U backup_admin app > /opt/database_backup.sql\n",
        "log_file": '192.0.2.10 - - [01/Jan/2026:12:00:00 +0000] "GET /admin HTTP/1.1" 200 512\n',
        "docker_config": json.dumps(
            {
                "auths": {
                    "registry.example.com": {
                        "auth": base64.b64encode(
                            f"backup_admin:{password}".encode()
                        ).decode()
                    }
                }
            }
        )
        + "\n",
    }
    return templates.get(
        token_type,
        f"Operations backup notes\n\nBackup endpoint: https://backup.example.com\nAccount: backup_admin\nRecovery password: {password}\n",
    )
