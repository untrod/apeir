# -*- coding: utf-8 -*-
"""
私有远程技术终端 —— Agent 端(笔记本/被控端,Windows)

职责:在 WireGuard 隧道内监听 HTTP,接收一条文字命令,执行,把结果返回给手机 App。
收命令 -> 校验令牌 -> 执行 -> 回结果。

通信约定:
  POST /exec   请求头 X-Auth-Token: <令牌>  (没有或不对 -> 401)
               请求体 JSON: {"command": "ls"}
               响应体 JSON: {"command","ok","returncode","stdout","stderr"}
  GET  /       健康检查,浏览器打开能看到一句话,方便确认服务活着(不需令牌)。
"""

import ctypes
import hmac
import json
import locale
import logging
import logging.handlers
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import crypto
import safety

# 日志:同时输出到控制台和文件
# 为什么加文件:开机自启时可能没有可见的控制台窗口,日志写文件才能事后排查。
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.log")
# 日志轮转:每10MB一个文件,保留3个备份,防止磁盘写满
_agent_fh = logging.handlers.RotatingFileHandler(
    LOG_FILE, encoding="utf-8", maxBytes=10 * 1024 * 1024, backupCount=3)
_agent_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(), _agent_fh],
)
log = logging.getLogger("agent")


def _mask_sensitive(text: str) -> str:
    """Mask common secrets before they enter agent.log."""
    if not isinstance(text, str) or not text:
        return text
    import re
    patterns = [
        (r'sk-[a-zA-Z0-9_-]{16,}', 'sk-***MASKED***'),
        (r'Bearer\s+[a-zA-Z0-9._-]{16,}', 'Bearer ***MASKED***'),
        (r'(api[_-]?key|token|password|secret)\s*[=:]\s*["\']?[^\s"\']+', r'\1=***MASKED***'),
        (r'(X-Auth-Token["\']?\s*[:=]\s*["\']?)[a-zA-Z0-9._-]{12,}', r'\1***MASKED***'),
    ]
    out = text
    for pat, repl in patterns:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out


def _detect_console_encoding() -> str:
    """
    确定 PowerShell 子进程输出用的编码,用它来解码命令输出。
    踩过的两个坑(都已实测验证):
      1. 不能"先试 UTF-8 再回退":'目录'的 GBK 字节(C4 BF C2 BC)恰好也是合法 UTF-8,
         会不报错却解码成乱码 Ŀ¼。
      2. 不能用 GetConsoleOutputCP(读的是你那个终端的代码页)或 locale.getpreferredencoding
         (本机 Python 处于 UTF-8 模式,返回 utf-8)—— 都不是子进程真正用的编码。
    子进程(-NoProfile 的 PowerShell)实际输出的是系统 ANSI 代码页 = GetACP(),
    中文 Windows 固定为 936/GBK,且不随 chcp 改变,确定可靠。
    """
    try:
        return f"cp{ctypes.windll.kernel32.GetACP()}"  # 中文 Windows = cp936
    except Exception:
        # 非 Windows 兜底,保证不崩。
        return locale.getpreferredencoding(False)


# 进程启动时探测一次即可,代码页不会中途变。
_CONSOLE_ENCODING = _detect_console_encoding()


def _decode(raw: bytes) -> str:
    """按本机控制台代码页解码;遇到个别坏字节用替换符兜底,绝不让解码异常拖垮服务。"""
    if not raw:
        return ""
    return raw.decode(_CONSOLE_ENCODING, errors="replace")


def run_command(command: str):
    """
    执行一条命令,返回 (returncode, stdout, stderr)。

    为什么走 PowerShell 而不是默认的 cmd.exe:
      - 你的验收命令里有 `ls`,cmd.exe 没有 `ls`(只有 dir),而 PowerShell 把 ls 作为
        Get-ChildItem 的别名,whoami 也支持 —— 这样 ls / whoami 都能直接通过。
    参数说明:
      -NoProfile      不加载用户 PowerShell 配置,启动更快、行为更可预测。
      -NonInteractive 不弹交互提示,避免远程执行时卡在等待输入。
    命令必须走 Runtime strict sandbox；若 Runtime 安全边界不可用则拒绝执行。
    """
    try:
        from nous_runtime.capability.sandbox import run_shell_command_strict
    except ImportError as exc:
        log.error("拒绝命令: Runtime strict sandbox 不可用: %s", exc)
        return -2, "", "拒绝: Runtime strict sandbox 不可用"

    try:
        completed = run_shell_command_strict(
            command,
            cwd=os.getcwd(),
            timeout_seconds=config.COMMAND_TIMEOUT,
        )
    except Exception as exc:
        log.exception("Strict sandbox execution failed")
        return -1, "", f"Strict sandbox execution failed: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


# 给模型的系统提示:把中文需求转成"一条" PowerShell 命令,并以 JSON 返回,便于稳定解析。
_LLM_SYSTEM_PROMPT = (
    "你是把中文自然语言转换为单条 Windows PowerShell 命令的助手。"
    "目标系统是 Windows,命令将在 PowerShell 中执行。"
    "只输出 JSON,格式严格为 "
    "{\"command\": \"<一条可直接执行的命令>\", \"explanation\": \"<一句话中文说明它做什么>\"}。"
    "不要输出多条命令,不要用 markdown 代码块,不要任何多余文字。"
)


def translate_to_command(text: str):
    """Translate natural language into one PowerShell command via Gateway."""
    if not config.LLM_API_KEY:
        raise RuntimeError(
            "LLM credential is not configured; configure it before use"
        )
    try:
        import model_gateway_bridge as gateway_bridge
    except ImportError:
        from remote_terminal import model_gateway_bridge as gateway_bridge

    schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "explanation": {"type": "string"},
        },
        "required": ["command", "explanation"],
        "additionalProperties": False,
    }
    result = gateway_bridge.invoke_message(
        [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        endpoint=config.LLM_API_URL,
        api_key=config.LLM_API_KEY,
        model=config.LLM_MODEL,
        timeout_s=config.LLM_TIMEOUT,
        structured=True,
        response_schema=schema,
    )
    parsed = result.structured_output
    if not isinstance(parsed, dict):
        content = result.message.get("content")
        parsed = content if isinstance(content, dict) else json.loads(str(content))
    return (
        str(parsed.get("command") or "").strip(),
        str(parsed.get("explanation") or "").strip(),
    )

# 限流器
_rate_limit_buckets = {}
def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    bucket = _rate_limit_buckets.get(ip, [])
    bucket = [t for t in bucket if now - t < 60]
    limit = getattr(config, "RATE_LIMIT_PER_MINUTE", 30)
    if len(bucket) >= limit:
        _rate_limit_buckets[ip] = bucket
        return False
    bucket.append(now)
    _rate_limit_buckets[ip] = bucket
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _check_access(self) -> bool:
        """IP 白名单 + 限流"""
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1", config.AGENT_HOST):
            return True
        allowed = getattr(config, "ALLOWED_IPS", [])
        if allowed and ip not in allowed:
            log.warning("拒绝:IP %s 不在白名单", ip)
            self._send_json(403, {"error": "forbidden: IP not in whitelist"})
            return False
        if not _check_rate_limit(ip):
            self._send_json(429, {"error": "rate limited"})
            return False
        return True

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # 健康检查：访问配置的 Agent 地址并确认服务状态。
        if self.path == "/":
            self._send_json(200, {"status": "agent alive"})
        else:
            self._send_json(404, {"error": "not found"})

    def _authorized(self) -> bool:
        token = self.headers.get("X-Auth-Token", "")
        return hmac.compare_digest(token, crypto.load_token())

    def do_POST(self):
        if self.path not in ("/exec", "/translate", "/transcribe", "/tts"):
            self._send_json(404, {"error": "not found"})
            return

        if not self._check_access():
            return

        if not self._authorized():
            log.warning("拒绝:令牌错误,来自 %s", self.client_address[0])
            self._send_json(401, {"error": "unauthorized"})
            return

        # /transcribe 接受原始音频,不解析 JSON
        if self.path == "/transcribe":
            self._handle_transcribe()
            return

        # 读取并解析 JSON 请求体
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "请求体必须是 JSON"})
            return

        if self.path == "/translate":
            self._handle_translate(body)
        elif self.path == "/tts":
            self._handle_tts(body)
        else:
            self._handle_exec(body)

    def _handle_exec(self, body):
        command = str(body.get("command", "")).strip()
        if not command:
            self._send_json(400, {"error": "command 不能为空"})
            return

        # 安全闸下沉:agent 独立检测危险命令
        # 危险命令必须带 brain 的有效 HMAC 签名(X-Cmd-Sig)才执行。
        # 这样即使 token 泄漏,攻击者直连 agent 也跑不了危险命令(签不出来)。
        signing_secret = getattr(config, "AGENT_SIGNING_SECRET", "")
        danger = safety.check_danger(command, getattr(config, "SAFETY_MODE", "normal"))
        if danger.is_danger:
            if not signing_secret:
                # 未配置签名密钥:记录告警但放行(部署过渡期;配置后即强制)
                log.warning("⚠️ 危险命令但未配置 AGENT_SIGNING_SECRET,过渡放行: %s —— %s",
                            _mask_sensitive(command)[:80], "; ".join(danger.reasons))
                self._send_json(403, {
                    "command": command, "ok": False, "returncode": -1, "stdout": "",
                    "stderr": "拒绝: 危险命令需要 Brain HMAC 签名,但 AGENT_SIGNING_SECRET 未配置。原因: "
                              + "; ".join(danger.reasons),
                })
                return
            else:
                sig = self.headers.get("X-Cmd-Sig", "")
                if not crypto.verify_command(command, sig, signing_secret):
                    log.error("拒绝危险命令(签名无效,疑似绕过 brain): %s —— %s",
                              _mask_sensitive(command)[:80], "; ".join(danger.reasons))
                    self._send_json(403, {
                        "command": command, "ok": False, "returncode": -1, "stdout": "",
                        "stderr": "拒绝:危险命令需经 Brain 签名授权(请通过指挥模式执行,会有确认流程)。原因: "
                                  + "; ".join(danger.reasons),
                    })
                    return
                log.info("危险命令签名校验通过: %s", _mask_sensitive(command)[:80])

        log.info("收到命令: %s", _mask_sensitive(command))
        try:
            returncode, stdout, stderr = run_command(command)
        except subprocess.TimeoutExpired:
            log.warning("命令超时(>%ss): %s", config.COMMAND_TIMEOUT, _mask_sensitive(command))
            self._send_json(200, {
                "command": command, "ok": False, "returncode": -1,
                "stdout": "", "stderr": f"命令执行超时(超过 {config.COMMAND_TIMEOUT} 秒)",
            })
            return
        except Exception as e:  # 兜底:任何执行异常都回给手机,而不是让服务崩
            log.error("执行出错: %s", e)
            self._send_json(200, {
                "command": command, "ok": False, "returncode": -1,
                "stdout": "", "stderr": f"执行出错: {e}",
            })
            return

        log.info("执行完成 returncode=%s, stdout=%d字节, stderr=%d字节",
                 returncode, len(stdout), len(stderr))
        self._send_json(200, {
            "command": command,
            "ok": returncode == 0,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        })

    def _handle_tts(self, body):
        """POST /tts — 文字转语音(Edge TTS,免费,国内直连),返回 MP3 音频。"""
        text = str(body.get("text", "")).strip()
        if not text:
            self._send_json(400, {"error": "text 不能为空"})
            return
        import tempfile
        import asyncio
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        try:
            tmp.close()
            from edge_tts import Communicate
            async def _gen():
                await Communicate(text[:300], "zh-CN-XiaoxiaoNeural").save(tmp.name)
            asyncio.run(_gen())
            with open(tmp.name, "rb") as f:
                audio = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
        except ImportError:
            self._send_json(500, {"error": "edge-tts 未安装, pip install edge-tts"})
        except Exception as e:
            log.error("TTS 失败: %s", e)
            self._send_json(500, {"error": f"TTS 失败: {e}"})
        finally:
            try: os.unlink(tmp.name)
            except OSError: pass

    def _handle_translate(self, body):
        text = str(body.get("text", "")).strip()
        if not text:
            self._send_json(400, {"error": "text 不能为空"})
            return

        log.info("翻译请求: %s", _mask_sensitive(text))
        try:
            command, explanation = translate_to_command(text)
        except urllib.error.HTTPError as e:
            # 模型接口返回错误(如 Key 错、额度用尽),把状态码带回去便于排查
            detail = e.read().decode("utf-8", "replace")[:300]
            log.error("LLM 接口 HTTP %s: %s", e.code, detail)
            self._send_json(200, {"ok": False, "error": f"模型接口错误 HTTP {e.code}: {detail}"})
            return
        except Exception as e:  # 网络/超时/未配置 Key/解析失败等,统一回错误,不崩服务
            log.error("翻译失败: %s", e)
            self._send_json(200, {"ok": False, "error": f"翻译失败: {e}"})
            return

        log.info("翻译结果: %s", _mask_sensitive(command))
        self._send_json(200, {
            "ok": bool(command),
            "text": text,
            "command": command,
            "explanation": explanation,
        })


    def _handle_transcribe(self):
        """POST /transcribe — 接收音频,调用 whisper 转文字,返回文本。"""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._send_json(400, {"ok": False, "error": "音频数据不能为空"})
            return
        if length > 5 * 1024 * 1024:
            self._send_json(413, {"ok": False, "error": "音频过大,请控制在 5MB 以内"})
            return
        raw = self.rfile.read(length)
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            tmp.write(raw)
            tmp.close()
            text = _transcribe_audio(tmp.name)
            # 调试:保存每次录音到 sessions/voice_*.wav
            dbg = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "sessions", f"voice_{time.strftime('%H%M%S')}.wav")
            try:
                os.makedirs(os.path.dirname(dbg), exist_ok=True)
                with open(dbg, "wb") as f:
                    f.write(raw)
            except Exception:
                pass
            if text == "(未识别到语音)":
                log.info("未识别,音频已保存至 %s (%d 字节)", dbg, length)
            self._send_json(200, {"ok": True, "text": text})
        except Exception as e:
            log.error("语音转文字失败: %s", e)
            self._send_json(200, {"ok": False, "error": f"转写失败: {e}"})
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


# 语音转文字
_whisper_model = None
_whisper_lock = threading.Lock()

def _get_whisper():
    """懒加载 whisper 模型(单例)。用 tiny 模型,内存<1GB,速度快。"""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model
        model_size = getattr(config, "STT_MODEL_SIZE", "") or "tiny"
        try:
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
            log.info("Whisper %s 模型已加载", model_size)
        except ImportError:
            log.error("faster-whisper 未安装,请运行: pip install faster-whisper")
            raise RuntimeError("faster-whisper not installed")
        return _whisper_model

def _transcribe_audio(wav_path: str) -> str:
    """对 WAV 文件运行 whisper,返回文字。指定中文以提升手表录音的识别率。"""
    model = _get_whisper()
    segments, _ = model.transcribe(wav_path, language="zh", beam_size=5,
                                   condition_on_previous_text=False)
    parts = [seg.text.strip() for seg in segments if seg.text.strip()]
    return "".join(parts) if parts else "(未识别到语音)"


def main():
    # 绑定重试：开机自启时 Agent 可能比隧道网卡先启动。
    # 此时不退出,而是隔几秒重试,直到隧道就绪。手动运行时若隧道已连,第一次就成功。
    server = None
    while server is None:
        try:
            # ThreadingHTTPServer:一条命令在跑时不阻塞健康检查/下一条请求。
            server = ThreadingHTTPServer((config.AGENT_HOST, config.AGENT_PORT), Handler)
        except OSError as e:
            log.warning("绑定 %s:%s 失败(常见于隧道尚未就绪),%s 秒后重试… 原始错误: %s",
                        config.AGENT_HOST, config.AGENT_PORT, config.BIND_RETRY_SECONDS, e)
            time.sleep(config.BIND_RETRY_SECONDS)

    log.info("Agent 已启动,监听 http://%s:%s (仅隧道内可达,需令牌)", config.AGENT_HOST, config.AGENT_PORT)
    log.info("健康检查: 浏览器打开 http://%s:%s/  |  停止: Ctrl+C", config.AGENT_HOST, config.AGENT_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C,正在关闭...")
        server.shutdown()


if __name__ == "__main__":
    main()
