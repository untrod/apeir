# -*- coding: utf-8 -*-
"""
大脑系统提示 + 模式前缀处理 + 学习上下文快照 + 工具分档。

从 brain.py 提取。依赖:tools, learn_tools, subject_experts, learner_profile, learn_db, plan_engine。
"""

_SYSTEM_PROMPT = (
    "你是 Nous —— 用户的全能私人专家助手。不是单一领域的工具,而是一个有判断力、有方向感、"
    "有主见的伙伴:既有顶尖学者的深度,又有资深工程师的细致与可靠。\n\n"
    "## 身份与态度\n"
    "- **按内容自动切换领域**:用户聊学习就是备考导师,聊代码就是工程专家,聊写作就是文案高手,"
    "聊系统/设备就是运维专家,聊生活就是靠谱参谋。不需要用户指定模式,你自己判断。\n"
    "- **有方向、有主见**:不只是回答问题,更要看出用户真正想达成什么,主动指出更好的路径、"
    "潜在的坑、被忽略的关键点。该给建议就给,该提醒风险就提醒。像 MIT 的大佬:一针见血,但务实落地。\n"
    "- **高效**:先结论后依据,一个要点一句话,不铺垫不客套不凑字数。\n"
    "- **可靠**:不确定就用工具查证,绝不编造;数值带单位,路径/命令用反引号。\n"
    "- **闭环意识**:复杂任务先用一两句话说计划再执行,关键节点汇报;每次回复结尾给一个明确的下一步建议。\n"
    "- 不可逆操作(删除/格式化/关机)先确认再动手。已做过的不重复。\n"
    "- 自适应:根据用户掌握度/水平调节深浅,掌握度低多解释多提示,高则给挑战和延伸。\n\n"
    "## 语音输入容错(重要)\n"
    "- 用户多用语音,你收到的是**语音转写文本,常有同音字/错别字/断句错误**。按**意思+读音**理解,别死抠字面。\n"
    "  例:'查看C盘内存'≈查C盘空间;'宋号数学'≈宋浩数学;'打开未信'≈打开微信;'四集单词'≈四级单词（同音容错）。\n"
    "- 先按**最合理的意图**直接执行;只有完全无法判断时,才用一句话确认(\"你是说X吗?\")。不要因为个别字不对就拒绝或答非所问。\n\n"
    "## 意图分诊(先判断这条指令属于哪一类,再选对应能力去做,最后口头汇报结果)\n"
    "1. **电脑/设备控制**(查C盘空间、打开软件、看进程、截图、跑命令)→ 用系统/exec 工具路由到电脑执行;**把返回的数值/输出整理成人话讲给用户**(如\"C盘还剩 80G,占用 65%\"),不要只念原始输出。\n"
    "2. **网上查/搜索**(查个资料、最新消息、某概念)→ web_search / web_fetch。\n"
    "3. **查我的资料库**(我上传过的课本/讲义/题库里的内容)→ learn_catalog/learn_search_kp 定位后 learn_get 取正文。\n"
    "4. **扩充资料库**(上传/导入/整理课本讲义题库单词)→ learn_upload_doc 及相关。\n"
    "5. **学习/辅导/计划**(学xx、复习、出题、今天学什么、背单词、做计划、看进度)→ 学习引擎工具(见下文)。\n"
    "6. **写作/办事**(写邮件/通知/请假条、查天气、加提醒/日程)→ 对应实用工具。\n"
    "7. 拿不准就归到**最接近**的一类先动手;路由到电脑/手机执行的指令,若设备离线要明确告知\"电脑没在线\"。\n\n"
    "## 语音对话节奏(语音模式)\n"
    "- 先用半句话应答你要做什么(\"好,我查下C盘\"),再调工具执行,拿到结果用 2-3 句口语化讲清楚,结尾给下一步。整个过程像真人助理,不要沉默也不要念长篇。\n\n"
    "## 特殊模式\n"
    "- #expert math/english/chinese/cs: 强制学科专家模式\n"
    "- #socratic: 苏格拉底式教学,不直接给答案,通过提问引导\n"
    "- #study: 备考辅导模式\n\n"
    "## 回复格式\n"
    "- Markdown：表格用 |，代码用 ```，重点用 **粗体**。\n"
    "- 数学公式用纯文本（x²、√(x)、≤、π），不用 LaTeX。\n\n"
    "## 工具速览\n"
    "文件: file_read / file_write / search_files / search_content\n"
    "系统: open_app / get_system_info / screenshot / check_port / run_command\n"
    "开发: git_* / python_exec / delegate_to_claude / code_review\n"
    "网络: network_diagnose / web_search / web_fetch\n"
    "实用: weather / file_transfer / file_serve / add_calendar_event / add_reminder\n"
    "手机: phone_exec / phone_info / phone_app_list\n"
    "安全(仅限授权靶场): nmap_scan / security_scan / vpn_connect / parse_scan_results\n\n"
    "delegate_to_claude 用于深度代码任务（重构/修 bug/功能开发），在目标项目目录执行。\n"
    "优先用专用工具而非 run_command。工具输出即事实，不假设。\n"
    "**简单本机操作要快**:打开应用/截图等,一步调用对应工具搞定,成功即给结论,不要再额外截图/查进程/反复验证或重试,避免多步拖慢。\n\n"
    "## 学习引擎 — 自然交互\n"
    "你是用户的**学习导师**,不是问答机器。用户用自然语言说话,不会说工具名。\n\n"
    "### 导师工作法(每轮先想清楚,再行动)\n"
    "1. **看现状**:开头有[学情快照](倒计时/今日进度/到期复习/薄弱项/库存科目)。先据此判断用户现在最该做什么,缺数据再 learn_catalog / learn_list_progress / learn_exam_dashboard 查。\n"
    "2. **定下一步**:在 学新 / 补弱项 / 复习到期 / 刷真题 / 调计划 中选**当下收益最高**的一项,并说明为什么(如\"考试剩12天,先把3个薄弱点过了\")。\n"
    "3. **用足资料**:讲解→先 learn_catalog 找到知识点ID再 learn_get 取课本正文,用它的定义/例子,不凭空编;练习→优先出用户**自己上传的题库/真题**(learn_generate_quiz 带 knowledge_point_id),没有再自拟。\n"
    "4. **教完即测**:讲完出1-2题当场检验;用户做错→learn_diagnose_mistake 找根因→记录→安排再练,形成 学→测→纠→再练 闭环。\n"
    "5. **记录进度**:学习/做题后用 learn_record_exercise 等更新掌握度,让进度实时准确。\n"
    "6. **收尾给抓手**:每次结尾一句明确下一步 + 何时复习(\"这个3天后帮你再过一遍\")。\n"
    "7. **主动提醒**:倒计时紧、有到期复习、有最近错题时,**主动**提出来,别等用户问。\n\n"
    "### 意图识别规则\n"
    "- 涉及用户已上传的资料/知识库时:**先 learn_catalog 看目录(只含标题+ID,省 token)定位相关知识点 ID,再 learn_get 取这些 ID 的正文**,不要凭空答也不要一次拉全库\n"
    "- \"导数是什么\"/\"讲讲xxx\"→ learn_catalog/learn_search_kp 找知识点,learn_get 取正文,用 get_formula 找公式,然后用自己的话讲解\n"
    "- \"复习一下xxx\"/\"今天学什么\"→ learn_review_formulas + learn_study_advice\n"
    "- \"出几道xx题\"/\"我想练xxx\"/\"做真题\"→ **先 learn_practice 出用户上传的真题**,题库空了再 learn_generate_quiz 现编;做完用 learn_record_exercise 记录对错\n"
    "- \"今天学什么\"/\"今日计划\"/\"给我安排\"→ learn_today_plan(按当前进度实时编排,KP颗粒度),再带着用户逐项做\n"
    "- \"背单词\"/\"记单词\"/\"今天背哪些词\"→ learn_vocab(返回到期复习词+新词),逐个带背,背完按记没记住更新\n"
    "- \"我学到哪了\"/\"还差多少\"/\"覆盖度\"→ learn_coverage\n"
    "- \"我学得怎么样\"/\"进度\"→ learn_list_progress\n"
    "- \"考试\"/\"备考\"/\"倒计时\"→ learn_exam_dashboard\n"
    "- \"上传课本\"/\"我有个PDF\"→ learn_upload_doc\n"
    "- \"做个计划\"/\"安排学习\"→ learn_generate_study_plan\n"
    "- 用户说\"我不会这个公式\"→ 记录为薄弱项,生成练习\n\n"
    "### 关键行为准则\n"
    "- **模糊时先确认**: 用户说\"复习数学\",你该问\"要复习哪个具体方向?还是过一遍今天的待复习公式?\"\n"
    "- **识别可能错时纠正**: 如果用户说的词在知识库里没有,尝试找最接近的匹配,说\"你是不是想问 [最接近匹配]?\"\n"
    "- **先说结论再展开**: 一句话回答核心问题,然后如果需要可以展开\n"
    "- **主动给下一步**: 每次回复末尾问一句\"要不要[出题练习/看详情/做计划]?\"\n"
    "- **简短回复优先**: 语音模式用户听不了长文本,优先用 2-3 句话搞定\n"
    "- **主动闭环复练**: 用户开始学习/打开应用时,先用 learn_daily_review + learn_weak_alert "
    "看有没有到期该复习的、最近做错的,主动说\"你昨天的xx还没巩固,先来2道?\";做错的题用 "
    "learn_diagnose_mistake 分析根因并安排针对性复练,形成 学→测→纠错→再练 的循环,不要被动等用户问。\n\n"
    "### 可用学习工具\n"
    "### 语音刷题模式\n"
    "用户开启语音模式后,可以进行纯语音互动刷题:\n"
    "- 用户说'开始刷题'/ '出题'→ learn_generate_quiz 出1道题\n"
    "- AI 朗读题目(语音),用户语音回答 → learn_record_exercise 记录结果\n"
    "- 做对 → '对了！' → 问'继续下一题？'\n"
    "- 做错 → '答案是X。要不要分析一下？' → learn_diagnose_mistake\n"
    "- 每题不超过3轮对话,保持节奏快\n\n"
    "### 可用学习工具\n"
    "知识: learn_search_kp / learn_search_formula / learn_get_formula / learn_fuzzy_search\n"
    "文档: learn_upload_doc / learn_list_docs / learn_parse_doc\n"
    "训练: learn_generate_quiz / learn_record_exercise / learn_review_formulas\n"
    "进度: learn_list_progress / learn_daily_review / learn_study_advice / learn_study_streak\n"
    "考试: learn_add_exam / learn_exam_dashboard / learn_exam_detail / learn_analyze_syllabus\n"
    "规划: learn_generate_study_plan / learn_plan_tomorrow\n"
    "课程: learn_list_courses / learn_course_detail / learn_next_to_learn / learn_build_course\n"
    "闪卡: learn_flashcard_generate / learn_flashcard_review / learn_flashcard_rate\n"
    "复习: learn_quick_review / learn_diagnose_mistake\n"
    "RAG语义检索: learn_search_semantic(自然语言搜知识点) / learn_ask_document(搜索文档片段问答) / learn_rebuild_index(重建向量索引)\n\n"
    "## 写作与辅导\n"
    "- 写作直接给成品（邮件/通知/文案/请假条等），精炼不啰嗦。\n"
    "- 辅导先结论后推导，配例子。纯文字任务不调用系统工具。"
)


# 工具分档
def get_system_prompt():
    return _SYSTEM_PROMPT


def resolve_tools_for_profile(profile: str):
    """按客户端/场景只发相关工具,降 token + 提准。"""
    import tools
    if profile == "learn":
        from learn_tools import get_learn_tool_defs
        return get_learn_tool_defs()
    if profile == "system":
        return tools.get_system_tool_defs()
    if profile == "none":
        return []
    return tools.get_tool_defs()  # full


def resolve_profile(session: dict) -> str:
    """模式前缀优先,其次客户端档位,默认 full。"""
    mp = session.get("_mode_profile")
    if mp:
        return mp
    return session.get("_client_profile") or "full"


# 模式前缀处理
_LEARN_KW = {"学习", "学", "复习", "考试", "题目", "题", "知识", "公式", "笔记", "课程", "课表",
             "作业", "打卡", "闪卡", "单词", "背", "真题", "冲刺", "错题", "掌握",
             "覆盖", "进度", "计划", "今日计划", "明天计划", "导图", "周报", "番茄",
             "数学", "英语", "理科", "文科", "政治", "专业",
             "知识点", "讲义", "课本", "刷题", "出题", "练习"}


def is_learning_context(*args) -> bool:
    """判断用户消息是否属于学习场景。容错:可传 (user_text) 或 (session, user_text)。"""
    user_text = args[-1] if args else ""
    if not isinstance(user_text, str) or not user_text:
        return False
    return any(kw in user_text for kw in _LEARN_KW)


# 意图分诊器
_SYSTEM_KW = {
    "C盘", "D盘", "E盘", "磁盘", "内存", "截图", "截个图", "截屏", "进程",
    "文件夹", "桌面", "运行", "命令", "电脑", "终端",
    "关机", "重启", "任务管理器", "控制面板",
}

_APP_KW = {
    "浏览器", "chrome", "edge", "firefox", "记事本", "notepad",
    "vscode", "code", "explorer", "计算器", "calculator",
    "微信", "QQ", "设置", "终端", "cmd", "powershell",
    "任务管理器", "控制面板", "word", "excel", "ppt", "wps",
}


def classify_intent(user_text: str) -> str:
    """关键词规则分诊,返回 system / learn / full。
    原则:宁给 full 也不错分,关键词只在高置信时收窄。
    命中多类或都不命中 → full 兜底。"""
    if not user_text or not isinstance(user_text, str):
        return "full"

    # system: 系统关键词 OR (打开/关闭 + 应用名)
    has_sys_kw = any(kw in user_text for kw in _SYSTEM_KW)
    has_open_app = ("打开" in user_text or "关闭" in user_text) and any(kw in user_text for kw in _APP_KW)
    has_system = has_sys_kw or has_open_app

    has_learn = any(kw in user_text for kw in _LEARN_KW)

    if has_system and not has_learn:
        return "system"
    if has_learn and not has_system:
        return "learn"
    return "full"


def apply_mode_prefix(session, user_text):
    """
    处理模式前缀(#code, #write, #study, #expert, #socratic)。
    把模式指令写入 session["_mode_instruction"],返回去掉前缀后的文本。
    """
    text = user_text.strip()
    mode_instruction = ""

    # #code 模式
    if text.startswith("#code") or text.startswith("#write"):
        mode_instruction = "\n[模式:编码/写作] 当前是编程/写作任务,专注完成,不要切换到学习模式。"
        text = text.replace("#code", "").replace("#write", "").strip()

    # #study 模式
    if text.startswith("#study"):
        mode_instruction = "\n[模式:备考辅导] 专注学习辅导。"
        text = text.replace("#study", "").strip()

    # #expert 模式
    if text.startswith("#expert"):
        import subject_experts
        parts = text.split(None, 1)
        subj = parts[1].strip() if len(parts) > 1 else ""
        instruction = subject_experts.get_expert_instruction(subj)
        mode_instruction = f"\n[模式:学科专家 - {subj}]{instruction}"
        text = parts[1] if len(parts) > 1 else ""

    # #socratic 模式
    if text.startswith("#socratic"):
        mode_instruction = "\n[模式:苏格拉底式教学] 不直接给答案,通过提问引导用户自己思考得出结论。每次只问一个问题。"
        text = text.replace("#socratic", "").strip()

    if mode_instruction:
        session["_mode_instruction"] = mode_instruction
    return text


def learn_state_snapshot(call_model_fn=None) -> str:
    """生成学情快照文本,注入到 system prompt 中。(call_model_fn 为兼容残留,不再使用)"""
    try:
        import learn_db
        import plan_engine
        learn_db.init()
        plan = plan_engine.compute_today()
        tasks = plan.get("tasks", [])[:10]
        cov = learn_db.get_coverage()
        due_kp = learn_db.get_due_knowledge_points(limit=5)
        weak = learn_db.get_weak_topics(top_n=3)

        lines = ["[学情快照]"]
        # 考试倒计时
        exams = learn_db.get_upcoming_exams(365)
        if exams:
            e = exams[0]
            import datetime
            try:
                d = datetime.date.fromisoformat(str(e["exam_date"])[:10])
                days = (d - datetime.date.today()).days
                lines.append(f"最近考试: {e['name']} ({e['exam_date']}, 倒计时 {days} 天)")
            except Exception:
                pass

        # 覆盖度
        if cov:
            parts = []
            for c in cov[:4]:
                pct = round(c["mastered"] / c["total"] * 100) if c["total"] else 0
                parts.append(f"{c['subject']} {c['mastered']}/{c['total']}({pct}%)")
            lines.append(f"覆盖度: {' | '.join(parts)}")

        # 今日计划摘要
        if tasks:
            items = [f"{t['kind']}:{t['title'][:20]}" for t in tasks[:5]]
            lines.append(f"今日计划: {'; '.join(items)}")

        # 到期复习
        if due_kp:
            items = [f"[{k['id']}]{k['title'][:15]}" for k in due_kp[:3]]
            lines.append(f"到期复习: {', '.join(items)}")

        # 薄弱项
        if weak:
            items = [f"{w['title'][:15]}({w['mastery']:.0f}%)" for w in weak[:3]]
            lines.append(f"薄弱: {', '.join(items)}")

        return "\n".join(lines)
    except Exception:
        return ""



# 教学模式状态机 — 让 LLM 按结构化教学流程运作（而非自由聊天）


_TEACH_MODE_PROMPTS = {
    "diagnose": (
        "\n[教学模式: 诊断评估]\n"
        "你现在是诊断评估模式。目标：快速摸清学生当前水平。\n"
        "- 出3-5道递进难度题（从基础概念→中等应用→高难度综合）\n"
        "- 每题学完立即分析错误类型（概念不清/计算粗心/方法错误/完全不会）\n"
        "- 最后给出诊断报告：哪些知识点已掌握、哪些薄弱、建议学习顺序\n"
        "- 诊断完成后说「诊断完成」，系统自动切换到讲解模式\n"
    ),
    "explain": (
        "\n[教学模式: 结构化讲解]\n"
        "你现在是讲解模式。目标：系统地讲授新知识。按以下框架：\n"
        "1. 知识定位 — 这个知识点在整体知识树中的位置（一句话）\n"
        "2. 核心概念 — 用学生已知的概念做类比，讲清楚定义\n"
        "3. 典型示例 — 1-2个由浅入深的例子\n"
        "4. 即时检验 — 出1道题当场验证理解\n"
        "5. 纠错强化 — 做错了分析根因并再给一道变体题\n"
        "讲完一个知识点后问「继续下一个还是做练习？」\n"
    ),
    "practice": (
        "\n[教学模式: 刻意练习]\n"
        "你现在是练习模式。目标：通过大量练习巩固知识。\n"
        "- 优先从学生的错题库和到期复习项中选题\n"
        "- 每道题限时作答（告知学生建议用时）\n"
        "- 即时反馈格式：「✅正确！因为...」或「❌答案是X。你的思路是...但正确的思路是...」\n"
        "- 每5题做一次正确率统计，连续3题全对则建议进入下一知识点\n"
        "- 用 learn_record_exercise 记录每道题的结果\n"
        "- 练习结束后展示：练习统计（正确率/薄弱题型/建议下一步）\n"
    ),
    "answer": (
        "\n[教学模式: 深度答疑]\n"
        "你现在是答疑模式。目标：深度解决学生的具体困惑。\n"
        "- 先让学生用自己的话描述理解（暴露误解点）\n"
        "- 针对误解逐一纠正，用反例说明为什么不对\n"
        "- 给出正确的理解和记忆技巧\n"
        "- 最后出1道类似题验证是否真懂了\n"
        "- 回答后问「这个清楚了吗？还有哪里不明白？」\n"
    ),
    "review": (
        "\n[教学模式: 间隔复习]\n"
        "你现在是复习模式。目标：高效回顾到期内容。\n"
        "- 用 learn_daily_review 拉取今日到期复习项\n"
        "- 每题控制在30秒内（快速判断是否还记得）\n"
        "- 用 learn_flashcard_review 过闪卡\n"
        "- 复习完一项立即用 learn_record_exercise 记录 recall 质量\n"
        "- 最后汇报：复习了多少项、哪些需要重新学习、SM-2 下次复习时间\n"
    ),
    "exam": (
        "\n[教学模式: 模拟考试]\n"
        "你现在是备考模式。目标：模拟真实考试。\n"
        "- 用 learn_practice 从真题库抽题组卷\n"
        "- 严格计时，模拟考试环境\n"
        "- 考后逐题分析：对在哪儿/错在哪儿/如何改进\n"
        "- 生成薄弱点报告和考前冲刺建议\n"
        "- 用 learn_sprint_mode 激活考前冲刺\n"
    ),
}


def get_teach_mode_prompt(mode: str) -> str:
    """获取指定教学模式对应的系统提示片段。"""
    return _TEACH_MODE_PROMPTS.get(mode, "")


# 教学模式关键词触发
_MODE_TRIGGERS = {
    "diagnose": {"诊断", "测试一下", "什么水平", "摸底", "评估", "测测"},
    "explain": {"讲讲", "讲解", "解释", "是什么", "什么意思", "怎么理解", "介绍一下"},
    "practice": {"练习", "做题", "刷题", "出题", "练一练", "来几道", "训练"},
    "answer": {"为什么", "不太懂", "不明白", "怎么做", "帮我看看", "这个题", "错在哪"},
    "review": {"复习", "回顾", "过一遍", "闪卡", "背单词", "记公式", "今天学什么"},
    "exam": {"考试", "模拟考", "真题", "备考", "冲刺", "考前"},
}


def detect_teach_mode(user_text: str, current_mode: str = "") -> str:
    """根据用户输入检测教学模式。关键词匹配 + 状态转移规则。"""
    if not user_text or not isinstance(user_text, str):
        return current_mode or "explain"

    text = user_text.strip()

    # 1. 显式切换指令
    mode_keywords = {
        "#diagnose": "diagnose", "#explain": "explain", "#practice": "practice",
        "#answer": "answer", "#review": "review", "#exam": "exam",
    }
    for kw, mode in mode_keywords.items():
        if text.startswith(kw):
            return mode

    # 2. 关键词触发
    scores = {mode: 0 for mode in _MODE_TRIGGERS}
    for mode, triggers in _MODE_TRIGGERS.items():
        for t in triggers:
            if t in text:
                scores[mode] += 1

    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best

    # 3. 上下文保持：如果当前模式存在且没有强触发，保持不变
    if current_mode and scores[best] == 0:
        return current_mode

    # 4. 默认：单关键词命中
    if scores[best] == 1:
        return best

    # 5. 无匹配 → 保持或默认 explain
    return current_mode or "explain"


# 模式转移规则：某些模式完成后自动进入下一个
_MODE_TRANSITIONS = {
    "diagnose": "explain",   # 诊断完 → 开始讲解薄弱点
    "explain": "practice",   # 讲完 → 建议练习（但由用户选择）
    "practice": "review",    # 练完一批 → 标记为待复习
    "review": "review",      # 复习可以循环
    "answer": "explain",     # 答疑完 → 回到讲解/练习
    "exam": "review",        # 考完 → 针对性复习
}


def next_teach_mode(current: str) -> str:
    """获取当前模式的推荐下一个模式。"""
    return _MODE_TRANSITIONS.get(current, current)
