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
            "Use an HTTP(S) URL without embedded credentials, query or fragment"
        )
    if args.ca_file and (
        not args.ca_file.startswith("/") or any(c in args.ca_file for c in "\r\n\0\"' ")
    ):
        parser.error(
            "CA file must be an absolute Linux path without whitespace or quotes"
        )
    values = read_env(Path(args.env))
    secret = values.get("AGENT_SECRET", "")
    if len(secret) < 32 or any(c in secret + args.url for c in "\r\n\0\"'"):
        parser.error("Set an AGENT_SECRET of at least 32 characters in .env first")
    output = Path(args.output)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as config:
        config.write(f"GATEWAY_URL={args.url}\nAGENT_SECRET={secret}\n")
        if args.node_ip:
            config.write(f"NODE_IP={args.node_ip}\n")
        if args.hostname:
            config.write(f"NODE_HOSTNAME={args.hostname}\n")
        config.write("AGENT_ALLOWED_DIRS=/etc,/var/www,/home,/opt\n")
        config.write("AGENT_AUTO_DIRS=/var/www/html,/var/www,/opt,/home,/etc\n")
        config.write("AGENT_STATE_FILE=/var/lib/luregenix-agent/agent.json\n")
        config.write("HEARTBEAT_INTERVAL=60\nTASK_POLL_INTERVAL=10\n")
        config.write("AGENT_FILE_MODE=0644\n")
        if args.ca_file:
            config.write(f"AGENT_CA_FILE={args.ca_file}\n")


if __name__ == "__main__":
    main()
