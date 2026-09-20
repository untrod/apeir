# -*- coding: utf-8 -*-
"""
安全闸 —— 危险命令检测 + 安全模式管理。

设计原则:
  - 授权可以大,但危险动作必须有人工确认这道闸。
  - 闸的配置只能手动改 config.py,AI 不能自己改自己的权限。
  - 本模块被 brain.py 在每次执行前调用;agent.py 不感知安全策略(它只负责执行)。

为什么抽成独立文件:
  - 危险模式列表会随经验增长,独立文件便于审计和更新。
  - 安全逻辑与业务逻辑解耦,将来换检测策略(如引入 ML 分类器)不影响 brain.py。
"""

import re
from dataclasses import dataclass, field

import config


@dataclass
class DangerResult:
    """安全检测结果。is_danger=True 表示需要人工确认。"""
    is_danger: bool
    reasons: list[str] = field(default_factory=list)       # 中文危险原因
    matched_patterns: list[str] = field(default_factory=list)  # 匹配到的正则



# 危险模式列表 —— 每条 (正则, 中文说明)
# 为什么用正则而不是精确匹配:AI 生成的命令变体多(带参、管道、别名),正则覆盖面更广。
# 注意:部分模式可能误匹配(如 "format" 出现在字符串里),但宁可多问一次也比漏过强。

_DANGER_PATTERNS: list[tuple[str, str]] = [
    # 删除
    (r'\brmdir\b.*/[sS]', '递归删除目录(rmdir /s)'),
    (r'\bRemove-Item\b.*-Recurse', '递归删除(Remove-Item -Recurse)'),
    (r'\bRemove-Item\b.*-Force', '强制删除(Remove-Item -Force)'),
    (r'\brm\s+-rf?\b', '强制递归删除(rm -rf)'),
    (r'\bdel\b.*/[fF].*/[sS]', '强制递归删除(del /f /s)'),
    (r'\bClear-RecycleBin\b', '清空回收站'),
    (r'\bwipe\b', '擦除文件/磁盘'),

    # 格式化 / 磁盘
    # 注意:Format-Table/Format-List/Format-Wide/Format-Custom/Format-Hex 是只读显示命令,
    # 不含 - 前缀的裸 format 才是格式化命令。
    (r'(?<![A-Za-z-])format(?![A-Za-z-])', '格式化磁盘(format)'),
    (r'\bFormat-Volume\b', '格式化卷(Format-Volume)'),
    (r'\bClear-Disk\b', '清除磁盘(Clear-Disk)'),
    (r'\bInitialize-Disk\b', '初始化磁盘'),
    (r'\bdiskpart\b', '磁盘分区工具(diskpart)'),
    (r'\bchkdsk\b.*/[fFxX]', '磁盘修复(chkdsk 带修复参数,有风险)'),

    # 关机 / 重启
    (r'\bshutdown\b.*/s\b', '关机(shutdown /s)'),
    (r'\bshutdown\b.*/r\b', '重启(shutdown /r)'),
    (r'\bshutdown\b.*/p\b', '立即关机(shutdown /p)'),
    (r'\bStop-Computer\b', '关机(Stop-Computer)'),
    (r'\bRestart-Computer\b', '重启(Restart-Computer)'),

    # 卸载软件
    (r'\bwmic\s+product\b', '卸载软件(wmic product)'),
    (r'\bUninstall-Package\b', '卸载软件包(Uninstall-Package)'),
    (r'\bRemove-AppxPackage\b', '卸载商店应用(Remove-AppxPackage)'),
    (r'\bmsiexec\b.*/[xX]', '卸载 MSI 包(msiexec /x)'),
    (r'\buninstall\b', '卸载软件(uninstall)'),

    # 注册表
    (r'\breg\s+(add|delete)\b', '修改/删除注册表(reg add/delete)'),
    (r'\bSet-ItemProperty\b.*-Path\s+.*Registry', '修改注册表(Set-ItemProperty)'),
    (r'\bRemove-ItemProperty\b.*-Path\s+.*Registry', '删除注册表项(Remove-ItemProperty)'),
    (r'\bNew-Item\b.*-Path\s+.*Registry', '新建注册表项(New-Item)'),

    # 防火墙 / 网络
    (r'\bnetsh\s+firewall\b', '修改防火墙(netsh firewall)'),
    (r'\bNew-NetFirewallRule\b', '新增防火墙规则(New-NetFirewallRule)'),
    (r'\bRemove-NetFirewallRule\b', '删除防火墙规则(Remove-NetFirewallRule)'),
    (r'\bSet-NetFirewallProfile\b', '修改防火墙配置(Set-NetFirewallProfile)'),
    (r'\bDisable-NetAdapter\b', '禁用网络适配器(Disable-NetAdapter)'),
    (r'\bEnable-NetAdapter\b', '启用网络适配器(Enable-NetAdapter)'),
    (r'\bRestart-NetAdapter\b', '重启网络适配器(Restart-NetAdapter)'),

    # 执行策略
    (r'\bSet-ExecutionPolicy\b', '修改 PowerShell 执行策略(Set-ExecutionPolicy)'),

    # 用户账户
    (r'\bnet\s+user\b', '修改用户账户(net user)'),
    (r'\bnet\s+localgroup\b', '修改本地组(net localgroup)'),
    (r'\bNew-LocalUser\b', '新建本地用户(New-LocalUser)'),
    (r'\bRemove-LocalUser\b', '删除本地用户(Remove-LocalUser)'),
    (r'\bAdd-LocalGroupMember\b', '添加组成员(Add-LocalGroupMember)'),

    # 对外发包 / 下载执行
    (r'\bInvoke-WebRequest\b.*-OutFile', '下载文件(Invoke-WebRequest -OutFile)'),
    (r'\bInvoke-RestMethod\b.*-OutFile', '下载文件(Invoke-RestMethod -OutFile)'),
    (r'\bcurl\b.*-[oO]\b', '下载文件(curl -o)'),
    (r'\bwget\b', '下载文件(wget)'),
    (r'\bStart-BitsTransfer\b', 'BITS 文件传输(Start-BitsTransfer)'),
    (r'\bSend-TcpPacket\b', '发送 TCP 包(Send-TcpPacket)'),

    # 权限提升
    (r'\bStart-Process\b.*-Verb\s+RunAs', '以管理员身份运行(Start-Process -Verb RunAs)'),
    (r'\brunas\b', '以其他用户身份运行(runas)'),

    # 系统级危险操作
    (r'\bbcdedit\b', '修改启动配置(bcdedit)'),
    (r'\bsc\s+(stop|delete|config)\b', '修改 Windows 服务(sc stop/delete/config)'),
    (r'\bStop-Service\b.*-Force', '强制停止服务(Stop-Service -Force)'),
    (r'\btaskkill\b.*/[fF]', '强制结束进程(taskkill /f)'),
    (r'\bStop-Process\b.*-Force', '强制结束进程(Stop-Process -Force)'),
    (r'\bRemove-Item\b.*-Path\s+["\']?[A-Za-z]:\\Windows\\', '删除 Windows 系统目录文件'),
    (r'\bRemove-Item\b.*-Path\s+["\']?[A-Za-z]:\\Program Files\\', '删除 Program Files 目录文件'),
]


def check_danger(command: str, mode: str = "") -> DangerResult:
    """
    检查一条命令是否需要人工确认。

    参数:
      command: 待检查的命令文本
      mode: 安全模式,空字符串表示从 config.SAFETY_MODE 读取

    返回 DangerResult,其中 is_danger=True 表示需要确认。

    三种模式:
      normal:   匹配危险列表 → 要确认;其余自动放行
      readonly: 只有读类命令自动放行;其余全部要确认
      whitelist: 只有白名单前缀的命令自动放行;其余全部要确认
    """
    cmd = command.strip()
    if not cmd:
        return DangerResult(is_danger=False)

    mode = mode or getattr(config, "SAFETY_MODE", "normal")

    if mode == "readonly":
        return _check_readonly(cmd)
    elif mode == "whitelist":
        return _check_whitelist(cmd)
    else:  # normal
        return _check_normal(cmd)


def _check_normal(cmd: str) -> DangerResult:
    """normal 模式:匹配危险列表 → 要确认;其余放行。"""
    reasons = []
    patterns = []
    for pattern, desc in _DANGER_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            reasons.append(desc)
            patterns.append(pattern)
    return DangerResult(
        is_danger=len(reasons) > 0,
        reasons=reasons,
        matched_patterns=patterns,
    )


def _check_readonly(cmd: str) -> DangerResult:
    """
    readonly 模式:只有读类命令自动放行,其余都要确认。
    为什么需要这个模式:当用户在敏感环境(如调试正在运行的服务)不希望 AI 做任何修改时,
    切换到只读模式,AI 只能查看信息不能动手。
    """
    readonly_prefixes = getattr(config, "SAFETY_READONLY_COMMANDS", [
        "Get-", "dir", "ls", "cat", "type", "whoami", "hostname",
        "ipconfig", "ping", "tracert", "pwd", "echo", "Write-Output",
        "Get-Date", "Get-Help",
    ])

    # 提取命令的第一个词(忽略前导空格和赋值)
    first_word = cmd.split()[0] if cmd.split() else ""
    # 也检查管道前的第一个命令
    first_pipe_cmd = cmd.split("|")[0].strip().split()[0] if "|" in cmd else first_word

    for prefix in readonly_prefixes:
        if first_word.startswith(prefix) or first_pipe_cmd.startswith(prefix):
            # 即使是读命令,也过一遍危险列表(防止读命令里藏了管道修改)
            danger = _check_normal(cmd)
            if danger.is_danger:
                return DangerResult(
                    is_danger=True,
                    reasons=["[只读模式] 命令含危险操作: " + r for r in danger.reasons],
                    matched_patterns=danger.matched_patterns,
                )
            return DangerResult(is_danger=False)

    # 不在只读白名单里 → 要确认
    return DangerResult(
        is_danger=True,
        reasons=[f"[只读模式] 命令 '{first_word}' 不在只读放行列表内,需要确认"],
        matched_patterns=[],
    )


def _check_whitelist(cmd: str) -> DangerResult:
    """
    whitelist 模式:只有白名单前缀的命令自动放行,其余都要确认。
    这是最严格模式——AI 只能执行用户显式列出的命令类型。
    """
    whitelist_prefixes = getattr(config, "SAFETY_WHITELIST_COMMANDS", [
        "dir", "ls", "Get-ChildItem", "cat", "type", "Get-Content",
        "whoami", "hostname", "ipconfig", "ping", "tracert",
        "Get-Process", "Get-Service", "Get-Location", "pwd",
        "echo", "Write-Output", "Get-Date", "Get-Command",
    ])

    first_word = cmd.split()[0] if cmd.split() else ""
    first_pipe_cmd = cmd.split("|")[0].strip().split()[0] if "|" in cmd else first_word

    for prefix in whitelist_prefixes:
        if first_word.startswith(prefix) or first_pipe_cmd.startswith(prefix):
            # 在白名单,但仍过一遍危险检测(防止目录遍历到敏感位置等)
            danger = _check_normal(cmd)
            if danger.is_danger:
                return DangerResult(
                    is_danger=True,
                    reasons=["[白名单模式] 命令含危险操作: " + r for r in danger.reasons],
                    matched_patterns=danger.matched_patterns,
                )
            return DangerResult(is_danger=False)

    return DangerResult(
        is_danger=True,
        reasons=[f"[白名单模式] 命令 '{first_word}' 不在白名单内,需要确认"],
        matched_patterns=[],
    )
