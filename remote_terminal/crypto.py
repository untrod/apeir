# -*- coding: utf-8 -*-
"""
API Key 加密工具。
Windows 上用 DPAPI 保护密钥(绑定当前用户,其他用户/机器无法解密)。
Linux 上不支持 DPAPI,仅使用明文/环境变量(由操作系统文件权限保护)。
"""

import hashlib
import hmac
import os
import subprocess


def sign_command(command: str, secret: str = "") -> str:
    """
    对命令做 HMAC-SHA256 签名。brain 下发命令时调用,agent 校验时调用。
    secret 留空则从 config.AGENT_SIGNING_SECRET 读取。
    返回十六进制签名串;secret 未配置时返回空串。
    """
    if not secret:
        import config
        secret = getattr(config, "AGENT_SIGNING_SECRET", "")
    if not secret:
        return ""
    return hmac.new(secret.encode("utf-8"), command.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_command(command: str, signature: str, secret: str = "") -> bool:
    """校验命令签名是否有效。用 compare_digest 防时序攻击。"""
    if not secret:
        import config
        secret = getattr(config, "AGENT_SIGNING_SECRET", "")
    if not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), command.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def encrypt(plain: str) -> str:
    """
    用 DPAPI 加密字符串(仅 Windows)。
    返回 Base64 编码的密文(可安全存放到 config.local.json)。
    """
    if os.name != "nt":
        raise RuntimeError("DPAPI 加密仅支持 Windows。Linux 请使用环境变量或 config.local.json 明文配置。")
    ps = (
        '$p = ConvertTo-SecureString -String ' + f'"{plain}"' +
        ' -AsPlainText -Force; '
        'ConvertFrom-SecureString $p'
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,  # 不弹控制台窗口
    )
    if r.returncode != 0:
        raise RuntimeError(f"DPAPI 加密失败: {r.stderr}")
    return r.stdout.strip()


def decrypt(encrypted: str) -> str:
    """
    用 DPAPI 解密字符串(仅 Windows)。
    encrypted 是 encrypt() 返回的 Base64 密文。
    """
    if os.name != "nt":
        raise RuntimeError("DPAPI 解密仅支持 Windows。Linux 请使用环境变量或 config.local.json 明文配置。")
    import tempfile
    # 写入临时文件避免命令行转义问题
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    try:
        tf.write(encrypted)
        tf.close()
        ps = (
            f'$enc = Get-Content "{tf.name}" | ConvertTo-SecureString; '
            '[System.Runtime.InteropServices.Marshal]::PtrToStringAuto('
            '[System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($enc))'
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            raise RuntimeError(f"DPAPI 解密失败: {r.stderr}")
        return r.stdout.strip()
    finally:
        os.unlink(tf.name)


def load_token() -> str:
    """
    从 config 加载鉴权令牌。
    优先级:明文(环境变量/config.local.json) > DPAPI 密文(仅 Windows)。
    """
    import config
    plain = getattr(config, "AUTH_TOKEN", "")
    if plain:
        return plain
    # DPAPI 仅 Windows 可用
    if os.name == "nt":
        encrypted = getattr(config, "AUTH_TOKEN_ENCRYPTED", "")
        if encrypted:
            return decrypt(encrypted)
    return ""


def load_api_key():
    """
    从 config 加载 API Key。
    优先级:明文(环境变量/config.local.json) > DPAPI 密文(仅 Windows)。
    """
    import config
    plain = getattr(config, "LLM_API_KEY", "")
    if plain:
        return plain
    # DPAPI 仅 Windows 可用
    if os.name == "nt":
        encrypted = getattr(config, "LLM_API_KEY_ENCRYPTED", "")
        if encrypted:
            return decrypt(encrypted)
    return ""
