"""Create a protected host-agent config from the project's dotenv file."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    values = {}
    for line in Path(args.env).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    secret = values.get("AGENT_SECRET", "")
    if not secret or any(c in secret + args.url for c in "\r\n\0"):
        parser.error("Set a nonempty AGENT_SECRET in .env first")
    output = Path(args.output)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as config:
        config.write(f"GATEWAY_URL={args.url}\nAGENT_SECRET={secret}\n")
        config.write("AGENT_ALLOWED_DIRS=/etc,/var/www,/home,/opt\n")
        config.write("AGENT_AUTO_DIRS=/var/www/html,/var/www,/opt,/home,/etc\n")
        config.write("AGENT_STATE_FILE=/var/lib/luregenix-agent/agent.json\n")
        config.write("HEARTBEAT_INTERVAL=60\nTASK_POLL_INTERVAL=10\n")


if __name__ == "__main__":
    main()
