#!/usr/bin/env bash
set -Eeuo pipefail
trap 'printf "Deployment failed at line %s\n" "$LINENO" >&2' ERR

# Keep your existing TOKEN="..." assignment here, or enter it at the prompt.
TOKEN="${TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
    read -rsp "GitHub token: " TOKEN
    printf '\n'
fi
[[ -n "$TOKEN" ]] || { echo "Token is required" >&2; exit 1; }
REPO="https://${TOKEN}@github.com/Uexine/LureGenix.git"
BRANCH="dev"
PROJECT_DIR="${PROJECT_DIR:-$HOME/LureGenix}"

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
else
    command -v docker-compose >/dev/null
    COMPOSE=(docker-compose)
fi

git_retry() {
    local attempt
    for attempt in 1 2 3; do
        if git -c http.version=HTTP/1.1 "$@"; then return 0; fi
        sleep 3
    done
    return 1
}

mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"
if [[ ! -d .git ]]; then
    git_retry clone --branch "$BRANCH" "$REPO" .
else
    git_retry fetch "$REPO" "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
    git switch "$BRANCH"
    git_retry pull --ff-only "$REPO" "$BRANCH"
fi
[[ -f docker-compose.yml ]] || { echo "docker-compose.yml not found" >&2; exit 1; }
if [[ ! -f .env ]]; then
    cp .env.example .env
    chmod 600 .env
    echo "Created .env. Set DB settings, JWT_SECRET and AGENT_SECRET, then run again."
    exit 1
fi

# Use only this file and explicitly selected services, including on older checkouts.
python3 -c 'import pathlib; values=dict(line.strip().split("=",1) for line in pathlib.Path(".env").read_text().splitlines() if line.strip() and not line.lstrip().startswith("#") and "=" in line); missing=[key for key in ("JWT_SECRET", "AGENT_SECRET", "BOOTSTRAP_ADMIN_PASSWORD") if not values.get(key, "").strip()]; assert not missing, "Set these values in .env before deployment: " + ", ".join(missing); assert values["JWT_SECRET"] != "your_super_secret_key_here_min_32_chars", "Replace the example JWT_SECRET"'
COMPOSE+=(-p luregenix -f docker-compose.yml)
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d --no-deps postgres
wait_ready() {
    local attempt
    for attempt in {1..60}; do
        if "$@" >/dev/null 2>&1; then return 0; fi
        sleep 2
    done
    echo "Service readiness check failed" >&2
    return 1
}
wait_ready "${COMPOSE[@]}" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
for migration in db/0[2-9]_*.sql; do
    [[ -f "$migration" ]] || continue
    "${COMPOSE[@]}" exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$migration"
done
"${COMPOSE[@]}" up -d --build --no-deps auth_service honeytoken_service event_service discovery_service gateway
wait_ready "${COMPOSE[@]}" exec -T gateway python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)'
"${COMPOSE[@]}" up -d --no-deps nginx
if [[ "${INSTALL_HOST_AGENT:-0}" == "1" ]]; then
    command -v python3 >/dev/null
    agent_config_dir="$(mktemp -d)"
    trap 'rm -f "$agent_config_dir/agent.env"; rmdir "$agent_config_dir"' EXIT
    python3 tools/configure_agent.py --url "${AGENT_GATEWAY_URL:-http://10.124.21.50:8080}" --output "$agent_config_dir/agent.env"
    sudo bash agent/install.sh "$agent_config_dir/agent.env"
fi
"${COMPOSE[@]}" ps
echo "Application started: http://10.124.21.50:8080"
echo "Ollama was not started or downloaded. Generation mode is selected in .env."
echo "Use INSTALL_HOST_AGENT=1 to install/start the main server agent."
