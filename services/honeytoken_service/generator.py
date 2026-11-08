"""Сборка файлов из проверенных данных LLM или локальных шаблонов."""

import base64
import io
import json
import os
import secrets
import tarfile
from datetime import datetime
from pathlib import Path
from threading import Lock

import requests

from llm import (
    DatabaseContent, DocumentContent, EnvironmentContent, GenerationError,
    HistoryContent, LogContent, RegistryContent, check_model, generate_content,
)

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

font_lock = Lock()


def generation_status():
    """Проверяет наличие модели в Ollama; шаблоны доступны независимо от неё."""
    mode = os.getenv("GENERATION_MODE", "template")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    try:
        info, warning = check_model()
        installed = info is not None
        llm_ready = installed and not warning
    except GenerationError as exc:
        installed = False
        warning = str(exc)
        llm_ready = False
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        installed = False
        warning = "Нет соединения с Ollama."
        llm_ready = False
    return {
        "mode": mode,
        "model": model,
        "ready": mode == "template" or (mode == "llm" and llm_ready),
        "llm_ready": llm_ready,
        "installed": installed,
        "warning": warning,
    }


def generate_file(token_type, mode=None, description="", name="", filename=""):
    """Возвращает байты файла и источник: локальные ключи, шаблон или LLM."""
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

    if mode == "template":
        content = template_content(token_type)
    else:
        content = render_content(generate_content(token_type, description, name, filename))
    payload = encode_content(token_type, content)
    if len(payload) > 1_000_000:
        raise GenerationError("Размер файла превышает ограничение агента (1 МБ).")
    return payload, mode


def sql_value(value):
    """Кодирует значение дампа как литерал; текст модели никогда не становится SQL-командой."""
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + value.replace("'", "''") + "'"


def render_content(data):
    """Собирает синтаксис формата самостоятельно, сохраняя сгенерированные моделью данные."""
    if isinstance(data, DocumentContent):
        return data
    if isinstance(data, DatabaseContent):
        parts = ["-- PostgreSQL database backup", "SET standard_conforming_strings = on;", "BEGIN;", ""]
        for table in data.tables:
            columns = [f'    "{column.name}" {column.type}' for column in table.columns]
            parts.append(f'CREATE TABLE "{table.name}" (\n    "id" INTEGER PRIMARY KEY,\n' + ",\n".join(columns) + "\n);")
            names = ', '.join(['"id"'] + [f'"{column.name}"' for column in table.columns])
            rows = ["    (" + ", ".join(sql_value(cell) for cell in [index, *row]) + ")"
                    for index, row in enumerate(table.rows, 1)]
            parts.append(f'INSERT INTO "{table.name}" ({names}) VALUES\n' + ",\n".join(rows) + ";\n")
        return "\n".join(parts) + "\nCOMMIT;\n"
    if isinstance(data, EnvironmentContent):
        # Кавычки защищают пробелы и '#'; конфигурация остаётся данными, а не shell-скриптом.
        return "\n".join(item.key + "=" + json.dumps(item.value, ensure_ascii=False) for item in data.settings) + "\n"
    if isinstance(data, RegistryContent):
        auth = base64.b64encode(f"{data.username}:{data.password}".encode()).decode("ascii")
        return json.dumps({"auths": {data.registry: {"auth": auth}}}, indent=2) + "\n"
    if isinstance(data, HistoryContent):
        return "\n".join(data.commands) + "\n"
    if isinstance(data, LogContent):
        lines = []
        for entry in data.entries:
            timestamp = datetime.fromisoformat(entry.timestamp).strftime("%d/%b/%Y:%H:%M:%S %z")
            lines.append(f'{entry.ip} - - [{timestamp}] "{entry.method} {entry.path} HTTP/1.1" {entry.status} {entry.bytes}')
        return "\n".join(lines) + "\n"
    raise GenerationError("Модель вернула неподдерживаемую структуру файла.")


def pdf_fonts():
    """Регистрирует шрифт с кириллицей; он устанавливается при сборке сервиса."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    with font_lock:
        if "LureSans" not in pdfmetrics.getRegisteredFontNames():
            directory = Path("/usr/share/fonts/truetype/dejavu")
            if not (directory / "DejaVuSans.ttf").is_file():
                raise GenerationError("Не найден шрифт PDF. Пересоберите honeytoken_service.")
            pdfmetrics.registerFont(TTFont("LureSans", str(directory / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("LureSans-Bold", str(directory / "DejaVuSans-Bold.ttf")))
            pdfmetrics.registerFontFamily("LureSans", normal="LureSans", bold="LureSans-Bold")


def encode_content(token_type, content):
    """Упаковывает текст в выбранный формат, не исполняя SQL и историю команд."""
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
        if isinstance(content, DocumentContent):
            document.core_properties.title = content.title
            document.add_heading(content.title, 0)
            for section in content.sections:
                document.add_heading(section.heading, 1)
                for paragraph in section.text.split("\n"):
                    if paragraph.strip():
                        document.add_paragraph(paragraph.strip())
        else:
            for line in content.splitlines():
                document.add_paragraph(line)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()
    if token_type == "pdf":
        from html import escape

        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        buffer = io.BytesIO()
        pdf_fonts()
        styles = getSampleStyleSheet()
        body = ParagraphStyle("RussianBody", parent=styles["BodyText"], fontName="LureSans", fontSize=11, leading=16, spaceAfter=9)
        title = ParagraphStyle("RussianTitle", parent=body, fontName="LureSans-Bold", fontSize=18, leading=24, spaceAfter=18)
        heading = ParagraphStyle("RussianHeading", parent=body, fontName="LureSans-Bold", fontSize=13, leading=18, spaceBefore=10)
        paragraphs = []
        if isinstance(content, DocumentContent):
            paragraphs.append(Paragraph(escape(content.title), title))
            for section in content.sections:
                paragraphs.append(Paragraph(escape(section.heading), heading))
                paragraphs.append(Paragraph(escape(section.text).replace("\n", "<br/>"), body))
            document_title = content.title
        else:
            for line in content.splitlines():
                if line.strip():
                    paragraphs.extend([Paragraph(escape(line), body), Spacer(1, 8)])
            document_title = "Рабочие заметки"
        SimpleDocTemplate(buffer, title=document_title, author="", leftMargin=48, rightMargin=48).build(paragraphs)
        return buffer.getvalue()
    if isinstance(content, DocumentContent):
        content = content.title + "\n\n" + "\n\n".join(section.heading + "\n" + section.text for section in content.sections) + "\n"
    return content.encode("utf-8")


def template_content(token_type):
    """Создаёт правдоподобный шаблон с вымышленными реквизитами и случайным секретом."""
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
