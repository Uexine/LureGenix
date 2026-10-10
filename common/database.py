import os
from datetime import datetime, timezone

import psycopg2


def connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        database=os.getenv("DB_NAME", "luregenix"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        connect_timeout=5,
    )


def utc_timestamp(value):
    if not isinstance(value, datetime):
        return value
    # Old TIMESTAMP columns contain UTC even though PostgreSQL returns naive values.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
