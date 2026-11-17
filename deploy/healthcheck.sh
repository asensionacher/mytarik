#!/usr/bin/env bash
# Read-only health check for the local stack.
set -u
fail=0

check() {
    name="$1"
    url="$2"
    if code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null); then
        if [ "$code" = "200" ]; then
            printf 'OK   %-18s %s\n' "$name" "$url"
            return
        fi
        printf 'FAIL %-18s %s (HTTP %s)\n' "$name" "$url" "$code"
    else
        printf 'FAIL %-18s %s (unreachable)\n' "$name" "$url"
    fi
    fail=1
}

check "Qdrant"    "http://127.0.0.1:6333/healthz"
check "TariffAI"  "http://127.0.0.1:8004/health"
check "Backend"   "http://127.0.0.1:8005/api/health"
check "Frontend"  "http://127.0.0.1:3000/"
check "Laguna"    "http://127.0.0.1:8084/v1/models"

exit "$fail"
