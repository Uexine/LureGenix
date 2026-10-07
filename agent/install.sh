#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    printf 'Run with sudo: sudo bash agent/install.sh\n' >&2
    exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null
command -v systemctl >/dev/null
install -d -m 0755 /opt/luregenix-agent
install -d -m 0700 /var/lib/luregenix-agent
install -m 0644 "${script_dir}/agent.py" /opt/luregenix-agent/agent.py
install -m 0644 "${script_dir}/requirements.txt" /opt/luregenix-agent/requirements.txt
python3 -m venv /opt/luregenix-agent/venv
/opt/luregenix-agent/venv/bin/python -m pip install -r /opt/luregenix-agent/requirements.txt
if [[ ! -e /etc/luregenix-agent.env ]]; then
    install -m 0600 "${script_dir}/agent.env.example" /etc/luregenix-agent.env
fi
install -m 0644 "${script_dir}/luregenix-agent.service" /etc/systemd/system/luregenix-agent.service
systemctl daemon-reload
systemctl enable luregenix-agent
printf 'Set GATEWAY_URL and AGENT_SECRET: sudoedit /etc/luregenix-agent.env\n'
printf 'Start or update the agent: sudo systemctl restart luregenix-agent\n'
