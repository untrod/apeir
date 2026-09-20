# -*- coding: utf-8 -*-
"""
集中配置 —— 所有地址、端口、密钥、模型都从这里取。
代码里只引用变量,不出现任何硬编码的真实值。

配置来源优先级(高→低):
  1. 环境变量(NOUS_开头,如 NOUS_LLM_API_KEY)
  2. 配置文件 config.local.json(同目录,不入版本控制)
  3. 本文件里的默认值(全部为空/占位,缺配置时给清晰报错)

首次使用时需要在 App 设置页(或 config.local.json / 环境变量)填入真实值。
"""

import json
import os


# 加载 .env(如果存在)——把 NOUS_XXX 环境变量注入 os.environ
# 为什么用 .env:服务器上把敏感密钥(AGENT_SIGNING_SECRET 等)放 .env(chmod 600),
# 不落进 config.local.json,降低泄漏面。零依赖手写解析,不引 python-dotenv。
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                # 兼容 "export KEY=val" 格式(shell 风格 .env)
                if key.startswith("export "):
                    key = key[len("export "):].strip()
                val = val.strip().strip('"').strip("'")
                # 已存在的环境变量优先(不覆盖)
                if key and key not in os.environ:
                    os.environ[key] = val
        print("已从 ./.env 加载环境变量")
    except Exception as e:
        print(f"加载 .env 失败(忽略): {e}")


_load_dotenv()

# 加载配置文件(如果存在)
_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.json")
_file_config = {}
try:
    if os.path.exists(_CONFIG_FILE):
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            _file_config = json.load(f)
except Exception:
    pass


def _get(key: str, default=""):
    """按优先级取配置:环境变量 NOUS_XXX > config.local.json > 默认值。"""
    return os.environ.get(f"NOUS_{key}", _file_config.get(key, default))


def save_config(updates: dict):
    """
    保存配置到 config.local.json(App 设置页 POST /config 调用)。
    只更新传入的字段,不覆盖其他。
    """
    global _file_config
    existing = {}
    try:
        if os.path.exists(_CONFIG_FILE):
            with open(_CONFIG_FILE, encoding="utf-8") as f:
                existing = json.load(f)
    except Exception:
        pass
    existing.update(updates)
    _file_config = existing
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    # 刷新模块级变量
    _reload_all()


def _reload_all():
    """从配置源重新加载所有变量。save_config 后调用。"""
    global BRAIN_HOST, BRAIN_PORT, BRAIN_MAX_STEPS, BRAIN_IDLE_LIMIT, BRAIN_STEP_WARNING
    global AGENT_HOST, AGENT_PORT, RELAY_PRIMARY, RELAY_HOST
    global DEFAULT_DEVICE, DEVICES_FILE, CLIENTS_FILE, AGENT_SIGNING_SECRET
    global AUTH_TOKEN, AUTH_TOKEN_ENCRYPTED
    global LLM_API_URL, LLM_API_KEY, LLM_API_KEY_ENCRYPTED, LLM_MODEL, LLM_TIMEOUT
    global VISION_API_URL, VISION_API_KEY, VISION_MODEL
    global COMMAND_TIMEOUT, BIND_RETRY_SECONDS
    global ALLOWED_IPS, RATE_LIMIT_PER_MINUTE
    global SAFETY_MODE, SAFETY_WHITELIST_COMMANDS, SAFETY_READONLY_COMMANDS
    global PHONE_SSH_IP, PHONE_SSH_PORT, PHONE_SSH_USER
    global PHONE_CONTROL_HOST, PHONE_CONTROL_PORT, PHONE_CONTROL_TOKEN
    global TRANSCRIPT_DIR
    global SESSION_MAX_CONTEXT_CHARS, SESSION_KEEP_TURNS, TOOL_OUTPUT_MAX_CHARS

    # 重新读文件
    global _file_config
    try:
        if os.path.exists(_CONFIG_FILE):
            with open(_CONFIG_FILE, encoding="utf-8") as f:
                _file_config = json.load(f)
    except Exception:
        pass

    # Brain(指挥层)
    # Brain listen address is supplied by configuration and is distinct from the device Agent address.
    BRAIN_HOST = _get("BRAIN_HOST", "")
    # Brain 端口
    BRAIN_PORT = int(_get("BRAIN_PORT", "8770"))

    # 设备路由
    # 默认目标设备 ID(brain 下发命令的默认目标,如 "laptop")
    DEFAULT_DEVICE = _get("DEFAULT_DEVICE", "laptop")
    # 设备注册表文件路径
    DEVICES_FILE = _get("DEVICES_FILE", "") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "devices.json")
    # 客户端注册表文件路径(手机/平板/手表等连 brain 的设备,每个独立 token)
    CLIENTS_FILE = _get("CLIENTS_FILE", "") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "clients.json")
    # brain-agent command signing key. Dangerous commands require a valid HMAC signature.
    # 绝不下发给 App。服务器和被控设备(笔记本)两端都要配且一致。
    AGENT_SIGNING_SECRET = _get("AGENT_SIGNING_SECRET", "")

    # Agent(执行层,仅被控设备需要)
    # Agent 监听地址。仅在此机器跑 agent 时有用。
    AGENT_HOST = _get("AGENT_HOST", "")
    # Agent 端口
    AGENT_PORT = int(_get("AGENT_PORT", "8765"))
    # 中继服务器隧道内地址(换腾讯云时只改这里)
    RELAY_PRIMARY = _get("RELAY_PRIMARY", "")
    RELAY_HOST = _get("RELAY_HOST", "") or RELAY_PRIMARY

    # 鉴权
    # 共享令牌。App 和电脑端必须一致。留空=未配置,程序会拒绝所有请求并提示。
    AUTH_TOKEN = _get("AUTH_TOKEN", "")
    AUTH_TOKEN_ENCRYPTED = _get("AUTH_TOKEN_ENCRYPTED", "")

    # LLM
    # API 地址(OpenAI 兼容格式,DeepSeek/OpenAI/智谱等通用)
    LLM_API_URL = _get("LLM_API_URL", "")
    # API Key。留空=未配置,/chat 时会返回清晰的中文报错。
    LLM_API_KEY = _get("LLM_API_KEY", "")
    LLM_API_KEY_ENCRYPTED = _get("LLM_API_KEY_ENCRYPTED", "")
    # 默认模型名
    LLM_MODEL = _get("LLM_MODEL", "deepseek-chat")
    # 视觉模型(识图用,DeepSeek 不支持视觉,需单独配 OpenAI/Claude/Gemini)
    VISION_API_URL = _get("VISION_API_URL", "")
    VISION_API_KEY = _get("VISION_API_KEY", "")
    VISION_MODEL = _get("VISION_MODEL", "")
    # 调用超时(秒)
    LLM_TIMEOUT = int(_get("LLM_TIMEOUT", "60"))
    # 入库解析模型(便宜模型,批量解析资料省钱)
    # 留空则回退到上面的主 LLM。env: NOUS_INGEST_API_URL / NOUS_INGEST_API_KEY / NOUS_INGEST_MODEL
    INGEST_API_URL = _get("INGEST_API_URL", "")
    INGEST_API_KEY = _get("INGEST_API_KEY", "")
    INGEST_MODEL = _get("INGEST_MODEL", "")

    # 执行
    COMMAND_TIMEOUT = int(_get("COMMAND_TIMEOUT", "30"))
    BIND_RETRY_SECONDS = int(_get("BIND_RETRY_SECONDS", "5"))
    BRAIN_MAX_STEPS = int(_get("BRAIN_MAX_STEPS", "9999"))
    BRAIN_IDLE_LIMIT = int(_get("BRAIN_IDLE_LIMIT", "3"))
    # 步数警告阈值:执行超过此步数时暂停询问用户是否继续(0=不询问)
    BRAIN_STEP_WARNING = int(_get("BRAIN_STEP_WARNING", "3000"))

    # 安全
    ALLOWED_IPS_str = _get("ALLOWED_IPS", "")
    ALLOWED_IPS = [x.strip() for x in ALLOWED_IPS_str.split(",") if x.strip()] if ALLOWED_IPS_str else []
    RATE_LIMIT_PER_MINUTE = int(_get("RATE_LIMIT_PER_MINUTE", "30"))

    # 安全闸
    SAFETY_MODE = _get("SAFETY_MODE", "normal")
    SAFETY_WHITELIST_COMMANDS = [
        "dir", "ls", "Get-ChildItem", "cat", "type", "Get-Content",
        "whoami", "hostname", "ipconfig", "ping", "tracert",
        "Get-Process", "Get-Service", "Get-Location", "pwd",
        "echo", "Write-Output", "Get-Date", "Get-Command",
    ]
    SAFETY_READONLY_COMMANDS = [
        "Get-", "dir", "ls", "cat", "type", "whoami", "hostname",
        "ipconfig", "ping", "tracert", "pwd", "echo", "Write-Output",
        "Get-Date", "Get-Help", "Select-", "Where-", "Sort-", "Group-",
        "Format-List", "Format-Table", "Measure-", "Compare-",
    ]

    # 手机 SSH
    PHONE_SSH_IP = _get("PHONE_SSH_IP", "")
    PHONE_SSH_PORT = int(_get("PHONE_SSH_PORT", "8022"))
    PHONE_SSH_USER = _get("PHONE_SSH_USER", "root")
    PHONE_CONTROL_HOST = _get("PHONE_CONTROL_HOST", "") or PHONE_SSH_IP
    PHONE_CONTROL_PORT = int(_get("PHONE_CONTROL_PORT", "8788"))
    PHONE_CONTROL_TOKEN = _get("PHONE_CONTROL_TOKEN", "") or AUTH_TOKEN

    # 审计
    TRANSCRIPT_DIR = _get("TRANSCRIPT_DIR", "") or None

    # 上下文管理
    SESSION_MAX_CONTEXT_CHARS = int(_get("SESSION_MAX_CONTEXT_CHARS", "8000"))
    SESSION_KEEP_TURNS = int(_get("SESSION_KEEP_TURNS", "5"))
    TOOL_OUTPUT_MAX_CHARS = int(_get("TOOL_OUTPUT_MAX_CHARS", "16000"))


# 初始加载
_reload_all()
