#!/usr/bin/env bash
# Start the complete local Mytarik stack and wait for health.
set -u
ROOT="/home/seby/mytarik"
PROXY="/home/seby/.local/bin/mytarik_llm_proxy.py"
LAGUNA="/home/seby/llama.cpp/start-laguna.sh"

cd "$ROOT" || exit 1

echo "[1/4] Docker services"
docker compose up -d || exit 1

echo "[2/4] Docker -> Laguna proxy"
if ! curl -sS --max-time 2 http://127.0.0.1:8082/v1/models >/dev/null 2>&1; then
    nohup "$PROXY" >/tmp/mytarik-llm-proxy.log 2>&1 &
fi

echo "[3/4] Laguna model"
if ! curl -sS --max-time 2 http://127.0.0.1:8084/v1/models >/dev/null 2>&1; then
    nohup "$LAGUNA" >/tmp/laguna-server.log 2>&1 &
fi

echo "[4/4] Waiting for health"
for _ in $(seq 1 90); do
    if curl -sS --max-time 2 http://127.0.0.1:8082/v1/models >/dev/null 2>&1 \
       && curl -sS --max-time 2 http://127.0.0.1:8005/api/health >/dev/null 2>&1; then
        echo "Mytarik is ready."
        echo "  Frontend : http://127.0.0.1:3000"
        echo "  Backend  : http://127.0.0.1:8005"
        echo "  Laguna   : http://127.0.0.1:8084/v1"
        exit 0
    fi
    sleep 5
done

echo "Mytarik did not become healthy; check /tmp/laguna-server.log and docker compose ps." >&2
exit 1
