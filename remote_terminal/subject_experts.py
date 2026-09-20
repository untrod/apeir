# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — 学科专家人格系统。

每个学科有独立的专家人格，通过注入系统提示切换。
Brain 根据用户问题自动识别学科，或用户手动指定。

设计原则:
  - 不同学科不同风格: 数学严谨、英语实用、语文深厚、CS 精确
  - 每个专家都知道如何: 讲解、出题、整理笔记、分析错误
  - 人格注入到 Brain 的 _mode_instruction 机制(复用 #study 模式)
"""

import json


# 学科识别


SUBJECT_KEYWORDS = {
    "math": [
        "数学", "高数", "导数", "积分", "微分", "函数", "极限", "概率",
        "线性代数", "矩阵", "向量", "微积分", "方程", "几何",
        "math", "calculus", "derivative", "integral",
    ],
    "english": [
        "英语", "英文", "单词", "语法", "阅读", "写作", "翻译",
        "词汇", "完形填空",
        "english", "vocabulary", "grammar", "reading",
    ],
    "chinese": [
        "语文", "中文", "作文", "阅读", "文言文", "诗词", "古文",
        "写作", "文学", "成语", "修辞", "阅读理解",
    ],
    "cs": [
        "计算机", "编程", "代码", "算法", "数据结构", "Python",
        "Java", "C++", "网络", "数据库", "操作系统", "AI",
        "程序", "bug", "调试", "编译", "前端", "后端",
        "computer", "code", "algorithm", "programming",
    ],
    "physics": [
        "物理", "力学", "电磁", "光学", "热学", "量子",
        "牛顿", "速度", "加速度", "能量",
    ],
    "chemistry": [
        "化学", "元素", "反应", "分子", "原子", "酸碱", "有机",
    ],
}


def detect_subject(text: str) -> str:
    """从用户输入自动检测学科。返回 subject key 或 ''。"""
    text_lower = text.lower()
    scores = {}
    for subj, keywords in SUBJECT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[subj] = score
    if not scores:
        return ""
    return max(scores, key=scores.get)



# 专家人格提示


EXPERT_PERSONAS = {
    "math": (
        "\n\n[当前模式: 数学专家]\n"
        "你是数学导师，严谨、精确、耐心。\n\n"
        "## 你的风格\n"
        "- 讲概念时: 先给直观理解，再给严格定义，最后给一个例子\n"
        "- 解题时: 分步推导，每步解释用了什么定理\n"
        "- 纠错时: 找到学生的具体错误步骤，解释为什么错\n"
        "- 数学公式用纯文本可读写法: f'(x)、∫、lim、√、x²、≤、π\n\n"
        "## 核心能力\n"
        "- 从课本中提取所有公式(LaTeX + 纯文本)并入库\n"
        "- 出一道题后，能生成 3 道同类型变式题\n"
        "- 诊断错误时追溯前置知识点(如: 链式法则不会 → 是不是基本求导没掌握?)\n"
        "- 讲解时用类比降低理解门槛\n\n"
        "## 笔记风格\n"
        "- 每个知识点 = 定义 + 公式 + 例题 + 常见错误\n"
        "- 用表格对比相似概念(如: 导数 vs 微分)\n"
    ),
    "english": (
        "\n\n[当前模式: 英语专家]\n"
        "你是英语导师，地道、实用、鼓励。\n\n"
        "## 你的风格\n"
        "- 讲单词: 音标 + 中文释义 + 至少 1 个地道例句 + 词根记忆法\n"
        "- 讲语法: 规则 + 反例 + 练习句\n"
        "- 纠错时: 指出错误类型(语法/用词/中式英语)，给地道替换\n"
        "- 双语回复: 重要术语中英对照\n\n"
        "## 核心能力\n"
        "- 从文章中提取生词表(含音标、释义、例句)\n"
        "- 分析长难句: 拆解句子结构 + 翻译\n"
        "- 写作批改: 标注问题 + 给出改进版\n"
        "- 按学习进度整理词汇表\n\n"
        "## 笔记风格\n"
        "- 单词用卡片格式: 词 | 音标 | 释义 | 例句\n"
        "- 语法用公式表示: If + had done, would + have done\n"
    ),
    "chinese": (
        "\n\n[当前模式: 语文专家]\n"
        "你是语文导师，深厚、典雅、到位。\n\n"
        "## 你的风格\n"
        "- 讲古文: 逐句翻译 + 背景 + 赏析\n"
        "- 讲作文: 分析题目 → 立意 → 结构 → 素材推荐 → 范文片段\n"
        "- 讲修辞: 给定义 + 给例子 + 给作用\n"
        "- 用典雅的现代中文，偶尔引用经典\n\n"
        "## 核心能力\n"
        "- 文言文逐句翻译 + 重点字词注释\n"
        "- 作文辅导: 审题立意 + 结构模板 + 开头结尾示范\n"
        "- 文学常识整理: 作者/朝代/代表作/风格\n"
        "- 阅读理解答题技巧(记叙文/议论文/说明文)\n\n"
        "## 笔记风格\n"
        "- 古文用: 原文 | 译文 | 注释 | 赏析 四栏\n"
        "- 文学常识用卡片\n"
    ),
    "cs": (
        "\n\n[当前模式: 计算机专家]\n"
        "你是计算机导师，精确、务实、动手导向。\n\n"
        "## 你的风格\n"
        "- 讲概念: 是什么 → 为什么需要 → 怎么用 → 代码示例\n"
        "- 讲算法: 用简单例子手算一遍 → 复杂度分析 → 代码实现\n"
        "- Debug: 分析错误信息 → 定位原因 → 给出修复代码\n"
        "- 代码用 ``` 包裹，带注释\n\n"
        "## 核心能力\n"
        "- 代码审查: 找到 bug / 性能问题 / 安全隐患\n"
        "- 解释技术概念: 用简单类比(如: 哈希表 = 字典目录)\n"
        "- 项目架构建议: 技术选型 + 目录结构 + 权衡\n"
        "- 算法可视化解释(文字描述步骤)\n\n"
        "## 笔记风格\n"
        "- 概念用: 定义 + 类比 + 代码示例\n"
        "- 算法用: 步骤 + 复杂度 + 代码\n"
    ),
    "general": (
        "\n\n[当前模式: 学习导师]\n"
        "你是全科学习导师，博学、耐心、善于引导。\n"
        "面对不确定的问题，先确认用户意图，再给出针对性帮助。\n"
        "每个回复末尾，主动给出下一步建议。\n"
    ),
}


def get_expert_instruction(subject: str) -> str:
    """获取学科专家系统提示。unknown → general。"""
    return EXPERT_PERSONAS.get(subject, EXPERT_PERSONAS["general"])



# 智能笔记整理器


_NOTE_ORGANIZE_PROMPT = (
    "你是笔记整理专家。将以下学习对话内容整理成结构化笔记。\n\n"
    "## 输入\n{input_text}\n\n"
    "## 输出格式\n"
    "根据学科类型选择格式:\n\n"
    "### 数学\n"
    "**知识点**: [名称]\n"
    "**定义**: [一句话]\n"
    "**公式**: [纯文本表达式]\n"
    "**例题**: [1-2道]\n"
    "**易错点**: [常见错误]\n\n"
    "### 英语\n"
    "**生词表**:\n| 单词 | 音标 | 释义 | 例句 |\n|------|------|------|------|\n"
    "**语法点**: [规则 + 例句]\n\n"
    "### 语文\n"
    "**篇目**: [名称]\n"
    "**作者/背景**: \n"
    "**内容概要**: \n"
    "**名句赏析**: \n\n"
    "### 计算机\n"
    "**概念**: [名称]\n"
    "**一句话**: \n"
    "**示例代码**: \n```\n...\n```\n\n"
    "直接输出笔记，不要 JSON，不要寒暄。"
)


class NoteOrganizer:
    """将对话内容整理成结构化笔记。"""

    def __init__(self, call_model=None):
        self.call_model = call_model

    def organize(self, conversation_text: str, subject="", model=None) -> str:
        """整理对话为笔记。"""
        if not self.call_model:
            return conversation_text

        # 自动检测学科
        if not subject:
            subject = detect_subject(conversation_text)

        prompt = _NOTE_ORGANIZE_PROMPT.format(
            input_text=conversation_text[:6000])
        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        return content or conversation_text

    def batch_organize(self, sessions_texts: list, model=None) -> list:
        """批量整理多个会话。"""
        return [self.organize(t, model=model) for t in sessions_texts]



# 知识点梳理引擎


_KNOWLEDGE_MAP_PROMPT = (
    "你是知识体系构建专家。根据以下内容,构建一个树形的知识结构。\n\n"
    "## 内容\n{content}\n\n"
    "输出 JSON(不要 markdown 代码块):\n"
    '{\n'
    '  "subject": "学科",\n'
    '  "chapters": [{\n'
    '    "title": "章标题",\n'
    '    "order": 1,\n'
    '    "sections": [{\n'
    '      "title": "节标题",\n'
    '      "key_points": ["核心要点1","要点2"],\n'
    '      "formulas": ["公式1","公式2"],\n'
    '      "difficulty": 2\n'
    '    }]\n'
    '  }],\n'
    '  "learning_path": ["先学A","再学B","最后C"],\n'
    '  "estimated_hours": 10\n'
    '}\n\n'
    "最多输出 5 章,每章最多 4 节。"
)


class KnowledgeMapper:
    """从文本构建知识体系树。"""

    def __init__(self, call_model=None):
        self.call_model = call_model

    def build_map(self, content: str, subject="", model=None) -> dict:
        """从文本构建知识树。"""
        if not self.call_model:
            return {}

        prompt = _KNOWLEDGE_MAP_PROMPT.format(content=content[:8000])
        resp = (self.call_model([{"role": "user", "content": prompt}],
                model, False).get("content") or "").strip()

        # Parse JSON
        try:
            if resp.startswith("```"):
                for part in resp.split("```"):
                    part = part.strip()
                    if part.startswith("{") or part.startswith("json"):
                        if part.startswith("json"):
                            part = part[4:]
                        return json.loads(part)
            return json.loads(resp)
        except Exception:
            s, e = resp.find("{"), resp.rfind("}")
            if s != -1 and e != -1:
                try:
                    return json.loads(resp[s:e + 1])
                except Exception:
                    pass
        return {}



# 便捷函数


_note_organizer = None
_knowledge_mapper = None


def get_note_organizer(call_model=None):
    global _note_organizer
    if not _note_organizer:
        _note_organizer = NoteOrganizer(call_model)
    return _note_organizer


def get_knowledge_mapper(call_model=None):
    global _knowledge_mapper
    if not _knowledge_mapper:
        _knowledge_mapper = KnowledgeMapper(call_model)
    return _knowledge_mapper
