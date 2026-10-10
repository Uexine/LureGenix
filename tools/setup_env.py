"""Prepare a private local configuration without executing dotenv as shell code."""

import argparse
import os
import re
import secrets
import subprocess
from pathlib import Path


def read_env(path):
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    return values


def configure(path, example, lan=False, volume=None, local=False):
    values = read_env(example)
    values.update(read_env(path))
    for key in (
        "DB_PASSWORD",
        "APP_DB_PASSWORD",
        "JWT_SECRET",
        "AGENT_SECRET",
        "ADMIN_SECRET",
    ):
        if (
            not values.get(key)
            or values[key] == "your_super_secret_key_here_min_32_chars"
        ):
            values[key] = secrets.token_hex(32)
    created_password = not values.get("BOOTSTRAP_ADMIN_PASSWORD")
    if created_password:
        values["BOOTSTRAP_ADMIN_PASSWORD"] = secrets.token_urlsafe(24)
    if lan:
        values["BIND_ADDRESS"] = "0.0.0.0"
    if local:
        values["BIND_ADDRESS"] = "127.0.0.1"
    if volume and not values.get("POSTGRES_DATA_VOLUME"):
        values["POSTGRES_DATA_VOLUME"] = volume
    if volume and values.get("POSTGRES_DATA_VOLUME") != volume:
        raise ValueError(
            "POSTGRES_DATA_VOLUME differs from the existing database; refusing to switch volumes"
        )
    if len(values["JWT_SECRET"]) < 32 or len(values["AGENT_SECRET"]) < 32:
        raise ValueError(
            "JWT_SECRET and AGENT_SECRET must contain at least 32 characters"
        )
    if values.get("APP_DB_USER") == values.get("DB_USER"):
        raise ValueError("APP_DB_USER must differ from the PostgreSQL owner DB_USER")
    if not re.fullmatch(r"luregenix_[a-z0-9_]{1,40}", values.get("APP_DB_USER", "")):
        raise ValueError("APP_DB_USER must be a dedicated luregenix_* role")
    if any(
        "\n" in value or "\r" in value or "\0" in value or "$" in value or "#" in value
        for value in values.values()
    ):
        raise ValueError(
            "Configuration values must not contain newline, NUL, '$' or '#'; use URL-safe secrets"
        )
    temporary = path.with_suffix(".env.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return values, created_password


def existing_database_volume():
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--all",
                "--filter",
                "label=com.docker.compose.project=luregenix",
                "--filter",
                "label=com.docker.compose.service=postgres",
                "--format",
                "{{.ID}}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        containers = result.stdout.split()
        if not containers:
            return None
        if len(containers) != 1:
            raise ValueError(
                "Multiple database containers found; resolve the duplicate before configuring"
            )
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}',
                containers[0],
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except FileNotFoundError:
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(
            "Cannot inspect the existing Docker database; check Docker access"
        ) from exc
    volume = result.stdout.strip()
    if not volume:
        raise ValueError(
            "Existing database uses a bind mount; preserve it explicitly in Compose"
        )
    return volume


def main():
    parser = argparse.ArgumentParser()
    network = parser.add_mutually_exclusive_group()
    network.add_argument("--lan", action="store_true")
    network.add_argument("--local", action="store_true")
    parser.add_argument("--volume")
    args = parser.parse_args()
    # Keep old anonymous volumes when moving an existing installation to named storage.
    try:
        volume = existing_database_volume()
    except ValueError as exc:
        parser.error(str(exc))
    if volume and not Path(".env").is_file():
        parser.error(
            "Restore the existing .env before configuring an existing database"
        )
    if args.volume and volume and args.volume != volume:
        parser.error("The selected volume does not match the existing database")
    try:
        values, created = configure(
            Path(".env"),
            Path(".env.example"),
            args.lan,
            volume or args.volume,
            args.local,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print("Configuration ready: .env (private; do not commit or share)")
    if created:
        print(
            "First-run administrator:", values.get("BOOTSTRAP_ADMIN_USERNAME", "admin")
        )
        print("First-run password:", values["BOOTSTRAP_ADMIN_PASSWORD"])
        print("Existing administrators in the database will NOT be reset.")
    if args.lan:
        print(
            "HTTP is exposed on the LAN. Use only for a trusted isolated lab; use TLS for other networks."
        )


if __name__ == "__main__":
    main()
