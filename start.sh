#!/usr/bin/env bash
# ModAgent 一键启动（macOS / Linux）
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  ModAgent 数学建模智能体 - 一键启动"
echo "============================================"

# Python 依赖
python3 -c "import fastapi, uvicorn, requests, yaml" 2>/dev/null || pip3 install -r requirements.txt

# 前端依赖
[ -d frontend/node_modules ] || (cd frontend && npm install)

echo "前端: http://localhost:3000"
echo "后端: http://localhost:8000"
echo "按 Ctrl+C 停止"

# 启动后端
python3 api.py &
API_PID=$!
trap "kill $API_PID 2>/dev/null" EXIT

# 启动前端
(cd frontend && npm run dev)
