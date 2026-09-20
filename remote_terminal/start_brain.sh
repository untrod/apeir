#!/usr/bin/env bash
# Brain 启动脚本(服务器用)。
# 从 600 权限的 .env 文件加载敏感配置(API Key / token / 签名密钥),
# 这些值以环境变量传入,绝不写进 config.local.json 明文落盘。
#
# 用法:
#   1. cp .env.example .env && chmod 600 .env  然后编辑 .env 填入真实值
#   2. ./start_brain.sh           # 前台运行
#   或 nohup ./start_brain.sh > brain.log 2>&1 &   # 后台运行

set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE="${NOUS_ENV_FILE:-./.env}"
if [ -f "$ENV_FILE" ]; then
    # 校验权限:必须 600,防止其他用户读到密钥
    perm=$(stat -c "%a" "$ENV_FILE" 2>/dev/null || echo "")
    if [ "$perm" != "600" ]; then
        echo "警告: $ENV_FILE 权限是 $perm,建议 chmod 600 $ENV_FILE" >&2
    fi
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    echo "已从 $ENV_FILE 加载环境变量"
else
    echo "警告: 未找到 $ENV_FILE,将仅依赖系统环境变量 / config.local.json" >&2
fi

exec python3 brain.py
