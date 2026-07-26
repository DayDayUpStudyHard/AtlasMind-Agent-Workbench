#!/bin/bash

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "=============================="
echo "  AtlasMind Agent Workbench"
echo "=============================="

echo "[1/4] Starting Java backend (:18080)..."
(cd "$ROOT/agent-server" && chmod +x mvnw && ./mvnw spring-boot:run) &

echo "[2/4] Starting admin app (:15173)..."
(cd "$ROOT/agent-admin" && npm run dev) &

echo "[3/4] Starting front app (:15174)..."
(cd "$ROOT/agent-front" && npm run dev) &

echo "[4/4] Starting Python AI service (:18088)..."
(cd "$ROOT/tools/chat-assistant/backend" && python run.py) &

echo ""
echo "Java backend: http://localhost:18080"
echo "Admin app:    http://localhost:15173"
echo "Front app:    http://localhost:15174"
echo "AI service:   http://localhost:18088"
echo ""

wait
