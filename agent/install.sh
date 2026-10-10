#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    printf 'Run with sudo: sudo bash agent/install.sh\n' >&2
    exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
config_file="${1:-}"
if [[ -n "$config_file" ]]; then
    [[ -f "$config_file" ]] || { echo "Agent configuration file not found" >&2; exit 1; }
    grep -Eq '^AGENT_SECRET=.+$' "$config_file" || { echo "AGENT_SECRET is required" >&2; exit 1; }
    grep -Eq '^GATEWAY_URL=https?://.+$' "$config_file" || { echo "GATEWAY_URL is required" >&2; exit 1; }
fi
command -v python3 >/dev/null
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10 or newer is required"'
command -v systemctl >/dev/null
install -d -m 0755 /opt/luregenix-agent
install -d -m 0700 /var/lib/luregenix-agent
install -m 0644 "${script_dir}/agent.py" /opt/luregenix-agent/agent.py
install -m 0644 "${script_dir}/requirements.txt" /opt/luregenix-agent/requirements.txt
python3 -m venv /opt/luregenix-agent/venv
/opt/luregenix-agent/venv/bin/python -m pip install --timeout 120 --retries 5 -r /opt/luregenix-agent/requirements.txt
if [[ -n "$config_file" ]]; then
    install -m 0600 "$config_file" /etc/luregenix-agent.env
fi
if [[ ! -e /etc/luregenix-agent.env ]]; then
    install -m 0600 "${script_dir}/agent.env.example" /etc/luregenix-agent.env
fi
install -m 0644 "${script_dir}/luregenix-agent.service" /etc/systemd/system/luregenix-agent.service
systemctl daemon-reload
systemctl enable luregenix-agent
if [[ -n "$config_file" ]]; then
    started_at="$(date +%s)"
    systemctl restart luregenix-agent
    sleep 3
    if ! systemctl is-active --quiet luregenix-agent; then
        journalctl -u luregenix-agent -n 30 --no-pager >&2
        exit 1
    fi
    for attempt in {1..30}; do
        if python3 -c 'import json,sys; data=json.load(open("/var/lib/luregenix-agent/agent.json")); assert data.get("node_id") and data.get("last_registration",0) >= int(sys.argv[1])' "$started_at" 2>/dev/null; then
            printf 'Agent service is running and registered with the application.\n'
            exit 0
        fi
        sleep 2
    done
    printf 'Agent service started but registration failed. Check URL, TLS, enrollment secret and migrations.\n' >&2
    journalctl -u luregenix-agent -n 30 --no-pager >&2
    exit 1
fi
printf 'Set GATEWAY_URL and AGENT_SECRET: sudoedit /etc/luregenix-agent.env\n'
printf 'Start or update the agent: sudo systemctl restart luregenix-agent\n'
