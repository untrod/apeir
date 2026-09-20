#!/usr/bin/env bash
# Nous Brain deployment script.
# Required:
#   export NOUS_PACKAGE_URL="http://<package-host>:9999/nous_deploy.tar.gz"
# Optional:
#   export NOUS_HOME="/opt/nous"
set -e

echo "=== 第1步：安装依赖 ==="
apt-get update -qq && apt-get install -y python3 wireguard-tools 2>/dev/null || true

echo "=== 第2步：部署代码 ==="
NOUS_HOME="${NOUS_HOME:-/opt/nous}"
NOUS_PACKAGE_URL="${NOUS_PACKAGE_URL:-}"
if [ -z "$NOUS_PACKAGE_URL" ]; then
    echo "❌ 请先设置 NOUS_PACKAGE_URL，例如 http://<package-host>:9999/nous_deploy.tar.gz"
    exit 1
fi

mkdir -p "$NOUS_HOME"
cd "$NOUS_HOME"
wget -O /tmp/nous_deploy.tar.gz "$NOUS_PACKAGE_URL" 2>/dev/null || {
    echo "❌ 无法下载部署包，请确认 NOUS_PACKAGE_URL 可访问"
    exit 1
}
tar xzf /tmp/nous_deploy.tar.gz -C "$NOUS_HOME/"
chmod +x "$NOUS_HOME/start_brain.sh"

echo "=== 第3步：创建 .env (如不存在) ==="
if [ ! -f "$NOUS_HOME/.env" ]; then
    cat > "$NOUS_HOME/.env" << 'ENVEOF'
export NOUS_LLM_API_KEY="sk-your-key-here"
export NOUS_AUTH_TOKEN="example-auth-token"
export NOUS_AGENT_SIGNING_SECRET="example-agent-signing-secret"
ENVEOF
    chmod 600 "$NOUS_HOME/.env"
    echo "⚠️ 请编辑 $NOUS_HOME/.env 填入真实值"
fi

echo "=== 第4步：创建 config.local.json (如不存在) ==="
if [ ! -f "$NOUS_HOME/config.local.json" ]; then
    cat > "$NOUS_HOME/config.local.json" << 'CONFEOF'
{
  "BRAIN_HOST": "",
  "BRAIN_PORT": "8770",
  "DEFAULT_DEVICE": "laptop",
  "AUTH_TOKEN": "example-auth-token",
  "LLM_API_URL": "https://api.example.com/v1/chat/completions",
  "LLM_MODEL": "example-model",
  "LLM_TIMEOUT": "60"
}
CONFEOF
    echo "⚠️ 请编辑 $NOUS_HOME/config.local.json 填入真实值"
fi

echo "=== 第5步：创建 systemd 服务 ==="
cat > /etc/systemd/system/nous-brain.service << SVCEOF
[Unit]
Description=Nous Brain
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$NOUS_HOME/.env
WorkingDirectory=$NOUS_HOME
ExecStart=/usr/bin/python3 $NOUS_HOME/brain.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload
systemctl enable nous-brain
systemctl start nous-brain
sleep 2

echo "=== 第6步：检查状态 ==="
systemctl status nous-brain --no-pager -l | head -10
echo ""
echo "=== brain.log ==="
tail -5 "$NOUS_HOME/brain.log"
echo ""
echo "✅ 部署完成!"
echo "   Brain: http://<NOUS_BRAIN_HOST>:8770"
echo "   Web面板: http://<NOUS_BRAIN_HOST>:8770/web"
