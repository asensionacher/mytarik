#!/usr/bin/env bash
# Stop the local stack and the local model processes.
set -u
ROOT="/home/seby/mytarik"

cd "$ROOT" || exit 1
pkill -f 'mytarik_llm_proxy.py' >/dev/null 2>&1 || true
pkill -x llama-server >/dev/null 2>&1 || true
docker compose stop
echo "Mytarik stopped."
