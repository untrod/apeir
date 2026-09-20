package com.example.remoteterminal

/**
 * 斜杠命令系统 — 像 Claude Code 一样在输入框输入 / 触发命令自动补全。
 * 每条命令 = 名称 + 中文说明 + 发送给大脑的实际文本。
 */
data class Command(
    val name: String,        // 如 "/clear"
    val description: String, // 中文说明
    val sendText: String,    // 发送给大脑的实际消息(空=不发送,本地处理)
    val localAction: Boolean = false, // 是否纯本地操作
)

val COMMANDS = listOf(
    // 本地操作
    Command("/clear", "清空当前对话", "", localAction = true),
    Command("/new", "新建空白会话", "", localAction = true),
    Command("/export", "导出对话为 Markdown 分享", "", localAction = true),
    Command("/help", "显示所有可用命令", "", localAction = true),
    Command("/voice", "切换语音对话模式", "", localAction = true),
    // 系统
    Command("/system", "系统概况 CPU/内存/磁盘/网卡", "用 get_system_info 查看系统概况"),
    Command("/disk", "磁盘空间分析 + 大文件查找", "用 disk_analyze 分析磁盘空间"),
    Command("/process", "列出 CPU 最高的进程", "用 process_manage 列出进程"),
    Command("/service", "列出运行中的 Windows 服务", "用 service_manage 列出服务"),
    // 网络
    Command("/diagnose", "一键网络诊断 隧道/外网/端口", "用 network_diagnose 做网络诊断"),
    Command("/port", "检查端口占用 例:/port 8770", ""),
    Command("/ssl", "SSL证书检查 例:/ssl github.com", ""),
    Command("/dns", "DNS查询 例:/dns example.com MX", ""),
    Command("/whois", "域名Whois 例:/whois github.com", ""),
    Command("/ip", "IP归属地查询", "用 ip_lookup 查 IP 归属"),
    // 文件
    Command("/find", "搜索文件名 例:/find *.py", ""),
    Command("/grep", "搜索文件内容 例:/grep TODO", ""),
    Command("/read", "读取文件 例:/read main.py", ""),
    Command("/write", "写入文件 例:/write path content", ""),
    Command("/diff", "对比两个文件差异", "用 text_diff 对比文件"),
    Command("/hash", "文件哈希校验 例:/hash setup.exe", ""),
    // 开发
    Command("/git", "查看 Git 仓库状态", "用 git_status 查看 Git 状态"),
    Command("/gitlog", "Git 最近提交记录", "用 git_log 查看最近提交"),
    Command("/blame", "Git Blame 查行作者 例:/blame app.py:42", ""),
    Command("/todo", "扫描项目 TODO/FIXME 标记", "用 find_todos 扫描待办"),
    Command("/review", "代码审查 例:/review main.py", ""),
    Command("/deps", "依赖检查(npm/pip过期)", "用 dependency_check 检查依赖"),
    Command("/python", "执行 Python 代码 例:/python 1+2", ""),
    // 开源平台
    Command("/gh", "GitHub搜索 例:/gh android compose", ""),
    Command("/repo", "GitHub仓库详情 例:/repo torvalds linux", ""),
    Command("/readme", "GitHub项目README 例:/readme微soft typescript", ""),
    Command("/trending", "GitHub今日趋势 例:/trending python", ""),
    Command("/gitee", "Gitee码云搜索 例:/gitee鸿蒙", ""),
    Command("/pypi", "PyPI搜索Python包 例:/pypi requests", ""),
    Command("/clone", "克隆GitHub仓库 例:/clone torvalds linux", ""),
    // GUI
    Command("/open", "打开应用 例:/open vscode", ""),
    Command("/windows", "列出所有打开窗口", "用 gui_control 列出窗口"),
    Command("/click", "鼠标点击 例:/click 500 300", ""),
    Command("/type", "键盘输入文字 例:/type Hello", ""),
    Command("/keys", "按快捷键 例:/keys Ctrl+C", ""),
    // 工具
    Command("/qr", "生成二维码 例:/qr https://example.com", ""),
    Command("/pwd", "生成随机密码 例:/pwd 20", ""),
    Command("/short", "生成短链接 例:/short https://...", ""),
    Command("/clip", "读取剪贴板内容", "用 clipboard 读剪贴板"),
    // 安全
    Command("/nmap", "Nmap端口扫描(需确认)", "用 nmap_scan 扫描"),
    Command("/vpn", "VPN连接状态", "用 vpn_connect status 查看"),
)

/** 根据输入过滤匹配命令。输入为空返回全部。 */
fun filterCommands(input: String): List<Command> {
    if (input.isEmpty()) return COMMANDS
    val q = input.lowercase().trimStart('/')
    return COMMANDS.filter { it.name.lowercase().contains(q) || it.description.contains(q) }
}

/** 判断是否为本地命令(不发送到大脑) */
fun isLocalCommand(name: String): Boolean = COMMANDS.find { it.name == name }?.localAction ?: false

/** 获取命令的发送文本(如果是本地命令返回 null) */
fun getCommandSendText(name: String): String? {
    val cmd = COMMANDS.find { it.name == name } ?: return null
    return if (cmd.localAction) null else cmd.sendText
}
