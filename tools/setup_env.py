"""Подготовка и восстановление .env без исполнения его содержимого как shell-кода."""

import argparse
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path


def read_env(path):
    """Читает простые KEY=value, игнорируя комментарии и снимая парные кавычки."""
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                values[key.strip()] = value
    return values


def configure(path, example, lan=False, volume=None, local=False, recovered=None):
    """Дополняет конфигурацию без смены заполненных секретов и атомарно сохраняет .env."""
    defaults = read_env(example)
    if (
        not {"DB_NAME", "DB_USER", "APP_DB_USER", "JWT_SECRET", "AGENT_SECRET"}
        <= defaults.keys()
    ):
        raise ValueError(
            "Не найден корректный .env.example. Запускайте настройку из корня проекта."
        )
    values = {**defaults, **(recovered or {})}
    values.update(
        {
            key: value
            for key, value in read_env(path).items()
            if value or key not in (recovered or {})
        }
    )
    # Пример задаёт поддерживаемые ключи; старые настройки провайдеров не переносим.
    values = {key: values[key] for key in defaults}
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
            "POSTGRES_DATA_VOLUME отличается от тома существующей БД. Смена тома отменена."
        )
    if len(values["JWT_SECRET"]) < 32 or len(values["AGENT_SECRET"]) < 32:
        raise ValueError(
            "JWT_SECRET и AGENT_SECRET должны содержать не менее 32 символов."
        )
    if values.get("APP_DB_USER") == values.get("DB_USER"):
        raise ValueError(
            "APP_DB_USER должен отличаться от владельца PostgreSQL DB_USER."
        )
    if not re.fullmatch(r"luregenix_[a-z0-9_]{1,40}", values.get("APP_DB_USER", "")):
        raise ValueError("APP_DB_USER должен быть отдельной ролью вида luregenix_*.")
    if any(
        "\n" in value or "\r" in value or "\0" in value or "$" in value or "#" in value
        for value in values.values()
    ):
        raise ValueError(
            "Настройки не должны содержать переносы строк, NUL, '$' или '#'. Используйте URL-безопасные секреты."
        )
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            for key, value in values.items():
                stream.write(f"{key}={value}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return values, created_password


def docker_output(*args):
    """Читает вывод Docker с таймаутом, не выводя реквизиты контейнеров в консоль."""
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=10
    ).stdout


def existing_database_volume():
    """Находит единственный том БД проекта, чтобы обновление не создало пустую базу рядом."""
    try:
        containers = docker_output(
            "ps",
            "--all",
            "--filter",
            "label=com.docker.compose.project=luregenix",
            "--filter",
            "label=com.docker.compose.service=postgres",
            "--format",
            "{{.ID}}",
        ).split()
        if not containers:
            return None
        if len(containers) != 1:
            raise ValueError(
                "Найдено несколько контейнеров БД. Устраните дубликат перед настройкой."
            )
        volume = docker_output(
            "inspect",
            "--format",
            '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}',
            containers[0],
        ).strip()
    except FileNotFoundError:
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(
            "Не удалось проверить существующую БД. Проверьте доступ к Docker."
        ) from exc
    if not volume:
        raise ValueError(
            "Существующая БД использует bind mount. Сохраните это подключение явно в Compose."
        )
    return volume


def recover_container_env():
    """Восстанавливает конфигурацию только из контейнеров LureGenix, скрывая значения секретов."""
    try:
        ids = docker_output(
            "ps",
            "--all",
            "--filter",
            "label=com.docker.compose.project=luregenix",
            "--format",
            "{{.ID}}",
        ).split()
        if not ids:
            raise ValueError(
                "Нет контейнеров LureGenix для восстановления .env. Нужна резервная копия."
            )
        containers = json.loads(docker_output("inspect", *ids))
        if not isinstance(containers, list):
            raise ValueError("Docker вернул некорректные сведения о контейнерах.")
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(
            "Не удалось прочитать контейнеры Docker для восстановления .env."
        ) from exc

    restored = {}
    owners = 0
    app_services = {
        "auth_service",
        "honeytoken_service",
        "event_service",
        "discovery_service",
    }
    settings = {
        "JWT_SECRET",
        "AGENT_SECRET",
        "ADMIN_SECRET",
        "BOOTSTRAP_ADMIN_USERNAME",
        "BOOTSTRAP_ADMIN_PASSWORD",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "GENERATION_MODE",
        "LLM_TIMEOUT_SECONDS",
        "DISCOVERY_ALLOWED_CIDRS",
        "EVENT_RETENTION_DAYS",
    }

    def remember(key, value):
        """Сохраняет настройку, отклоняя конфликтующие значения в разных контейнерах."""
        if not value:
            return
        if key in restored and restored[key] != value:
            raise ValueError(
                f"В контейнерах разные значения {key}. Восстановите .env из резервной копии."
            )
        restored[key] = value

    for container in containers:
        config = container.get("Config") or {}
        labels = config.get("Labels") or {}
        if labels.get("com.docker.compose.project") != "luregenix":
            continue
        service = labels.get("com.docker.compose.service")
        if service not in app_services | {"postgres", "database_init", "gateway"}:
            continue
        env = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
        if service == "postgres":
            owners += 1
            for key, source in {
                "DB_NAME": "POSTGRES_DB",
                "DB_USER": "POSTGRES_USER",
                "DB_PASSWORD": "POSTGRES_PASSWORD",
            }.items():
                remember(key, env.get(source))
        elif service == "database_init":
            for key in (
                "DB_NAME",
                "DB_USER",
                "DB_PASSWORD",
                "APP_DB_USER",
                "APP_DB_PASSWORD",
            ):
                remember(key, env.get(key))
        elif service in app_services:
            remember("DB_NAME", env.get("DB_NAME"))
            # Старые версии работали владельцем БД; им будет создана отдельная роль приложения.
            if env.get("DB_USER", "").startswith("luregenix_"):
                remember("APP_DB_USER", env["DB_USER"])
                remember("APP_DB_PASSWORD", env.get("DB_PASSWORD"))
        for key in settings:
            remember(key, env.get(key))
    if owners != 1:
        raise ValueError(
            "Для восстановления нужен ровно один контейнер PostgreSQL проекта."
        )
    missing = {
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "JWT_SECRET",
        "AGENT_SECRET",
    } - restored.keys()
    if missing:
        raise ValueError(
            "В контейнерах отсутствуют настройки: "
            + ", ".join(sorted(missing))
            + ". Нужна резервная копия .env."
        )
    return restored


def main():
    """Обрабатывает режим сети и восстановление, сохраняя привязку к существующей БД."""
    parser = argparse.ArgumentParser()
    network = parser.add_mutually_exclusive_group()
    network.add_argument("--lan", action="store_true")
    network.add_argument("--local", action="store_true")
    parser.add_argument("--volume")
    parser.add_argument(
        "--recover-env",
        action="store_true",
        help="Восстановить потерянный .env из сохранившихся контейнеров, не изменяя БД",
    )
    args = parser.parse_args()
    # Сохраняем старые анонимные тома при переходе на именованное хранилище.
    try:
        volume = existing_database_volume()
    except ValueError as exc:
        parser.error(str(exc))
    if volume and not Path(".env").is_file() and not args.recover_env:
        parser.error(
            "Есть существующая БД, но нет .env. Восстановите файл из копии или выполните python3 tools/setup_env.py --recover-env."
        )
    if args.volume and volume and args.volume != volume:
        parser.error("Выбранный том не совпадает с томом существующей БД.")
    try:
        recovered = recover_container_env() if args.recover_env else None
        current = read_env(Path(".env"))
        if recovered:
            conflicts = [
                key
                for key, value in recovered.items()
                if current.get(key) and current[key] != value
            ]
            if conflicts:
                raise ValueError(
                    "Настройки .env отличаются от контейнеров: "
                    + ", ".join(sorted(conflicts))
                    + ". Файл не изменён."
                )
        if (
            volume
            and not recovered
            and any(
                not current.get(key) for key in ("DB_NAME", "DB_USER", "DB_PASSWORD")
            )
        ):
            raise ValueError(
                "В .env не заполнены настройки существующей БД. Восстановите их или используйте --recover-env. Новые пароли БД не созданы."
            )
        values, created = configure(
            Path(".env"),
            Path(".env.example"),
            args.lan,
            volume or args.volume,
            args.local,
            recovered=recovered,
        )
    except ValueError as exc:
        parser.error(str(exc))
    except OSError:
        parser.error("Не удалось сохранить .env. Проверьте каталог и права доступа.")
    print("Конфигурация готова: .env. Не публикуйте и не передавайте этот файл.")
    if args.recover_env:
        print(
            "Настройки восстановлены из контейнеров. Существующая БД и пароли не удалялись."
        )
    if created:
        print("Первый администратор:", values.get("BOOTSTRAP_ADMIN_USERNAME", "admin"))
        print("Пароль первого входа:", values["BOOTSTRAP_ADMIN_PASSWORD"])
        print("Пароли существующих администраторов НЕ меняются.")
    if args.lan:
        print(
            "HTTP доступен в локальной сети. Используйте только в изолированном стенде; в других сетях нужен HTTPS."
        )


if __name__ == "__main__":
    main()
