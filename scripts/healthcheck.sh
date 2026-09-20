#!/usr/bin/env bash
# Nous Health Check
set -euo pipefail
URL="${1:-http://localhost:8770}"
echo "Checking $URL..."
curl -sf "$URL/health" > /dev/null && echo "PASS Brain is healthy" || { echo "FAIL Brain unreachable"; exit 1; }
echo "PASS Health check passed"
