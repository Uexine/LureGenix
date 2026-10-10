"""Create a protected host-agent config from the project's dotenv file."""

import argparse
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from setup_env import read_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ca-file", default="")
    parser.add_argument("--node-ip", default="")
    parser.add_argument("--hostname", default="")
    args = parser.parse_args()
    if args.node_ip:
        try:
            args.node_ip = str(ipaddress.ip_address(args.node_ip))
        except ValueError:
            parser.error("Укажите корректный IP-адрес сервера в --node-ip")
    if args.hostname and (
        len(args.hostname) > 253
        or any(not (c.isascii() and (c.isalnum() or c in "-._")) for c in args.hostname)
    ):
        parser.error(
            "Hostname должен содержать только латинские буквы, цифры, '.', '_' и '-'"
        )
    url = urlsplit(args.url)
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        parser.error(
            "Укажите HTTP(S)-адрес без логина, пароля, параметров запроса и фрагмента."
        )
    if args.ca_file and (
        not args.ca_file.startswith("/") or any(c in args.ca_file for c in "\r\n\0\"' ")
    ):
        parser.error(
            "Путь к сертификату CA должен быть абсолютным Linux-путём без пробелов и кавычек."
        )
    try:
        values = read_env(Path(args.env))
        settings = read_env(
            Path(__file__).resolve().parents[1] / "agent/agent.env.example"
        )
    except OSError:
        parser.error(
            "Не удалось прочитать конфигурацию. Проверьте пути и права доступа."
        )
    secret = values.get("AGENT_SECRET", "")
    if len(secret) < 32 or any(c in secret + args.url for c in "\r\n\0\"'"):
        parser.error("Сначала задайте AGENT_SECRET длиной не менее 32 символов в .env.")
    settings.update(
        GATEWAY_URL=args.url,
        AGENT_SECRET=secret,
        NODE_IP=args.node_ip,
        NODE_HOSTNAME=args.hostname,
        AGENT_CA_FILE=args.ca_file,
    )
    output = Path(args.output)
    try:
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.error("Файл конфигурации уже существует. Укажите другое имя в --output.")
    except OSError:
        parser.error(
            "Не удалось создать конфигурацию. Проверьте каталог и права доступа."
        )
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as config:
        for key, value in settings.items():
            config.write(f"{key}={value}\n")
    print(f"Конфигурация агента создана: {output}. Не публикуйте этот файл.")


if __name__ == "__main__":
    main()
