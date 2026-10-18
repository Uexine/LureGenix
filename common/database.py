import os
from datetime import datetime, timezone

import psycopg2


def connect():
    """Открывает соединение с БД от имени роли текущего сервиса."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        connect_timeout=5,
    )


def utc_timestamp(value):
    """Преобразует дату в ISO 8601 UTC, остальные значения оставляет как есть."""
    if not isinstance(value, datetime):
        return value
    # Старые столбцы TIMESTAMP хранят UTC, но драйвер возвращает дату без часового пояса.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


"""Подключение к PostgreSQL и единый формат времени для API."""
