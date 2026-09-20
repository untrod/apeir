#!/bin/bash

# Nous Learning Engine — 一键迁移脚本

# 用法:
#   从旧服务器打包:
#     cd /opt && tar czf nous_backup.tar.gz nous/
#     scp nous_backup.tar.gz user@new-server:/opt/
#
#   在新服务器上:
#     cd /opt && tar xzf nous_backup.tar.gz
#     cd /opt/nous && bash migrate.sh

set -e

echo "=== Nous 学习引擎迁移 ==="

# 1. 安装系统依赖
echo "[1/4] 安装系统包..."
apt-get update -qq
apt-get install -y python3 python3-pip wireguard-tools curl 2>/dev/null || true

# 2. 安装 Python 依赖
echo "[2/4] 安装 Python 包..."
pip3 install --break-system-packages -r requirements.txt 2>/dev/null || \
  pip3 install faster-whisper edge-tts PyPDF2 pdfplumber python-docx

# 3. 配置检查
echo "[3/4] 检查配置..."
if [ ! -f config.local.json ]; then
    echo "⚠️  缺少 config.local.json,请从旧服务器复制或手动创建"
fi
if [ ! -f .env ]; then
    echo "⚠️  缺少 .env,请从旧服务器复制(含 API Key)"
fi

# 4. 启动服务
echo "[4/4] 启动 Brain..."
pkill -f brain.py 2>/dev/null || true
nohup python3 brain.py > /dev/null 2>&1 &
sleep 2

if pgrep -f brain.py > /dev/null; then
    echo ""
    echo "✅ 迁移完成!"
    echo "   Brain: http://$(hostname -I | awk '{print $1}'):8770"
    echo "   学习仪表盘: http://$(hostname -I | awk '{print $1}'):8770/learn/dashboard"
    echo "   上传页面: 浏览器打开 learn_upload.html"
    echo ""
    echo "⚠️  请检查:"
    echo "   1. config.local.json 中的 AUTH_TOKEN 和 LLM_API_KEY"
    echo "   2. WireGuard 配置(如需手表连接)"
    echo "   3. 防火墙开放 8770 端口"
else
    echo "❌ Brain 启动失败,请检查日志: tail /opt/nous/brain.log"
fi
