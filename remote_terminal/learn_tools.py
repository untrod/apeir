# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — Brain 工具定义 + Handler。

提供 8 个学习工具,集成到 brain.py 的 _TOOLS 列表中。
每个 handler 遵循 tools.py 的 ToolResult 约定。
"""

import json
import logging
import os
import time
from datetime import date, timedelta

import learn_db
import doc_engine

log = logging.getLogger("learn_tools")

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learn_docs")



# 工具 JSON Schema 定义


LEARN_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "learn_upload_doc",
            "description": "上传学习文档(课本/讲义/题库)。支持 PDF/Word/txt。上传后自动解析提取知识点和题目。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "文档路径,如 C:\\Users\\xxx\\课本.pdf"},
                    "subject": {"type": "string", "description": "科目: math/english/chinese/cs,默认自动检测"},
                },
                "required": ["filepath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_list_docs",
            "description": "浏览文档库: 列出所有已上传的资料。可按状态筛选(已解析/未解析)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "筛选: all(全部)/ parsed(已解析)/ pending(待解析),默认 all"},
                    "subject": {"type": "string", "description": "按科目筛选,留空=全部"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_parse_doc",
            "description": "选择一篇文档进行 AI 解析(提取知识点+公式+题目)。支持指定页码范围。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "integer", "description": "文档 ID(来自 learn_list_docs)"},
                    "subject": {"type": "string", "description": "指定科目(覆盖自动检测)"},
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_search_kp",
            "description": "搜索知识点。可按科目、关键词查找。返回标题/章节/掌握度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目过滤,如 math/english,留空=全部"},
                    "keyword": {"type": "string", "description": "搜索关键词,如 '导数'"},
                    "limit": {"type": "integer", "description": "返回条数,默认20"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_get_formula",
            "description": "查看一个公式的详情:LaTeX 表达式、纯文本版、来源课本/页码、掌握度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "formula_id": {"type": "integer", "description": "公式 ID"},
                },
                "required": ["formula_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_review_formulas",
            "description": "获取今日待复习的公式列表(按 SM-2 间隔调度)。返回公式名/表达式/掌握度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目过滤,留空=全部"},
                    "count": {"type": "integer", "description": "返回数量,默认5"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_list_progress",
            "description": "查看学习进度:总体统计 + 今日学习数据 + 薄弱知识点Top5。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目过滤,留空=全部"},
                    "days": {"type": "integer", "description": "统计最近N天,默认30"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_record_exercise",
            "description": "记录一道题的做题结果。正确则更新知识点掌握度,错误则创建错题记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise_id": {"type": "integer", "description": "题目 ID(来自 learn_generate_quiz 的输出)"},
                    "correct": {"type": "boolean", "description": "是否做对"},
                    "user_answer": {"type": "string", "description": "用户的答案"},
                },
                "required": ["exercise_id", "correct"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_generate_quiz",
            "description": "根据知识点或公式生成变式练习题。支持指定数量和难度。返回题目+答案。",
            "parameters": {
                "type": "object",
                "properties": {
                    "formula_id": {"type": "integer", "description": "从指定公式出题"},
                    "knowledge_point_id": {"type": "integer", "description": "从指定知识点出题"},
                    "subject": {"type": "string", "description": "从指定科目随机出题"},
                    "count": {"type": "integer", "description": "题目数量,默认3"},
                    "difficulty": {"type": "integer", "description": "难度 1-4,默认根据用户掌握度自适应"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_search_formula",
            "description": "搜索公式库。按科目/关键词查找。返回公式名/纯文本表达式/掌握度/来源。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目过滤"},
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "返回条数,默认15"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_add_exam",
            "description": "注册一场考试。设置考试名称、日期、科目和范围,系统会自动生成备考计划和倒计时。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "考试名称,如 '期末考试-高等数学' 或 '2026年考研'"},
                    "exam_date": {"type": "string", "description": "考试日期 YYYY-MM-DD"},
                    "subjects": {"type": "string", "description": "科目列表,逗号分隔,如 '高等数学,英语,计算机'"},
                    "scope": {"type": "string", "description": "考试范围/考纲(可以是一段描述)"},
                    "target_score": {"type": "string", "description": "目标分数,如 '350/450'"},
                },
                "required": ["name", "exam_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_exam_dashboard",
            "description": "考试仪表盘: 所有 upcoming 考试 + 倒计时 + 覆盖度 + 紧急度。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_exam_detail",
            "description": "单个考试的详细状态: 每科准备度、缺口清单、每日建议学习量、活跃计划。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_id": {"type": "integer", "description": "考试 ID"},
                },
                "required": ["exam_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_generate_study_plan",
            "description": "生成自适应备考计划。根据考试日期和知识缺口,自动分配每天的学习任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_id": {"type": "integer", "description": "考试 ID(不填则用最近一场)"},
                    "minutes_per_day": {"type": "integer", "description": "每天可用时间(分钟),默认60"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_analyze_syllabus",
            "description": "考纲分析: 对比考试范围与已有知识库,找出缺口。AI 告诉你哪些是必考但还没学的。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_id": {"type": "integer", "description": "考试 ID"},
                },
                "required": ["exam_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_study_advice",
            "description": "AI 学习顾问: 综合分析考试、弱项、进度,给出一句话优先级建议 + 今日可执行任务。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_list_courses",
            "description": "浏览所有课程。每门课显示章节数、知识点数、完成度。用户说'我的课程'/'学到哪了'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_course_detail",
            "description": "查看一门课的完整章节树和每章完成度。用户说'高数有哪些章节'/'微积分学到哪了'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "integer", "description": "课程 ID"},
                },
                "required": ["course_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_next_to_learn",
            "description": "推荐下一门该学的章节。用户说'接下来学什么'/'然后呢'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "course_id": {"type": "integer", "description": "课程 ID"},
                },
                "required": ["course_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_build_course",
            "description": "从已有知识库自动构建课程树(LLM 将零散知识点组织成有序章节)。用户说'帮我整理一下课程'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目,如 math"},
                    "course_name": {"type": "string", "description": "课程名,留空自动生成"},
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_auto_variant",
            "description": "为一道错题自动生成2-3道变式题。用户说'这题再练练'/'出点类似的题'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mistake_id": {"type": "integer", "description": "错题 ID"},
                },
                "required": ["mistake_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_achievements",
            "description": "查看学习成就徽章。用户说'我的成就'/'有什么徽章'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_weekly_report",
            "description": "生成本周学习报告。用户说'本周总结'/'周报'/'这周学得怎么样'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_smart_plan",
            "description": "AI智能日计划: 结合今日课表+学习计划+课本内容+进度,自动生成今天的学习清单(复习什么+做什么题+背什么+读什么)。用户说'今天学什么'/'帮我计划'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "available_minutes": {"type": "integer", "description": "今天可用时间(分钟),默认60"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_custom_quiz",
            "description": "生成自定义试卷: 指定题型分布、章节范围、难度。用户说'出张卷子'/'模拟考'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目"},
                    "chapters": {"type": "string", "description": "章节范围,如 '第三章' 或 '第1-3章',留空=全部"},
                    "question_types": {"type": "string", "description": "题型分布,如 '5选择+3填空+2大题',默认3选择+2大题"},
                    "difficulty": {"type": "integer", "description": "难度 1-4,默认自适应"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_export",
            "description": "导出学习数据: 知识点列表/公式表/错题集。输出 Markdown 格式可复制保存。",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "description": "导出内容: all/knowledge/formulas/mistakes,默认 all"},
                    "subject": {"type": "string", "description": "科目过滤,留空=全部"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_focus_history",
            "description": "查看专注学习历史记录。用户说'我的专注记录'/'学了多久'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "最近N天,默认30"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_my_notes",
            "description": "查看历史笔记。用户说'我的笔记'/'之前记了什么'时调用。支持搜索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词,留空=全部"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_focus_start",
            "description": "开始一个专注学习会话(番茄钟)。用户说'开始学习'/'专注模式'/'开始一个番茄'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目"},
                    "task": {"type": "string", "description": "具体任务"},
                    "duration_min": {"type": "integer", "description": "时长(分钟),默认25"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_quick_note",
            "description": "快速记笔记(语音友好)。用户说'记一下:xxx'/'note:xxx'时调用。自动分类为作业/备忘/问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "笔记内容"},
                    "subject": {"type": "string", "description": "科目(留空自动检测)"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_weak_alert",
            "description": "检查弱项预警: 哪些知识点卡住了很久需要攻克。用户说'我的弱项'/'哪里需要加强'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_sprint_mode",
            "description": "激活考前冲刺模式: 密集训练+错题清零+模拟考。用户说'冲刺'/'快考试了怎么办'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_id": {"type": "integer", "description": "考试ID,不填=最近一场"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_micro_learning",
            "description": "生成5分钟微学习片段(适合排队/通勤)。用户说'来点碎片学习'/'5分钟学什么'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目,留空=全部"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_add_timetable",
            "description": "添加课表条目。支持自然语言: '周一上午8-10点高数课在教3'。系统自动检测空闲时间并安排学习。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "自然语言描述,如 '周三下午2点到4点英语课' 或 '周一8:00-9:40高数'"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_my_schedule",
            "description": "查看今日或本周课表。用户说'今天有什么课'/'课表'/'我的安排'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "description": "today(今日)/ week(本周),默认 today"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_free_time",
            "description": "查看今天的空闲时间段。用户说'我今天什么时候有空'/'有什么时间可以学习'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_auto_schedule",
            "description": "在今天的空闲时间自动安排学习任务(弱项复习+公式+作业)。用户说'帮我安排今天的学习'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_add_homework",
            "description": "添加作业/任务。用户说'我有xx作业'/'布置了xx'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "作业标题"},
                    "subject": {"type": "string", "description": "科目"},
                    "due_date": {"type": "string", "description": "截止日期 YYYY-MM-DD,留空=明天"},
                    "estimated_minutes": {"type": "integer", "description": "预计耗时(分钟),默认30"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_my_homework",
            "description": "查看作业列表。用户说'我的作业'/'还有什么作业没做'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_my_profile",
            "description": "查看/编辑学习者的个人画像和学习习惯。用户说'我的档案'/'我的学习习惯'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "view(查看)/ edit(编辑)"},
                    "field": {"type": "string", "description": "edit时: 要修改的字段,如 goals/weak_subjects/style"},
                    "value": {"type": "string", "description": "edit时: 新值"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_remember",
            "description": "记住用户说的一条信息(持久记忆)。用户说'记住...'/'别忘了...'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要记住的内容"},
                    "category": {"type": "string", "description": "分类: goal/preference/struggle/progress,默认 goal"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_flashcard_generate",
            "description": "从知识点或科目生成 Anki 式闪卡。用户说'生成闪卡'/'做点卡片'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_id": {"type": "integer", "description": "知识点 ID(单个知识点出卡)"},
                    "subject": {"type": "string", "description": "科目(全部知识点出卡)"},
                    "count": {"type": "integer", "description": "生成数量,默认10"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_flashcard_review",
            "description": "开始闪卡复习: 获取今日待复习的卡片。用户说'复习卡片'/'闪卡'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "deck": {"type": "string", "description": "牌组名(按科目),留空=全部"},
                    "count": {"type": "integer", "description": "卡片数,默认10"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_flashcard_rate",
            "description": "对一张闪卡评分(复习后)。评分: 0完全忘 1有印象 3勉强 5秒答。系统自动安排下次复习时间。",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_id": {"type": "integer", "description": "卡片 ID"},
                    "quality": {"type": "integer", "description": "0-5评分"},
                },
                "required": ["card_id", "quality"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_fuzzy_search",
            "description": "模糊搜索: 用户说的词不精确时,在知识库中找最接近的匹配。用于纠正可能的语音识别错误。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "用户说的模糊词"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_quick_review",
            "description": "快速复习: 5分钟速览今日最该复习的内容(到期公式+薄弱知识点+未复习错题)。适合用户说'快速复习'/'来一遍'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目,留空=全部"},
                    "count": {"type": "integer", "description": "条数,默认5"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_study_streak",
            "description": "查看学习连续打卡天数、累计统计。用户说'打卡'/'连续学了几天'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_daily_review",
            "description": "生成今日学习复盘: 学了什么、薄弱项、进步趋势、明日建议。从错误中找根因,从数据中找规律。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_plan_tomorrow",
            "description": "根据当前进度和弱项,自动生成明日学习计划。考虑间隔复习、错题重做、新内容推进。",
            "parameters": {
                "type": "object",
                "properties": {
                    "available_minutes": {"type": "integer", "description": "明天可用时间(分钟),默认60"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_diagnose_mistake",
            "description": "诊断一个错题的根因: 是概念不清、计算错误还是前置知识欠缺。给出复习建议。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mistake_id": {"type": "integer", "description": "错题 ID"},
                },
                "required": ["mistake_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_catalog",
            "description": "查看知识库目录(阶段→科目→章节→知识点,仅标题+ID+掌握度,不含正文,省 token)。回答前先用它找到相关知识点 ID,再用 learn_get 调取正文。可按 stage/subject 缩小范围。",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {"type": "string", "description": "阶段筛选,如 考研/高考,留空=全部"},
                    "subject": {"type": "string", "description": "科目筛选,如 高等数学,留空=全部"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_get",
            "description": "按知识点 ID 调取完整正文内容(配合 learn_catalog:先看目录选 ID,再用本工具取详情)。一次可取多个。",
            "parameters": {
                "type": "object",
                "properties": {
                    "ids": {"type": "string", "description": "知识点 ID,逗号分隔,如 '12,15,18'"},
                },
                "required": ["ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_practice",
            "description": "从用户【已上传的题库/真题】里出真题练习(不是现编)。要练真题/做卷子时优先用它;题库为空再用 learn_generate_quiz 现编。出题后用 learn_record_exercise 记录对错。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目,留空=全部"},
                    "knowledge_point_id": {"type": "integer", "description": "只出某知识点的题,可选"},
                    "count": {"type": "integer", "description": "题数,默认1,最多5"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_vocab",
            "description": "今日单词:返回到期要复习的词 + 该背的新词(来自用户上传的单词资料)。用户说'背单词/记单词/今天背哪些词'时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "new": {"type": "integer", "description": "新词数量,默认10"},
                    "review": {"type": "integer", "description": "复习词数量,默认10"},
                    "subject": {"type": "string", "description": "科目/词库,留空=全部"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_today_plan",
            "description": "生成【自适应今日计划】:按当前掌握度/到期复习/薄弱项/章节进度实时编排今天该学什么(知识点颗粒度)。用户问'今天学什么/今日计划/帮我安排'时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer", "description": "今天可用分钟数,可选(默认90)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_coverage",
            "description": "查看大纲覆盖度:各科目 已掌握/总 知识点 + 平均掌握度。回答'我学到哪了/还差多少'时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目,留空=全部"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_merge_subject",
            "description": "合并科目别名:把一个科目下的所有知识点/资料并到另一个科目(如把'高数'并到'高等数学'),整理库时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string", "description": "要被合并掉的科目名"},
                    "to": {"type": "string", "description": "合并到的目标科目名"},
                },
                "required": ["from", "to"],
            },
        },
    },
    # 学习计划管理
    {
        "type": "function",
        "function": {
            "name": "learn_my_plan",
            "description": "查看当前学习阶段计划：进度、今日任务、已完成天数。用户说'我的计划/学到哪了/进度怎么样/阶段计划'时用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_today_tasks",
            "description": "查看今日详细学习任务：每科的讲义内容、必须掌握的知识点、练习题。用户说'今天学什么/今日任务/今天要学哪些'时优先用这个。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期(YYYY-MM-DD),默认今天"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_checkin",
            "description": "每日学习打卡：记录今天完成了哪些科目、学了多久、反思和收获。用户说'打卡/今天学完了/复盘/总结一下今天'时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "math_done": {"type": "boolean", "description": "高数是否完成"},
                    "english_done": {"type": "boolean", "description": "英语是否完成"},
                    "cs_done": {"type": "boolean", "description": "计算机是否完成"},
                    "chinese_done": {"type": "boolean", "description": "语文是否完成"},
                    "duration_minutes": {"type": "integer", "description": "今天实际学习时长(分钟)"},
                    "reflection": {"type": "string", "description": "今日反思:学会了什么、哪里还不会、明天注意什么"},
                    "difficulties": {"type": "string", "description": "遇到的困难"},
                    "achievements": {"type": "string", "description": "今日收获/突破"},
                    "mood": {"type": "integer", "description": "心情 1-5"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_phase_summary",
            "description": "生成/查看阶段学习总结：薄弱点、强项、错题归类、下阶段建议。可以跨阶段传承记忆。用户说'阶段总结/这个阶段学完了/帮我总结一下/生成总结报告'时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "generate(生成新总结) 或 view(查看已有总结),默认 generate"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_plan_detail",
            "description": "查看某一天的完整学习讲义（四科详细内容+必须掌握+练习题）。用户问具体某天学什么时用，如'7月3号学什么'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期(YYYY-MM-DD),如 2026-07-03"},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_set_day",
            "description": "手动设置当前学习进度到第N天。当学习节奏与实际计划不同步时使用。用户说'学到第3天了/跳到第5天/重设进度'时用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer", "description": "跳到第几天(1-based)。如 day=3 表示学到第3天"},
                },
                "required": ["day"],
            },
        },
    },
    # RAG 语义检索工具
    {
        "type": "function",
        "function": {
            "name": "learn_search_semantic",
            "description": "【语义搜索】用自然语言描述想找什么,AI 理解语义后在知识库中检索最相关的知识点。适合模糊但需要精准匹配的场景。用户说'导数的定义'/'微积分基本定理怎么证明'时用。返回相关知识点摘要+ID,再用 learn_get 获取正文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "自然语言查询,如'导数的定义是什么'"},
                    "subject": {"type": "string", "description": "可选,科目过滤: 高等数学/英语/大学语文/计算机"},
                    "top_k": {"type": "integer", "description": "返回结果数,默认5,最多10"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_ask_document",
            "description": "【文档问答】在已上传的文档库中语义搜索相关内容片段,用于 AI 回答基于文档的问题。用户说'这本教材里关于xxx的部分在哪'/'总结一下这篇论文'时用。返回相关文档片段供 LLM 参考回答。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询问题,如'第三章讲了什么'"},
                    "subject": {"type": "string", "description": "可选,科目过滤"},
                    "doc_type": {"type": "string", "description": "可选,文档类型: 课本/讲义/题库/试卷/笔记"},
                    "top_k": {"type": "integer", "description": "返回片段数,默认5,最多10"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "learn_rebuild_index",
            "description": "【管理员】重建知识库向量索引。数据迁移、发现检索不准或安装向量数据库后初次使用时调用。返回索引的知识点数量。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


def get_learn_tool_defs():
    return LEARN_TOOL_DEFS



# 工具 Handler

# 注意: handler 签名遵循 tools.py 的约定:
#   handler(args, session, executor) -> ToolResult
# 但由于部分 handler 需要调用 LLM(call_model),单独处理。

class LearnHandler:
    """封装所有学习工具的处理逻辑。"""

    def __init__(self, call_model=None):
        self.call_model = call_model  # 延迟注入,避免循环引用 brain
        learn_db.init()
        os.makedirs(DOCS_DIR, exist_ok=True)

    def handle_list_docs(self, args, session, executor):
        """浏览文档库。"""
        status = (args.get("status") or "all").strip().lower()
        subject = (args.get("subject") or "").strip()

        if status == "parsed":
            docs = learn_db.list_documents(parsed=True)
        elif status == "pending":
            docs = learn_db.list_documents(parsed=False)
        else:
            docs = learn_db.list_documents()

        if subject:
            docs = [d for d in docs if d.get("subject","") == subject]

        if not docs:
            return _ok(
                "📂 文档库为空。\n\n"
                "用 learn_upload_doc 上传课本/讲义/题库(PDF/Word/txt),"
                "上传后自动解析提取知识点和公式。")

        lines = ["📂 文档库:\n"]
        lines.append("| ID | 文件名 | 类型 | 科目 | 页数 | 状态 | 提取 |")
        lines.append("|----|--------|------|------|------|------|------|")
        for d in docs:
            status_icon = "✅" if d.get("parsed") else "⏳"
            status_text = "已解析" if d.get("parsed") else "待解析"
            kp = d.get("kp_count", 0)
            ex = d.get("ex_count", 0)
            extracted = f"{kp}知+{ex}题" if kp or ex else "-"
            lines.append(
                f"| {d['id']} | {d['filename'][:20]} | {d.get('filetype','')} "
                f"| {d.get('subject','-')} | {d.get('total_pages','?')} "
                f"| {status_icon} {status_text} | {extracted} |")
        lines.append(f"\n共 {len(docs)} 篇文档。对某篇执行 `learn_parse_doc doc_id=N` 进行解析。")
        return _ok("\n".join(lines))

    def handle_parse_doc(self, args, session, executor):
        """选择一篇文档进行 AI 解析。"""
        doc_id = args.get("doc_id")
        if not doc_id:
            return _error("doc_id 不能为空(来自 learn_list_docs 的 ID 列)")
        doc = learn_db.get_document(int(doc_id))
        if not doc:
            return _error(f"文档 ID {doc_id} 不存在")

        filepath = doc.get("filepath", "")
        subject = (args.get("subject") or doc.get("subject") or "").strip()

        if not filepath or not os.path.isfile(filepath):
            return _error(f"文档文件不存在: {filepath}\n请重新上传。")

        try:
            result = doc_engine.process_document(
                filepath, self.call_model, subject=subject,
                on_progress=lambda stage, cur, tot: log.info(
                    "解析 %s: %s %d/%d", doc['filename'], stage, cur, tot))
            return _ok(
                f"📖 '{doc['filename']}' 解析完成。\n\n"
                f"- 页数: {result.get('pages',0)}\n"
                f"- 新增知识点: {result.get('kps_added',0)}\n"
                f"- 新增公式: {result.get('formulas_added',0)}\n"
                f"- 新增题目: {result.get('exercises_added',0)}\n\n"
                f"现在可以:\n"
                f"- learn_search_kp 搜索知识点\n"
                f"- learn_review_formulas 查看公式\n"
                f"- learn_generate_quiz 出题练习")
        except Exception as e:
            log.error("解析文档失败: %s", e)
            return _error(f"解析失败: {e}")

    def handle_upload_doc(self, args, session, executor):
        """上传并解析文档。"""
        filepath = (args.get("filepath") or "").strip().strip('"')
        subject = (args.get("subject") or "").strip()
        if not filepath:
            return _error("filepath 不能为空")
        if not os.path.isfile(filepath):
            return _error(f"文件不存在: {filepath}")

        try:
            result = doc_engine.process_document(
                filepath, self.call_model, subject=subject,
                on_progress=lambda stage, cur, tot: log.info(
                    "文档处理进度: %s %d/%d", stage, cur, tot))
            return _ok(
                f"文档 '{result['filename']}' 处理完成。\n"
                f"- 页数: {result['pages']}\n"
                f"- 新增知识点: {result['kps_added']}\n"
                f"- 新增公式: {result['formulas_added']}\n"
                f"- 新增题目: {result['exercises_added']}\n\n"
                f"可以用 learn_search_kp 搜索知识点, learn_review_formulas 查看公式。")
        except Exception as e:
            log.error("文档处理失败: %s", e)
            return _error(f"文档处理失败: {e}")

    def handle_search_kp(self, args, session, executor):
        subject = (args.get("subject") or "").strip()
        keyword = (args.get("keyword") or "").strip()
        limit = min(args.get("limit") or 20, 50)
        results = learn_db.search_knowledge_points(subject, keyword, limit)
        if not results:
            return _ok("未找到匹配的知识点。可以用 learn_upload_doc 上传课本后自动提取。")
        lines = []
        for r in results:
            m = r.get("mastery", 0)
            bar = _mastery_bar(m)
            lines.append(
                f"**[{r['id']}]** {r.get('chapter','')} / {r.get('section','')} / "
                f"{r['title']} ({r['subject']}) | 掌握 {bar} {m:.0f}%")
        return _ok("\n".join(lines))

    # RAG 语义检索
    def handle_search_semantic(self, args, session, executor):
        """语义搜索知识点——用自然语言描述想找什么,AI 理解语义后检索最相关的知识点。
        适合: "导数的定义是什么" "微积分基本定理怎么证明" 等模糊但需要精准匹配的场景。"""
        query = (args.get("query") or "").strip()
        if not query:
            return _err("请提供查询内容(query)")
        subject = (args.get("subject") or "").strip()
        top_k = min(args.get("top_k") or 5, 10)

        try:
            import vector_store
        except ImportError:
            return _err("向量数据库未安装。服务器管理员: pip install chromadb sentence-transformers")

        results = vector_store.search_knowledge(query, top_k=top_k, subject=subject)
        if not results:
            return _ok("未找到语义匹配的知识点。可以: 1) 尝试更具体的描述 2) 用 learn_upload_doc 上传相关资料 3) 用 learn_search_kp 做关键词搜索")

        lines = [f"🔍 「{query}」的语义检索结果:"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n**{i}. [{r['kp_id']}] {r['title']}** (相似度: {r['score']}, {r['subject']})")
            # 截取关键内容(前300字)
            preview = r['content'][:300]
            if len(r['content']) > 300:
                preview += "..."
            lines.append(f"   {preview}")
        lines.append("\n💡 用 learn_get(knowledge_id=ID) 获取完整正文。")
        return _ok("\n".join(lines))

    def handle_ask_document(self, args, session, executor):
        """针对特定文档的 RAG 问答——用语义搜索在文档中找到最相关的片段,让 LLM 基于这些片段回答。
        适合: "这本教材里关于xxx的部分在哪里" "总结一下这篇论文" """
        query = (args.get("query") or "").strip()
        if not query:
            return _err("请提供查询问题(query)")
        subject = (args.get("subject") or "").strip()
        doc_type = (args.get("doc_type") or "").strip()
        top_k = min(args.get("top_k") or 5, 10)

        try:
            import vector_store
        except ImportError:
            return _err("向量数据库未安装。服务器管理员: pip install chromadb sentence-transformers")

        results = vector_store.search_documents(query, top_k=top_k, subject=subject, doc_type=doc_type)
        if not results:
            return _ok("未在文档库中找到相关内容。")

        lines = [f"📄 「{query}」的文档检索结果:"]
        for i, r in enumerate(results, 1):
            lines.append(f"\n**{i}. [doc#{r['doc_id']}]** ({r['subject']}/{r['doc_type']} | 相似度: {r['score']})")
            lines.append(f"   {r['content'][:400]}")
        lines.append("\n💡 LLM 会基于以上片段回答你的问题。")
        return _ok("\n".join(lines))

    def handle_rebuild_index(self, args, session, executor):
        """重建知识库向量索引。数据迁移或发现检索不准时使用。"""
        try:
            import vector_store
        except ImportError:
            return _err("向量数据库未安装")
        n = vector_store.rebuild_knowledge_index()
        return _ok(f"✅ 向量索引重建完成, 共 {n} 个知识点已索引。")

    def handle_catalog(self, args, session, executor):
        """看知识目录(只有标题+id+掌握度,不含正文),用于先选后取,省 token。"""
        stage = (args.get("stage") or "").strip()
        subject = (args.get("subject") or "").strip()
        catalog = learn_db.get_catalog(stage, subject)
        if not catalog:
            return _ok("知识库还没有内容,先上传课本/资料(电脑访问 /upload)。")
        lines = []
        for st, subs in catalog.items():
            lines.append(f"【{st}】")
            for sj, chaps in subs.items():
                lines.append(f"◆ {sj}")
                for ch, kps in chaps.items():
                    titles = " ".join(f"[{k['id']}]{k['title']}({k['mastery']}%)" for k in kps[:40])
                    lines.append(f"  · {ch}: {titles}")
        out = "\n".join(lines)
        if len(out) > 6000:
            out = out[:6000] + "\n…(目录较大,可加 subject/stage 参数缩小范围)"
        out += "\n\n→ 选好后用 learn_get 传 ids 调取这些知识点的完整内容。"
        return _ok(out)

    def handle_get_kp(self, args, session, executor):
        """按 id 调取知识点完整内容(配合 learn_catalog 用)。"""
        raw = args.get("ids") or args.get("kp_ids") or ""
        if isinstance(raw, str):
            ids = [int(x) for x in raw.replace("，", ",").split(",") if x.strip().isdigit()]
        elif isinstance(raw, list):
            ids = [int(x) for x in raw if str(x).strip().isdigit()]
        else:
            ids = []
        if not ids:
            return _error("请提供 ids(知识点ID,逗号分隔或数组)")
        details = learn_db.get_kp_details(ids[:30])
        if not details:
            return _ok("没找到这些 id 的知识点。")
        blocks = []
        for d in details:
            blocks.append(
                f"**[{d['id']}] {d['title']}** ({d.get('subject','')}/{d.get('chapter','')})\n"
                f"{d.get('content','') or '(无正文)'}")
        return _ok("\n\n---\n\n".join(blocks))

    def handle_practice(self, args, session, executor):
        """从用户上传的题库/真题里出真题(不是现编)。配合 learn_record_exercise 判分。"""
        subject = (args.get("subject") or "").strip()
        kp_id = args.get("knowledge_point_id")
        count = min(args.get("count") or 1, 5)
        try:
            ex = learn_db.search_exercises(
                subject=subject, kp_id=int(kp_id) if kp_id else None, limit=80)
        except Exception:
            ex = []
        if not ex:
            return _ok("题库里还没有真题(传一份『题库/试卷』类型资料即可)。要我先现编几道吗?")
        import random
        picks = random.sample(ex, min(count, len(ex)))
        qs = "\n\n".join(f"**[题{e['id']}]** {e['question']}" for e in picks)
        ans = "\n".join(f"[题{e['id']}标准答案] {e.get('answer','')}" for e in picks)
        return _ok(qs + "\n\n(让用户作答后,你对照下面标准答案判分,别直接公布;判完用 "
                   "learn_record_exercise 记录对错。)\n<!--标准答案,勿直接发给用户-->\n" + ans)

    def handle_vocab(self, args, session, executor):
        """今日单词:到期复习词 + 新词(从词卡库)。背单词/记单词时用。"""
        try:
            n_new = min(int(args.get("new") or 10), 30)
        except Exception:
            n_new = 10
        try:
            n_due = min(int(args.get("review") or 10), 30)
        except Exception:
            n_due = 10
        deck = (args.get("subject") or "").strip()
        due = [c for c in learn_db.get_due_flashcards(deck=deck, limit=60)
               if c.get("repetitions", 0) > 0][:n_due]
        new = learn_db.get_new_flashcards(deck=deck, limit=n_new)
        if not due and not new:
            return _ok("词汇库还是空的。上传『单词/词汇』类资料(电脑 /upload,类型选单词)即可。")
        lines = []
        if due:
            lines.append(f"🔁 今日复习({len(due)}个):")
            for c in due:
                lines.append(f"- {c['front']} = {c['back']}")
        if new:
            lines.append(f"\n🆕 今日新词({len(new)}个):")
            for c in new:
                ex = f"  例:{c['hint']}" if c.get("hint") else ""
                lines.append(f"- {c['front']} = {c['back']}{ex}")
        lines.append("\n(背/复习完告诉我哪些记住了、哪些没记住,我用 SM-2 更新下次复习时间。)")
        return _ok("\n".join(lines))

    # 学习计划管理 handlers

    def handle_my_plan(self, args, session, executor):
        """查看当前阶段计划+节奏分析。"""
        phase = learn_db.get_active_phase()
        if not phase:
            return _ok("还没有激活的学习阶段。")
        progress = learn_db.get_phase_progress(phase["id"])
        current = learn_db.get_current_plan()
        total = learn_db.get_phase_plans_count(phase["id"])
        cur_day = phase.get("current_day", 1)
        pace = learn_db.get_pace_analysis()

        lines = [
            f"## 📋 {phase['name']}",
            f"计划日期: {phase['start_date']} ~ {phase['end_date']}（固定，不可偏移）",
            "截止: 7月20日前必须完成（进辅导班）",
            "",
        ]

        if pace:
            lines.append("### ⏱ 节奏分析")
            lines.append(f"{pace['urgency_text']}")
            lines.append(f"学习进度: 第{cur_day}/{total}天 | 日历: 今天应学到第{pace['expected_today']}天")
            lines.append(f"剩余: {pace['remaining_plan_days']}天计划 / {pace['calendar_remaining_days']}天日历 | 需每天完成 {pace['needed_pace']} 天")
            if pace.get("catchup_suggestion"):
                lines.append(f"💡 {pace['catchup_suggestion']}")

        lines += [
            "",
            f"打卡: {progress['checkin_count']} 次 | 完成: {progress['completed_days']}/{total} 天 ({progress['progress_pct']}%)",
        ]

        if current:
            subjs = []
            for s in ["math","english","cs","chinese"]:
                field = f"{'math' if s=='math' else 'english' if s=='english' else 'cs' if s=='cs' else 'chinese'}_content"
                val = current.get(field, "")
                if val and val.strip():
                    label = {"math":"高数","english":"英语","cs":"计算机","chinese":"语文"}[s]
                    subjs.append(f"  **{label}**: {val[:60]}")
            lines.append(f"\n### 📅 当前: 第{cur_day}天({current['date']}) · {current.get('phase_position','')}")
            lines.extend(subjs)
            if current.get("study_time"):
                lines.append(f"  建议时间: {current['study_time']}")

        return _ok("\n".join(lines))

    def handle_today_tasks(self, args, session, executor):
        """查看当前应学的详细任务（按学习节奏）。指定 date 可跳转。"""
        date_str = (args.get("date") or "").strip()
        plan = None

        if date_str:
            plan = learn_db.get_today_plan(date_str)
            source = f"指定日期 {date_str}"
        else:
            plan = learn_db.get_current_plan()
            if plan:
                phase = learn_db.get_active_phase()
                cur = phase.get("current_day", 1) if phase else 1
                source = f"第{cur}天 ({plan.get('date','')})"
            else:
                return _ok("没有激活的学习计划。")

        if not plan:
            return _ok(f"{source} 没有安排。说'我的计划'查看整体进度。")

        lines = [f"## 📅 {source} · {plan['phase_position']}", ""]

        for s, label in [("math","高数"),("english","英语"),("cs","计算机"),("chinese","语文")]:
            content_field = f"{s}_content"
            detail_field = f"{'math' if s=='math' else 'english' if s=='english' else 'cs' if s=='cs' else 'chinese'}_detail"
            content = plan.get(content_field, "")
            detail = plan.get(detail_field, "")
            if content or detail:
                lines.append(f"### {label}")
                if content:
                    lines.append(f"**内容**: {content}")
                if detail:
                    lines.append(f"**详细讲义**:\n{detail[:600]}")
                lines.append("")

        lines.append(f"**⏱ 时间**: {plan.get('study_time','')}")
        lines.append(f"**📤 产出**: {plan.get('expected_output','')}")
        lines.append(f"**🔍 复盘**: {plan.get('review_focus','')}")

        must_know = plan.get("must_know", "")
        exercises = plan.get("exercises", "")
        if must_know:
            lines.append(f"\n### ⭐ 今日必会\n{must_know}")
        if exercises:
            lines.append(f"\n### ✏️ 练习\n{exercises}")
        lines.append(f"\n状态: {'✅ 已完成' if plan.get('status')=='done' else '⏳ 待完成'}")

        return _ok("\n".join(lines))

    def handle_checkin(self, args, session, executor):
        """每日打卡+自动推进学习日。"""
        phase = learn_db.get_active_phase()
        if not phase:
            return _ok("没有激活的学习阶段。")
        plan = learn_db.get_current_plan()
        if not plan:
            return _ok("今天没有计划安排。")

        plan_id = plan["id"]
        cur_day = phase.get("current_day", 1)
        total = learn_db.get_phase_plans_count(phase["id"])

        completed = {
            "math": bool(args.get("math_done", True)),
            "english": bool(args.get("english_done", True)),
            "cs": bool(args.get("cs_done", True)),
            "chinese": bool(args.get("chinese_done", True)),
        }
        duration = int(args.get("duration_minutes") or 0)
        reflection = str(args.get("reflection") or "").strip()
        difficulties = str(args.get("difficulties") or "").strip()
        achievements = str(args.get("achievements") or "").strip()
        mood = min(max(int(args.get("mood") or 3), 1), 5)

        from datetime import date
        learn_db.checkin(plan_id, date.today().isoformat(), completed, duration, reflection, difficulties, achievements, mood)
        done_count = sum(1 for v in completed.values() if v)
        all_done = done_count == 4

        if all_done:
            learn_db.update_plan_status(plan_id, "done")
            new_day = learn_db.advance_day()
            next_plan_msg = f"\n➡️ 已推进到第{new_day}天" if new_day > cur_day else ""
            status_emoji = "🎉"
        elif done_count >= 2:
            learn_db.update_plan_status(plan_id, "partial")
            next_plan_msg = f"\n⚠️ 未全部完成，明天继续第{cur_day}天"
            status_emoji = "👍"
        else:
            next_plan_msg = f"\n📝 继续第{cur_day}天的学习"
            status_emoji = "📝"

        lines = [f"{status_emoji} 打卡 · 第{cur_day}/{total}天{next_plan_msg}", ""]
        lines.append(f"完成: {done_count}/4科 ({'高数' if completed['math'] else ''}{' 英语' if completed['english'] else ''}{' 计算机' if completed['cs'] else ''}{' 语文' if completed['chinese'] else ''})")
        if duration > 0:
            lines.append(f"学习时长: {duration} 分钟")
        if achievements:
            lines.append(f"收获: {achievements}")
        if difficulties:
            lines.append(f"困难: {difficulties}")
        if reflection:
            lines.append(f"反思: {reflection}")
        lines.append(f"心情: {'⭐' * mood}")

        progress = learn_db.get_phase_progress(phase["id"])
        lines.append(f"\n阶段进度: {progress['completed_days']}/{total} 天 ({progress['progress_pct']}%)")

        return _ok("\n".join(lines))

    def handle_phase_summary(self, args, session, executor):
        """生成/查看阶段总结。"""
        action = str(args.get("action") or "generate").strip()
        phase = learn_db.get_active_phase()
        if not phase:
            return _error("没有激活的学习阶段。")

        if action == "view":
            summaries = learn_db.get_phase_summaries(phase["id"])
            if not summaries:
                return _ok("还没有阶段总结，说'生成阶段总结'来创建。")
            lines = [f"## 📊 {phase['name']} 总结", ""]
            for s in summaries:
                lines.append(f"### {s['subject']} · {s['summary_type']}")
                lines.append(s["content"][:500])
                lines.append("")
            return _ok("\n".join(lines))

        # generate: 收集数据让 LLM 总结
        progress = learn_db.get_phase_progress(phase["id"])
        checkins = learn_db.get_checkins(phase["id"])
        plans = learn_db.get_phase_plans(phase["id"])

        # 收集错题
        try:
            mistakes = learn_db.get_recent_mistakes(limit=20)
            mistake_text = "\n".join(f"- [{m['subject']}] {m.get('question','')[:80]} → {m.get('root_cause','')[:80]}" for m in mistakes[:10])
        except Exception:
            mistake_text = "（暂无错题数据）"

        # 收集打卡反思
        reflection_text = "\n".join(
            f"- {c['date']}: 收获={c.get('achievements','')[:60]} 困难={c.get('difficulties','')[:60]}"
            for c in checkins[-7:]
        ) if checkins else "（暂无反思记录）"

        # 构建总结请求（返回给 LLM 处理）
        out = (
            f"## 📊 {phase['name']} 阶段总结\n\n"
            f"### 基础数据\n"
            f"- 进度: {progress['completed_days']}/{progress['total_days']} 天完成\n"
            f"- 打卡: {progress['checkin_count']} 次\n"
            f"- 日期: {phase['start_date']} ~ {phase['end_date']}\n\n"
            f"### 近期错题\n{mistake_text}\n\n"
            f"### 近期反思\n{reflection_text}\n\n"
            f"---\n"
            f"**请 AI 根据以上数据生成结构化阶段总结，包括：**\n"
            f"1. 四科掌握度评估（强项/弱项）\n"
            f"2. 高频错误类型和根因\n"
            f"3. 学习效率分析\n"
            f"4. 下阶段针对性建议\n"
            f"5. 需要传承到下一阶段的记忆点\n\n"
            f"生成后调用 learn_remember 保存关键记忆，然后用 add_phase_summary 将总结入库。"
        )
        return _ok(out)

    def handle_plan_detail(self, args, session, executor):
        """查看某天完整讲义。"""
        date_str = str(args.get("date") or "").strip()
        if not date_str:
            return _error("需要指定日期，如 date=2026-07-03")
        plan = learn_db.get_today_plan(date_str)
        if not plan:
            return _ok(f"📅 {date_str} 没有安排。")

        lines = [f"## 📅 {date_str} · {plan['phase_position']}", ""]

        for s, label in [("math","高数"),("english","英语"),("cs","计算机"),("chinese","语文")]:
            content_field = f"{s}_content"
            detail_field = f"{'math' if s=='math' else 'english' if s=='english' else 'cs' if s=='cs' else 'chinese'}_detail"
            content = plan.get(content_field, "")
            detail = plan.get(detail_field, "")
            if content or detail:
                lines.append(f"### {label}")
                if content:
                    lines.append(f"{content}")
                if detail:
                    lines.append(f"\n{detail}")
                lines.append("")

        must_know = plan.get("must_know", "")
        exercises = plan.get("exercises", "")
        if must_know:
            lines.append(f"### ⭐ 必须掌握\n{must_know}")
        if exercises:
            lines.append(f"### ✏️ 练习检验\n{exercises}")

        return _ok("\n".join(lines))

    def handle_set_day(self, args, session, executor):
        """手动跳到第N天。"""
        day = int(args.get("day") or 0)
        if day < 1:
            return _error("day 必须 >= 1")
        learn_db.set_current_day(day)
        plan = learn_db.get_current_plan()
        if plan:
            total = learn_db.get_phase_plans_count(learn_db.get_active_phase()["id"])
            return _ok(f"已跳到第{day}天 · {plan['date']} ({plan['phase_position']})\n共{total}天，说'今天学什么'开始学习。")
        return _ok(f"已设置到第{day}天（共?天）")

    def handle_today_plan(self, args, session, executor):
        """自适应今日计划(实时按进度编排)。"""
        import plan_engine
        try:
            mins = int(args.get("minutes") or 0) or None
        except Exception:
            mins = None
        return _ok(plan_engine.render_text(plan_engine.compute_today(mins)))

    def handle_coverage(self, args, session, executor):
        """大纲覆盖度:各科目 已掌握/总 知识点。"""
        subject = (args.get("subject") or "").strip()
        cov = learn_db.get_coverage(subject)
        if not cov:
            return _ok("还没有知识点,先上传课本(电脑访问 /upload)。")
        lines = ["📊 大纲覆盖度(已掌握/总 · 平均掌握度)"]
        for c in cov:
            pct = round(c["mastered"] / c["total"] * 100) if c["total"] else 0
            lines.append(f"- {c['subject']}: {c['mastered']}/{c['total']}({pct}%),平均 {c['avg']}%")
        return _ok("\n".join(lines))

    def handle_merge_subject(self, args, session, executor):
        """合并科目别名:把 from 科目并入 to。"""
        frm = (args.get("from") or args.get("from_subject") or "").strip()
        to = (args.get("to") or args.get("to_subject") or "").strip()
        if not frm or not to:
            return _error("需要 from 和 to 两个科目名,如 from=高数 to=高等数学")
        n = learn_db.merge_subject(frm, to)
        return _ok(f"已把「{frm}」合并到「{to}」,影响 {n} 个知识点。")

    def handle_get_formula(self, args, session, executor):
        f_id = args.get("formula_id")
        if not f_id:
            return _error("formula_id 不能为空")
        fm = learn_db.get_formula(int(f_id))
        if not fm:
            return _error(f"公式 ID {f_id} 不存在")
        tags = json.loads(fm.get("usage_tags", "[]"))
        return _ok(
            f"**{fm['name']}** [{fm['id']}]\n\n"
            f"```\n{fm['plain_text'] or fm['latex']}\n```\n\n"
            f"- 科目: {fm['subject']}\n"
            f"- LaTeX: `{fm['latex']}`\n"
            f"- 来源: {fm['source_doc']} P{fm['source_page']}\n"
            f"- 重要度: {'⭐' * fm['importance']}\n"
            f"- 标签: {', '.join(tags)}\n"
            f"- 掌握度: {_mastery_bar(fm['mastery'])} {fm['mastery']:.0f}%\n"
            f"- 复习次数: {fm['review_count']} | 下次复习: {fm['next_review'] or '待定'}")

    def handle_review_formulas(self, args, session, executor):
        subject = (args.get("subject") or "").strip()
        count = min(args.get("count") or 5, 20)
        formulas = learn_db.get_due_formulas(subject, count)
        if not formulas:
            return _ok("🎉 没有待复习的公式！所有公式都在掌握中。")
        lines = [f"📐 今日待复习公式 ({len(formulas)} 个):\n"]
        for f in formulas:
            lines.append(
                f"**[{f['id']}] {f['name']}** — {f['plain_text'][:60]}\n"
                f"  掌握: {_mastery_bar(f['mastery'])} {f['mastery']:.0f}% | "
                f"来源: {f['source_doc']} P{f['source_page']}")
        lines.append("\n用 learn_generate_quiz formula_id=N 对这个公式出题练习。")
        return _ok("\n".join(lines))

    def handle_list_progress(self, args, session, executor):
        subject = (args.get("subject") or "").strip()
        days = min(args.get("days") or 30, 365)
        stats = learn_db.get_stats()
        summary = learn_db.get_progress_summary(days)
        weak = learn_db.get_weak_topics(subject, 5)

        total_min = sum(s["total_minutes"] for s in summary)
        total_ex = sum(s["total_ex"] for s in summary)
        accuracy = (sum(s["accuracy"] * s["total_ex"] for s in summary if s["total_ex"] > 0)
                    / max(1, sum(s["total_ex"] for s in summary)))

        lines = [
            "📊 学习进度概览",
            "---",
            f"**知识库**: {stats['total_knowledge_points']} 知识点, "
            f"{stats['total_formulas']} 公式, {stats['total_exercises']} 题目",
            f"**未复习错题**: {stats['unreviewed_mistakes']}",
            f"**未处理文档**: {stats['unprocessed_documents']}",
            "",
            f"**今日**: {stats['today_study_minutes']} 分钟, {stats['today_exercises']} 题",
            "",
            f"**近 {days} 天**: {total_min} 分钟, {total_ex} 题, 正确率 {accuracy:.1f}%",
        ]

        if weak:
            lines.append("")
            lines.append("**⚠️ 薄弱知识点 Top 5**:")
            for w in weak:
                m = w["mastery"]
                lines.append(f"  - [{w['id']}] {w['title']} ({w['subject']}) — "
                           f"掌握 {_mastery_bar(m)} {m:.0f}%, "
                           f"上次复习: {w['last_reviewed'] or '从未'}")

        return _ok("\n".join(lines))

    def handle_record_exercise(self, args, session, executor):
        ex_id = args.get("exercise_id")
        correct = args.get("correct", False)
        user_answer = str(args.get("user_answer", "")).strip()

        if not ex_id:
            return _error("exercise_id 不能为空")
        ex = learn_db.get_exercise(int(ex_id))
        if not ex:
            return _error(f"题目 ID {ex_id} 不存在")

        kp_id = ex.get("knowledge_point_id")
        fm_ids = json.loads(ex.get("formula_ids", "[]"))

        if correct:
            # 更新知识点和公式掌握度
            if kp_id:
                kp = learn_db.get_knowledge_point(kp_id)
                new_m = min(100, kp.get("mastery", 0) + 15)
                learn_db.update_kp_mastery(kp_id, new_m)
                # SM-2: 正确→拉长间隔
                learn_db.update_kp_next_review(kp_id, _sm2_next(
                    kp.get("review_count", 0), kp.get("mastery", 0) / 100, 1.0))
            for fid in fm_ids:
                fm = learn_db.get_formula(fid)
                if fm:
                    new_m = min(100, fm.get("mastery", 0) + 12)
                    learn_db.update_formula_mastery(fid, new_m)
                    learn_db.update_formula_next_review(fid, _sm2_next(
                        fm.get("review_count", 0), fm.get("mastery", 0) / 100, 1.0))
            learn_db.log_progress(
                subject=ex.get("subject", ""),
                exercises_done=1, exercises_correct=1)
            return _ok("✅ 正确！掌握度已更新。继续加油！")
        else:
            # 创建错题记录
            learn_db.add_mistake(
                exercise_id=int(ex_id), user_answer=user_answer,
                error_type="pending_analysis",
                knowledge_gap_id=kp_id)
            if kp_id:
                kp = learn_db.get_knowledge_point(kp_id)
                new_m = max(0, kp.get("mastery", 50) - 10)
                learn_db.update_kp_mastery(kp_id, new_m)
                learn_db.update_kp_next_review(kp_id, time.strftime("%Y-%m-%d"))  # 今天再复习
            learn_db.log_progress(
                subject=ex.get("subject", ""),
                exercises_done=1, exercises_correct=0,
                weak_topics=[kp_id] if kp_id else [])
            return _ok(
                f"❌ 已记录错题。正确答案: {ex.get('answer', '')[:200]}\n"
                f"建议用 learn_generate_quiz 再做几道同类题巩固。")

    def handle_generate_quiz(self, args, session, executor):
        formula_id = args.get("formula_id")
        kp_id = args.get("knowledge_point_id")
        subject = (args.get("subject") or "").strip()
        count = min(args.get("count") or 3, 10)
        difficulty = args.get("difficulty")  # None → 自适应

        # 【参数化题库加速】先尝试从模板生成（零延迟，不调 LLM）
        template_questions = []
        try:
            if kp_id:
                templates = learn_db.get_templates_for_kp(int(kp_id), limit=count)
            elif subject:
                templates = learn_db.get_templates_by_subject(subject, limit=count)
            else:
                templates = []
            for t in templates[:count]:
                q = learn_db.generate_from_template(t["id"])
                if q:
                    template_questions.append(q)
                    learn_db.mark_instance_used(q["id"])
        except Exception:
            pass

        if len(template_questions) >= count:
            # 全部从模板生成，零 LLM 调用
            out = "## 练习题\n\n"
            for i, q in enumerate(template_questions, 1):
                out += f"**第{i}题** (难度 {q['difficulty']}/6)\n{q['question_text']}\n\n"
            out += "\n---\n(题目由题库模板自动生成，答案已存储。做完后我可以帮你批改。)"
            return ToolResult(output=out)

        # 模板不够 → LLM 补充
        if not self.call_model:
            return _error("题目生成需要 LLM,但未注入 call_model")

        # 收集上下文
        context = ""
        if formula_id:
            fm = learn_db.get_formula(int(formula_id))
            if not fm:
                return _error(f"公式 ID {formula_id} 不存在")
            context = (f"公式: {fm['name']}\n表达式: {fm['plain_text']}\n"
                      f"知识点: {learn_db.get_knowledge_point(fm.get('knowledge_point_id') or 0).get('title','')}")
            if difficulty is None:
                difficulty = max(1, int(4 - fm["mastery"] / 30))  # 掌握度越低,难度越低
            subject = fm.get("subject", subject)
        elif kp_id:
            kp = learn_db.get_knowledge_point(int(kp_id))
            if not kp:
                return _error(f"知识点 ID {kp_id} 不存在")
            context = f"知识点: {kp['title']}\n内容: {kp.get('content','')[:500]}"
            if difficulty is None:
                difficulty = max(1, int(4 - kp["mastery"] / 30))
            subject = kp.get("subject", subject)
        elif subject:
            context = f"科目: {subject}"
        else:
            return _error("至少指定 formula_id / knowledge_point_id / subject 之一")

        # 获取近期题目避免重复
        recent = learn_db.get_recent_exercises(limit=10)
        avoid = "\n".join(f"- {r['question'][:80]}" for r in recent) if recent else "无"

        prompt = (
            f"你是{subject or '学科'}辅导老师。根据以下上下文生成 {count} 道练习题。\n\n"
            f"{context}\n\n"
            f"难度: {difficulty}/4 (1基础定义 2理解应用 3综合 4考试级)\n"
            f"每个知识点或公式可以生成多道变式题\n\n"
            f"最近做过的题目(避免重复):\n{avoid}\n\n"
            "输出 JSON 数组(不要 markdown 代码块):\n"
            '[\n'
            '  {"question": "题目", "answer": "答案", "solution_steps": ["步骤1","步骤2"], "difficulty": 2, "bloom_level": 3}\n'
            ']\n\n'
            "要求: 题目清晰完整,答案正确,步骤详细。每题之间要有区分度。"
        )

        content = (self.call_model([{"role": "user", "content": prompt}],
                   None, False).get("content") or "").strip()

        # 解析 JSON
        try:
            from doc_engine import _extract_json as _ej
            questions = _ej(content)
            if isinstance(questions, dict):
                questions = questions.get("questions", [questions])
        except Exception:
            return _error(f"题目生成解析失败,LLM 回复: {content[:300]}")

        if not questions:
            return _error(f"题目生成失败,LLM 回复: {content[:500]}")

        # 入库并格式化
        lines = [f"📝 生成 {len(questions)} 道题:\n"]
        for i, q in enumerate(questions):
            q_text = q.get("question", q.get("q", ""))
            a_text = q.get("answer", q.get("a", ""))
            if not q_text:
                continue
            ex_id = learn_db.add_exercise(
                knowledge_point_id=int(kp_id) if kp_id else None,
                formula_ids=[int(formula_id)] if formula_id else [],
                question=q_text, answer=a_text,
                solution_steps=q.get("solution_steps", q.get("steps", [])),
                difficulty=q.get("difficulty", difficulty or 2),
                bloom_level=q.get("bloom_level", 3))
            lines.append(
                f"**[题目 {ex_id}]** {q_text[:200]}\n"
                f"  难度: {'⭐'*q.get('difficulty',2)} | Bloom: L{q.get('bloom_level',3)}\n"
                f"  答案: {a_text[:150]}")

        return _ok("\n".join(lines))

    def handle_search_formula(self, args, session, executor):
        subject = (args.get("subject") or "").strip()
        keyword = (args.get("keyword") or "").strip()
        limit = min(args.get("limit") or 15, 50)
        results = learn_db.search_formulas(subject, keyword, limit)
        if not results:
            return _ok("未找到匹配的公式。用 learn_upload_doc 上传课本后自动提取。")
        lines = ["📐 公式搜索结果:\n"]
        for f in results:
            lines.append(
                f"**[{f['id']}] {f['name']}** — {f['plain_text'][:50]}\n"
                f"  {f['subject']} | {_mastery_bar(f['mastery'])} {f['mastery']:.0f}% | "
                f"来源: {f['source_doc']} P{f['source_page']}")
        return _ok("\n".join(lines))

    def handle_add_exam(self, args, session, executor):
        """注册考试。"""
        import study_planner
        name = str(args.get("name", "")).strip()
        exam_date = str(args.get("exam_date", "")).strip()
        subjects_str = str(args.get("subjects", "")).strip()
        scope = str(args.get("scope", "")).strip()
        target_score = str(args.get("target_score", "")).strip()

        if not name or not exam_date:
            return _error("name 和 exam_date 不能为空")
        try:
            date.fromisoformat(exam_date)
        except ValueError:
            return _error("exam_date 格式错误,请用 YYYY-MM-DD")

        subjects = [s.strip() for s in subjects_str.split(",") if s.strip()]
        days_left = (date.fromisoformat(exam_date) - date.today()).days

        mgr = study_planner.get_exam_manager()
        exam_id = mgr.add_exam(name, exam_date, subjects, scope, target_score)
        return _ok(
            f"✅ 已注册考试: **{name}**\n\n"
            f"- 日期: {exam_date} (倒计时 **{days_left}** 天)\n"
            f"- 科目: {', '.join(subjects) if subjects else '未指定'}\n"
            f"- 目标: {target_score or '未设定'}\n\n"
            f"下一步:\n"
            f"- learn_analyze_syllabus {exam_id} — 分析考纲缺口\n"
            f"- learn_generate_study_plan {exam_id} — 生成备考计划\n"
            f"- learn_exam_dashboard — 查看考试仪表盘")

    def handle_exam_dashboard(self, args, session, executor):
        """考试仪表盘。"""
        import study_planner
        mgr = study_planner.get_exam_manager()
        d = mgr.get_dashboard()
        if not d["exams"]:
            return _ok(
                "📋 暂无 upcoming 考试。\n\n"
                "用 learn_add_exam 注册考试,系统会自动:\n"
                "- 分析考纲 vs 知识库缺口\n"
                "- 生成倒计时备考计划\n"
                "- 追踪每科准备进度")
        lines = [f"📋 考试仪表盘 ({d['total']} 场, {d['urgent_count']} 场紧急)\n"]
        lines.append("| # | 考试 | 日期 | 倒计时 | 紧急度 | 覆盖度 |")
        lines.append("|---|------|------|--------|--------|--------|")
        for e in d["exams"]:
            lines.append(
                f"| {e['id']} | {e['name'][:15]} | {e['date']} "
                f"| {e['days_left']}天 | {e['urgency']} "
                f"| {e['topics_covered']}/{e['topics_total']} ({e['coverage']}%) |")
        if d["urgent_count"]:
            lines.append(f"\n🔴 {d['urgent_count']} 场考试在 7 天内,建议立即生成备考计划!")
        return _ok("\n".join(lines))

    def handle_exam_detail(self, args, session, executor):
        """考试详情。"""
        import study_planner
        exam_id = args.get("exam_id")
        if not exam_id:
            return _error("exam_id 不能为空")
        mgr = study_planner.get_exam_manager()
        detail = mgr.get_exam_detail(int(exam_id))
        if "error" in detail:
            return _error(detail["error"])

        lines = [
            f"📋 **{detail['name']}**",
            "---",
            f"📅 {detail['date']} | ⏰ 倒计时 **{detail['days_left']}** 天",
            f"🎯 目标: {detail['target_score'] or '未设定'}",
            f"📊 考纲覆盖: {detail['coverage']['covered']}/{detail['coverage']['total_topics']} "
            f"({detail['coverage']['coverage_pct']}%)",
        ]

        if detail.get("subject_progress"):
            lines.append("\n**各科准备度**:")
            for subj, prog in detail["subject_progress"].items():
                bar = _mastery_bar(prog["avg_mastery"])
                lines.append(f"  {subj}: {bar} {prog['avg_mastery']}% "
                           f"({prog['kps']} 知识点, {prog['weak_count']} 薄弱)")

        rec = detail.get("daily_recommendation", {})
        if rec.get("topics_per_day", 0) > 0:
            lines.append(f"\n**每日建议**: {rec['topics_per_day']} 知识点 + "
                        f"{rec['exercises_per_day']} 题")
            lines.append(f"剩余缺口: {rec['total_gaps']} 个")

        if detail.get("uncovered_gaps"):
            lines.append("\n**⚠️ 未覆盖的缺口**:")
            for g in detail["uncovered_gaps"][:8]:
                lines.append(f"  - {g.get('topic','')} ({g.get('subject','')}) "
                           f"优先级: {'⭐'*g.get('priority',1)}")

        lines.append(f"\n用 learn_generate_study_plan exam_id={exam_id} 生成备考计划")
        return _ok("\n".join(lines))

    def handle_generate_study_plan(self, args, session, executor):
        """生成自适应备考计划。"""
        import study_planner
        exam_id = args.get("exam_id")
        minutes = min(args.get("minutes_per_day") or 60, 480)
        planner = study_planner.get_planner(self.call_model)
        plan = planner.generate(
            exam_id=int(exam_id) if exam_id else None,
            minutes_per_day=minutes)

        if "error" in plan:
            return _error(plan["error"])

        tasks = plan.get("tasks", [])
        lines = [
            f"📅 **{plan['name']}**",
            "---",
            f"📆 {plan['total_days']} 天 | 📅 截止 {plan['exam_date']}",
            f"📚 {plan['topics_count']} 个知识点待学",
            f"🎯 {plan['focus']}",
            f"💡 {plan.get('strategy','')}",
            "",
            "**前 15 天任务预览**:",
            "| 天 | 任务 | 类型 | 时长 |",
            "|----|------|------|------|",
        ]
        for t in tasks[:15]:
            lines.append(f"| {t.get('day','')} | {t.get('task','')[:30]} "
                        f"| {t.get('type','')} | {t.get('duration','')}分钟 |")

        breakdown = plan.get("daily_breakdown", {})
        if breakdown:
            avg = sum(breakdown.values()) // max(1, len(breakdown))
            lines.append(f"\n⏰ 日均学习: ~{avg} 分钟")

        lines.append(f"\n计划 ID: {plan['plan_id']} | 查看: learn_list_progress")
        return _ok("\n".join(lines))

    def handle_analyze_syllabus(self, args, session, executor):
        """考纲缺口分析。"""
        import study_planner
        exam_id = args.get("exam_id")
        if not exam_id:
            return _error("exam_id 不能为空")
        analyzer = study_planner.get_syllabus_analyzer(self.call_model)
        result = analyzer.analyze(int(exam_id))
        if "error" in result:
            return _error(result["error"])

        lines = [
            f"🔍 考纲分析: {result.get('analysis','')}",
            "",
            f"**新增缺口**: {result.get('gaps_added',0)} 个",
            "",
            "**待补充的知识点**:",
        ]
        for g in result.get("gaps", [])[:10]:
            lines.append(f"  - [{g.get('subject','')}] {g.get('topic','')} "
                        f"({'⭐'*g.get('priority',1)} {g.get('reason','')})")

        if result.get("strengths"):
            lines.append(f"\n**✅ 已有优势**: {', '.join(result['strengths'][:5])}")

        lines.append(f"\n💡 {result.get('recommendation','')}")
        lines.append(f"\n下一步: learn_generate_study_plan exam_id={exam_id}")
        return _ok("\n".join(lines))

    def handle_study_advice(self, args, session, executor):
        """AI 学习建议。"""
        import study_planner
        advisor = study_planner.get_advisor(self.call_model)
        result = advisor.advise()
        return _ok(result)

    def handle_daily_review(self, args, session, executor):
        """生成今日学习复盘,并带上到期待复习的知识点/公式。"""
        import reviewer
        head = []
        try:
            due_kp = learn_db.get_due_knowledge_points(limit=10)
            if due_kp:
                head.append("📌 到期待复习知识点: " +
                            "、".join(f"[{k['id']}]{k['title']}" for k in due_kp))
        except Exception:
            pass
        try:
            due_fm = learn_db.get_due_formulas(limit=10)
            if due_fm:
                head.append("📐 到期公式: " + "、".join(k["name"] for k in due_fm))
        except Exception:
            pass
        r = reviewer.get_reviewer(self.call_model)
        result = r.review()
        pre = ("\n".join(head) + "\n\n") if head else ""
        return _ok(pre + result)

    def handle_plan_tomorrow(self, args, session, executor):
        """生成明日学习计划。"""
        import reviewer
        minutes = min(args.get("available_minutes") or 60, 480)
        pg = reviewer.get_plan_generator(self.call_model)
        plan = pg.generate_tomorrow_plan(minutes)
        tasks = plan.get("tasks", [])
        lines = [
            "📅 明日学习计划",
            "---",
            f"**重点**: {plan.get('focus','')}",
            f"**预计**: {minutes} 分钟",
            "",
            "| # | 任务 | 时长 | 类型 | 原因 |",
            "|---|------|------|------|------|"
        ]
        for i, t in enumerate(tasks, 1):
            lines.append(f"| {i} | {t.get('task','')} | {t.get('duration','')}分钟 "
                        f"| {t.get('type','')} | {t.get('reason','-')} |")
        lines.append("")
        lines.append(f"💡 {plan.get('tip','')}")
        return _ok("\n".join(lines))

    def handle_diagnose_mistake(self, args, session, executor):
        """诊断错题根因。"""
        import reviewer
        m_id = args.get("mistake_id")
        if not m_id:
            return _error("mistake_id 不能为空")
        d = reviewer.get_diagnoser(self.call_model)
        result = d.diagnose(int(m_id))
        if "error" in result:
            return _error(result["error"])
        return _ok(
            f"🔍 错题诊断 #{m_id}\n\n"
            f"**根因**: {result.get('root_cause','未知')}\n"
            f"**错误类型**: {result.get('gap_type','未知')}\n"
            f"**建议复习**: {', '.join(result.get('should_review',[]))}\n"
            f"**建议**: {result.get('advice','')}")

    def handle_auto_variant(self, args, session, executor):
        import efficiency_engine
        m_id = args.get("mistake_id")
        if not m_id:
            return _error("mistake_id 不能为空")
        av = efficiency_engine.AutoVariant(self.call_model)
        results = av.generate_for_mistake(int(m_id))
        if results and "error" in results[0]:
            return _error(results[0]["error"])
        lines = [f"🔄 为错题生成 {len(results)} 道变式题:\n"]
        for r in results:
            lines.append(f"  [{r['exercise_id']}] {r['question'][:80]}")
        lines.append("\n用 learn_record_exercise 记录结果")
        return _ok("\n".join(lines))

    def handle_achievements(self, args, session, executor):
        import efficiency_engine
        result = efficiency_engine.AchievementSystem.check_all()
        if not result["earned"]:
            return _ok(
                "🏆 还没有解锁成就。\n\n"
                "开始学习吧！完成第一次学习就能解锁'初次学习'徽章。"
                f"\n\n共 {result['total']} 个徽章等你发现。")
        lines = [f"🏆 成就 ({len(result['earned'])}/{result['total']}) — {result['progress_pct']}%\n"]
        lines.append("**已解锁**:")
        for a in result["earned"]:
            lines.append(f"  🏅 {a['name']} — {a['desc']}")
        if result["locked"]:
            lines.append("\n**下一个目标**:")
            for a in result["locked"][:3]:
                lines.append(f"  🔒 {a['name']} — {a['desc']}")
        return _ok("\n".join(lines))

    def handle_weekly_report(self, args, session, executor):
        import efficiency_engine
        report = efficiency_engine.WeeklyReport.generate(self.call_model)
        return _ok(report)

    def handle_smart_plan(self, args, session, executor):
        """AI智能日计划: 综合课表+进度+课本+学习计划。"""
        import schedule_engine
        minutes = min(args.get("available_minutes") or 60, 480)

        # 收集上下文
        tt = schedule_engine.get_timetable_engine()
        today_sched = tt.get_today_schedule()
        free_slots = tt.get_free_slots()
        homework = tt.get_homework(due_only=True)
        due_fm = learn_db.get_due_formulas(limit=8)
        weak_kps = learn_db.get_weak_topics(top_n=8)
        docs = learn_db.list_documents(parsed=True)
        stats = learn_db.get_stats()
        import learner_profile
        profile = learner_profile.load_profile()
        exams = learn_db.get_upcoming_exams(30)

        # 构建数据文本
        sched_text = "\n".join(
            f"- {s['start_time']}-{s['end_time']} {s['name']}" for s in today_sched) or "今天没有固定课程"
        free_text = "\n".join(
            f"- {f['start']}-{f['end']} ({f['duration_min']}分钟)" for f in free_slots[:5]) or "无空闲"
        hw_text = "\n".join(f"- {h['title']} (截止{h.get('due_date','?')})" for h in homework[:5]) or "无作业"
        weak_text = "\n".join(f"- [{w['id']}] {w['title']} 掌握{w['mastery']:.0f}%" for w in weak_kps[:6])
        fm_text = "\n".join(f"- {f['name']}: {f.get('plain_text','')[:50]}" for f in due_fm[:6])
        doc_text = "\n".join(
            f"- {d['filename']} ({d.get('subject','')}) {'已解析' if d.get('parsed') else '待解析'}"
            for d in docs[:5]) or "无"
        exam_text = "\n".join(f"- {e['name']} ({e['exam_date']})" for e in exams[:3]) or "无即将考试"
        goals = profile.get("goals", [])
        goal_text = ", ".join(goals) if goals else "未设定"

        prompt = (
            "你是学习规划专家。根据学生的全面数据,生成今天的学习清单。\n\n"
            f"## 今日课表\n{sched_text}\n\n"
            f"## 空闲时间\n{free_text}\n\n"
            f"## 待交作业\n{hw_text}\n\n"
            f"## 薄弱知识点\n{weak_text}\n\n"
            f"## 待复习公式\n{fm_text}\n\n"
            f"## 已有课本/资料\n{doc_text}\n\n"
            f"## 即将考试\n{exam_text}\n\n"
            f"## 学习目标\n{goal_text}\n\n"
            f"## 今日可用时间: {minutes}分钟\n"
            f"知识库总量: {stats['total_knowledge_points']}知识点, {stats['total_formulas']}公式, "
            f"{stats['total_exercises']}题 | 未复习错题: {stats['unreviewed_mistakes']}\n\n"
            "输出一份简洁的今日学习清单(适合手表屏幕):\n\n"
            "**📋 今日学习清单**\n\n"
            "**🔤 要复习的知识点**: (3-5个,按优先级)\n"
            "**📐 要过的公式**: (3-5个)\n"
            "**✏️ 建议练习题**: (数量和类型)\n"
            "**📖 建议阅读**: (课本/讲义的哪部分)\n"
            "**📝 要完成的作业**: (按截止日期)\n\n"
            "**⏰ 时间分配建议**: (怎么利用空闲时间)\n\n"
            "直接输出,不要 JSON,不要寒暄。控制在 2000 字以内。"
        )

        if not self.call_model:
            return _error("LLM 未配置")
        content = (self.call_model([{"role": "user", "content": prompt}],
                   None, False).get("content") or "").strip()
        return _ok(content or "生成失败")

    def handle_custom_quiz(self, args, session, executor):
        subject = str(args.get("subject", "")).strip()
        chapters = str(args.get("chapters", "")).strip()
        qtypes = str(args.get("question_types", "3道选择+2道大题")).strip()
        difficulty = args.get("difficulty")

        # 收集章节知识点
        if chapters:
            kps = learn_db.search_knowledge_points(subject=subject, keyword=chapters, limit=20)
        elif subject:
            kps = learn_db.search_knowledge_points(subject=subject, limit=20)
        else:
            kps = learn_db.get_weak_topics(top_n=15)

        if not kps:
            return _error("未找到匹配的知识点。请先上传教材或缩小范围。")

        kp_text = "\n".join(f"- {k['title']} (掌握{k['mastery']:.0f}%)" for k in kps[:10])
        formulas = learn_db.search_formulas(subject=subject, limit=10)
        fm_text = "\n".join(f"- {f['name']}: {f['plain_text'][:60]}" for f in formulas[:5])

        prompt = (
            f"你是出卷专家。根据以下内容生成一份试卷。\n\n"
            f"科目: {subject or '综合'}\n"
            f"范围: {chapters or '全部'}\n"
            f"题型分布: {qtypes}\n"
            f"难度: {difficulty or '自适应'}/4\n\n"
            f"知识点:\n{kp_text}\n\n"
            f"公式库:\n{fm_text}\n\n"
            "输出格式:\n"
            "**一、选择题** (每题4个选项)\n"
            "1. ...\n"
            "A. ... B. ... C. ... D. ...\n\n"
            "**二、填空题**\n"
            "...\n\n"
            "**三、解答题**\n"
            "...\n\n"
            "---\n**参考答案** (放在最后)\n"
            "...\n\n"
            "要求: 题目完整,选项合理,答案正确。"
        )

        if not self.call_model:
            return _error("LLM 未配置")
        content = (self.call_model([{"role": "user", "content": prompt}],
                   None, False).get("content") or "").strip()
        return _ok(content or "生成失败,请重试")

    def handle_export(self, args, session, executor):
        fmt = str(args.get("format", "all")).strip()
        subject = str(args.get("subject", "")).strip()

        lines = [f"# Nous 学习数据导出\n生成: {time.strftime('%Y-%m-%d %H:%M')}\n"]

        if fmt in ("all", "knowledge"):
            lines.append("## 知识点\n")
            kps = learn_db.search_knowledge_points(subject=subject, limit=100)
            for k in kps:
                bar = _mastery_bar(k["mastery"])
                lines.append(f"- {bar} [{k['id']}] {k.get('chapter','')}/{k['title']} "
                           f"({k.get('subject','')}) {k['mastery']:.0f}%")
            lines.append(f"\n共 {len(kps)} 个知识点\n")

        if fmt in ("all", "formulas"):
            lines.append("## 公式表\n")
            fms = learn_db.search_formulas(subject=subject, limit=100)
            lines.append("| 公式 | 表达式 | 掌握度 | 来源 |")
            lines.append("|------|--------|--------|------|")
            for f in fms:
                lines.append(f"| {f['name']} | {f.get('plain_text','')[:50]} "
                           f"| {f['mastery']:.0f}% | {f.get('source_doc','')} P{f.get('source_page',0)} |")
            lines.append(f"\n共 {len(fms)} 个公式\n")

        if fmt in ("all", "mistakes"):
            lines.append("## 错题集\n")
            mistakes = learn_db.get_mistakes(subject=subject, reviewed=None, limit=50)
            for m in mistakes:
                lines.append(f"- [{m.get('created_at','')[:10]}] {m.get('question','')[:80]}")
                if m.get("answer"):
                    lines.append(f"  答案: {m['answer'][:80]}")

        lines.append("\n---\n导出工具: learn_export")

        # 存为文件
        export_dir = os.path.join(doc_engine.DOCS_DIR, "exports")
        os.makedirs(export_dir, exist_ok=True)
        fname = f"nous_export_{time.strftime('%Y%m%d_%H%M')}.md"
        fpath = os.path.join(export_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        result = "\n".join(lines[:100])  # 返回前100行预览
        if len(lines) > 100:
            result += f"\n\n... (完整文件: {fpath})"
        return _ok(result)

    def handle_focus_history(self, args, session, executor):
        days = int(args.get("days", 30))
        import learn_db
        history = learn_db.get_focus_history(days)
        stats = learn_db.get_focus_stats()
        if not history:
            return _ok("还没有专注学习记录。用 learn_focus_start 开始第一次番茄钟吧！")
        lines = [
            f"🍅 专注历史 ({stats['total_sessions']}次, 共{stats['total_hours']}小时)",
            f"今日: {stats['today_minutes']}分钟\n",
            "最近记录:"
        ]
        for h in history[:10]:
            d = h.get("d", "")
            subj = h.get("subject", "")
            dur = h.get("duration_seconds", 0)
            lines.append(f"  {d} | {subj or '学习'} | {dur//60}分钟")
        return _ok("\n".join(lines))

    def handle_my_notes(self, args, session, executor):
        import learn_db
        keyword = str(args.get("keyword", "")).strip()
        if keyword:
            notes = learn_db.search_quick_notes(keyword, 20)
        else:
            notes = learn_db.get_quick_notes(20)
        if not notes:
            return _ok("还没有笔记。用 learn_quick_note 记一条吧！")
        lines = [f"📝 笔记 ({len(notes)} 条)\n"]
        for n in notes[:15]:
            lines.append(f"  [{n['id']}] {n['created_at'][:10]} {n['content'][:100]}")
        return _ok("\n".join(lines))

    def handle_focus_start(self, args, session, executor):
        import efficiency_engine
        subject = str(args.get("subject", "")).strip()
        task = str(args.get("task", "")).strip()
        duration = int(args.get("duration_min", 25))
        session_info = efficiency_engine.FocusMode.start_session(subject, task, duration)
        method = efficiency_engine.recommend_method(subject, 0, is_new=False)
        return _ok(
            f"🍅 专注模式 · {session_info['duration']}分钟\n\n"
            f"任务: {task or '自由学习'}\n"
            f"科目: {subject or '不限'}\n\n"
            f"{session_info['tip']}\n\n"
            f"{method}")

    def handle_quick_note(self, args, session, executor):
        import efficiency_engine
        text = str(args.get("text", "")).strip()
        subject = str(args.get("subject", "")).strip()
        if not text:
            return _error("text 不能为空")
        result = efficiency_engine.QuickCapture.capture(text, subject)
        if "error" in result:
            return _error(result["error"])
        return _ok(f"{result['suggestion']}\n分类: {result['type']} | 科目: {result['subject']}")

    def handle_weak_alert(self, args, session, executor):
        import efficiency_engine
        result = efficiency_engine.WeakPointMonitor.check()
        if not result["alerts"]:
            return _ok("🎉 没有需要预警的弱项！继续保持！")
        lines = ["⚠️ 弱项预警\n"]
        for i, a in enumerate(result["alerts"][:6], 1):
            stale = f" {a['days_since_review']}天未复习" if a['days_since_review'] > 3 else ""
            lines.append(
                f"{i}. [{a['kp_id']}] {a['title']} ({a.get('subject','')}) "
                f"掌握 {a['mastery']:.0f}%{stale}")
            lines.append(f"   {a['suggestion']}")
        if result["sprint_alert"]:
            lines.append(f"\n{result['sprint_alert']}")
        lines.append(f"\n共 {result['critical_count']} 项, learn_auto_schedule 帮你安排复习")
        return _ok("\n".join(lines))

    def handle_sprint_mode(self, args, session, executor):
        import efficiency_engine
        exam_id = args.get("exam_id")
        result = efficiency_engine.SprintMode.activate(
            int(exam_id) if exam_id else None)
        if "error" in result:
            return _error(result["error"])
        s = result["strategy"]
        lines = [
            f"🔥 **{result['exam']}** · 倒计时 {result['days_left']} 天",
            "",
            f"弱项: {result['weak_count']} | 错题: {result['mistake_count']}",
            "",
            f"**Phase 1** ({s['phase1']['days']}天): {s['phase1']['focus']}",
            f"  {s['phase1']['daily']}",
            "",
            f"**Phase 2** ({s['phase2']['days']}天): {s['phase2']['focus']}",
            f"  {s['phase2']['daily']}",
            "",
            f"**Phase 3** ({s['phase3']['days']}天): {s['phase3']['focus']}",
            f"  {s['phase3']['daily']}",
            "",
            "**今日**:",
        ]
        for t in result["urgent_tasks"]:
            lines.append(f"  • {t}")
        lines.append(f"\n{result['motivation']}")
        return _ok("\n".join(lines))

    def handle_micro_learning(self, args, session, executor):
        import efficiency_engine
        subject = str(args.get("subject", "")).strip()
        snippets = efficiency_engine.MicroLearning.generate(subject, 4)
        tip = efficiency_engine.MicroLearning.daily_tip()
        lines = ["⚡ 微学习 (5分钟碎片)\n"]
        for s in snippets:
            lines.append(f"  {s['duration']} | {s['content']}")
        lines.append(f"\n{tip}")
        return _ok("\n".join(lines))

    def handle_add_timetable(self, args, session, executor):
        import schedule_engine
        text = str(args.get("text", "")).strip()
        if not text:
            return _error("text 不能为空")
        tt = schedule_engine.get_timetable_engine()
        parsed = tt.parse_natural(text)
        slot_id = tt.add_slot(**parsed)
        wd_names = ["周一","周二","周三","周四","周五","周六","周日"]
        wd = wd_names[parsed["weekday"]]
        return _ok(
            f"✅ 已添加到课表:\n"
            f"  {wd} {parsed['start_time']}-{parsed['end_time']} "
            f"{parsed['name']} ({parsed['category']})\n"
            f"  {parsed.get('location','')}\n\n"
            f"查看完整课表: learn_my_schedule scope=week\n"
            f"查看空闲时间: learn_free_time")

    def handle_my_schedule(self, args, session, executor):
        import schedule_engine
        scope = str(args.get("scope", "today")).strip()
        tt = schedule_engine.get_timetable_engine()
        wd_names = ["周一","周二","周三","周四","周五","周六","周日"]

        if scope == "week":
            week = tt.get_week_schedule()
            lines = ["📅 本周课表:\n"]
            for wd in range(7):
                slots = week.get(wd, [])
                day_name = wd_names[wd]
                if slots:
                    for s in slots:
                        lines.append(
                            f"  {day_name} {s['start_time']}-{s['end_time']} "
                            f"{s['name']} {s.get('location','')}")
                else:
                    lines.append(f"  {day_name} (空闲)")
            return _ok("\n".join(lines))
        else:
            today = tt.get_today_schedule()
            today_wd = date.today().weekday()
            lines = [f"📅 今日课表 ({wd_names[today_wd]})\n"]
            if not today:
                lines.append("今天没有固定课程安排。")
                free = tt.get_free_slots()
                if free:
                    total = sum(f["duration_min"] for f in free)
                    lines.append(f"空闲时间: {len(free)} 段,共 {total} 分钟")
                    for f in free:
                        lines.append(f"  {f['start']}-{f['end']} ({f['duration_min']}分钟)")
            else:
                for s in today:
                    lines.append(
                        f"  {s['start_time']}-{s['end_time']} {s['name']} "
                        f"{s.get('location','')}")
                free = tt.get_free_slots()
                if free:
                    total = sum(f["duration_min"] for f in free)
                    lines.append(f"\n空闲: {total} 分钟可学习")
            lines.append("\n自动排课: learn_auto_schedule")
            return _ok("\n".join(lines))

    def handle_free_time(self, args, session, executor):
        import schedule_engine
        tt = schedule_engine.get_timetable_engine()
        free = tt.get_free_slots()
        if not free:
            return _ok("今天没有空闲时间段。用 learn_my_schedule 查看课表。")
        total = sum(f["duration_min"] for f in free)
        lines = [f"⏰ 今日空闲时间 ({total} 分钟)\n"]
        for f in free:
            bar = "▓" * min(20, f["duration_min"] // 5)
            lines.append(f"  {f['start']}-{f['end']} {bar} {f['duration_min']}分钟")
        lines.append("\n自动安排学习: learn_auto_schedule")
        return _ok("\n".join(lines))

    def handle_auto_schedule(self, args, session, executor):
        import schedule_engine
        tt = schedule_engine.get_timetable_engine()
        tasks = tt.auto_schedule_study()
        if not tasks:
            return _ok("今天没有空闲时间可安排。")
        lines = [f"📋 已自动安排 {len(tasks)} 个学习任务:\n"]
        for t in tasks:
            method_str = ""
            if t.get("method"):
                methods = [schedule_engine.LEARNING_METHODS[m]["name"]
                          for m in t["method"] if m in schedule_engine.LEARNING_METHODS]
                if methods:
                    method_str = f" [{' + '.join(methods)}]"
            lines.append(
                f"  {t['time']} | {t['task']} | {t['duration']}分钟{method_str}")
        return _ok("\n".join(lines))

    def handle_add_homework(self, args, session, executor):
        import schedule_engine
        title = str(args.get("title", "")).strip()
        subject = str(args.get("subject", "")).strip()
        due_date = str(args.get("due_date", "")).strip()
        minutes = int(args.get("estimated_minutes", 30))
        if not title:
            return _error("title 不能为空")
        if not due_date:
            due_date = (date.today() + timedelta(days=1)).isoformat()
        tt = schedule_engine.get_timetable_engine()
        hw_id = tt.add_homework(title, subject, due_date, minutes)
        return _ok(
            f"📝 已添加作业: **{title}**\n"
            f"  科目: {subject or '未指定'} | 截止: {due_date} | 预计: {minutes}分钟\n"
            f"  查看: learn_my_homework")

    def handle_my_homework(self, args, session, executor):
        import schedule_engine
        tt = schedule_engine.get_timetable_engine()
        hw_list = tt.get_homework()
        if not hw_list:
            return _ok("📝 没有作业。很好！")
        pending = [h for h in hw_list if not h["completed"]]
        done = [h for h in hw_list if h["completed"]]
        lines = [f"📝 作业 ({len(pending)} 待完成, {len(done)} 已完成)\n"]
        if pending:
            lines.append("**待完成**:")
            for h in pending[:10]:
                due = h.get("due_date", "")
                days = ""
                if due:
                    d = (date.fromisoformat(due) - date.today()).days
                    days = f" ⏰{d}天" if d >= 0 else " 🔴过期"
                lines.append(f"  [{h['id']}] {h['title']} "
                           f"({h.get('subject','')}) "
                           f"{h.get('estimated_minutes',30)}分钟{days}")
        return _ok("\n".join(lines))

    def handle_my_profile(self, args, session, executor):
        import learner_profile
        action = str(args.get("action", "view")).strip()
        if action == "edit":
            field = str(args.get("field", "")).strip()
            value = str(args.get("value", "")).strip()
            if not field:
                return _error("field 不能为空")
            learner_profile.update_profile(**{field: value})
            learner_profile.add_memory("preference",
                f"用户修改了 {field}: {value}", importance=2)
            return _ok(f"✅ 已更新 {field}")
        # view
        profile = learner_profile.load_profile()
        lines = ["🧑 学习者画像\n"]
        if profile.get("name"):
            lines.append(f"姓名: {profile['name']}")
        lines.append(f"阶段: {profile['level']}")
        goals = profile.get("goals", [])
        if goals:
            lines.append(f"目标: {', '.join(goals)}")
        if profile.get("strong_subjects"):
            lines.append(f"擅长: {', '.join(profile['strong_subjects'])}")
        if profile.get("weak_subjects"):
            lines.append(f"薄弱: {', '.join(profile['weak_subjects'])}")
        style = profile.get("style", {})
        pace = style.get("pace", "normal")
        lines.append(f"节奏: {pace} | 偏好语音: {'是' if style.get('prefers_voice') else '否'} "
                    f"| 偏好简短: {'是' if style.get('prefers_quick') else '否'}")
        cur = profile.get("current", {})
        if cur.get("last_studied"):
            lines.append(f"上次学习: {cur['last_studied']} ({cur.get('last_subject','')})")
        beh = profile.get("behavior", {})
        if beh.get("consecutive_days", 0) > 0:
            lines.append(f"连续学习: {beh['consecutive_days']} 天")
        memories = learner_profile.get_recent_memories(14, 5)
        if memories:
            lines.append("\n近期记忆:")
            for m in memories:
                lines.append(f"  • {m['content'][:80]}")
        lines.append("\n编辑: learn_my_profile action=edit field=goals value='你的目标'")
        return _ok("\n".join(lines))

    def handle_remember(self, args, session, executor):
        import learner_profile
        content = str(args.get("content", "")).strip()
        category = str(args.get("category", "goal")).strip()
        if not content:
            return _error("content 不能为空")
        learner_profile.add_memory(category, content, importance=3)
        return _ok(f"🧠 已记住: {content[:100]}")

    def handle_list_courses(self, args, session, executor):
        import course_engine
        ce = course_engine.get_course_engine()
        courses = ce.list_courses()
        if not courses:
            return _ok(
                "📚 还没有课程。\n\n"
                "上传教材后用 learn_build_course 自动构建课程树。\n"
                "或者用 learn_add_exam 注册考试,系统会生成备考课程。")
        lines = ["📚 我的课程:\n"]
        lines.append("| ID | 课程 | 章节 | 知识点 | 完成度 |")
        lines.append("|----|------|------|--------|--------|")
        for c in courses:
            bar = _mastery_bar(c.get("progress_pct", 0))
            lines.append(f"| {c['id']} | {c['name'][:15]} | {c.get('total_chapters',0)} "
                        f"| {c['completed_kps']}/{c['total_kps']} "
                        f"| {bar} {c.get('progress_pct',0)}% |")
        lines.append("\n查看详情: learn_course_detail course_id=N")
        return _ok("\n".join(lines))

    def handle_course_detail(self, args, session, executor):
        import course_engine
        course_id = args.get("course_id")
        if not course_id:
            return _error("course_id 不能为空")
        ce = course_engine.get_course_engine()
        tree = ce.get_course_tree(int(course_id))
        if not tree:
            return _error(f"课程 {course_id} 不存在")
        lines = [f"📚 {tree['name']} ({tree.get('subject','')})\n"]
        for i, ch in enumerate(tree.get("chapters", []), 1):
            bar = _mastery_bar(100 * ch["completed_count"] / max(1, ch["kp_count"]))
            status = "✅" if ch["status"] == "done" else "📖" if ch["status"] == "in_progress" else "⬜"
            lines.append(f"  {status} 第{i}章 {ch['title']} "
                        f"{bar} {ch['completed_count']}/{ch['kp_count']} "
                        f"({ch.get('estimated_hours',1)}h)")
        lines.append(f"\n总进度: {tree.get('progress_pct',0)}%")
        lines.append(f"下一步: learn_next_to_learn course_id={course_id}")
        return _ok("\n".join(lines))

    def handle_next_to_learn(self, args, session, executor):
        import course_engine
        course_id = args.get("course_id")
        if not course_id:
            return _error("course_id 不能为空")
        ce = course_engine.get_course_engine()
        next_up = ce.get_next_to_learn(int(course_id))
        lines = [f"📍 {next_up.get('suggestion','')}"]
        ch = next_up.get("chapter", {})
        if ch:
            lines.append(f"章节: {ch.get('title','')}")
            lines.append(f"预计: {ch.get('estimated_hours',1)} 小时")
        weak = next_up.get("weak_kps", [])
        if weak:
            lines.append("重点攻克:")
            for w in weak:
                lines.append(f"  • {w.get('title','')} (掌握 {w.get('mastery',0):.0f}%)")
        lines.append("\n要现在学习吗?说 '出几道题' 开始练习。")
        return _ok("\n".join(lines))

    def handle_build_course(self, args, session, executor):
        import course_engine
        subject = str(args.get("subject", "")).strip()
        course_name = str(args.get("course_name", "")).strip()
        if not subject:
            return _error("subject 不能为空")
        ce = course_engine.get_course_engine()
        result = ce.build_from_knowledge_base(subject, course_name, self.call_model)
        if "error" in result:
            return _error(result["error"])
        return _ok(
            f"✅ 课程已构建: **{result['course_name']}**\n"
            f"- 课程 ID: {result['course_id']}\n"
            f"- 章节: {result['chapters_count']}\n"
            f"- 知识点: {result['total_kps']}\n\n"
            f"用 learn_course_detail {result['course_id']} 查看课程树。")

    def handle_flashcard_generate(self, args, session, executor):
        import course_engine
        kp_id = args.get("kp_id")
        subject = str(args.get("subject", "")).strip()
        count = min(args.get("count") or 10, 30)
        fe = course_engine.get_flashcard_engine(self.call_model)
        if kp_id:
            result = fe.generate_from_kp(int(kp_id), count)
        elif subject:
            result = fe.generate_from_subject(subject, count)
        else:
            return _error("至少指定 kp_id 或 subject")
        if result and "error" in result[0]:
            return _error(result[0]["error"])
        lines = [f"🃏 生成 {len(result)} 张闪卡:\n"]
        for c in result[:10]:
            lines.append(f"  [{c['id']}] Q: {c.get('front','')[:60]}")
        lines.append("\n用 learn_flashcard_review 开始复习。")
        return _ok("\n".join(lines))

    def handle_flashcard_review(self, args, session, executor):
        import course_engine
        deck = str(args.get("deck", "")).strip()
        count = min(args.get("count") or 10, 30)
        fe = course_engine.get_flashcard_engine()
        cards = fe.get_due_cards(deck, count)
        stats = fe.get_stats(deck)
        if not cards:
            return _ok(f"🎉 没有待复习的闪卡！({stats['total_cards']} 张卡片,全部掌握)")
        lines = [f"🃏 闪卡复习 ({len(cards)}/{stats['total_cards']} 张待复习)\n"]
        for i, c in enumerate(cards[:10], 1):
            lines.append(f"**[{c['id']}]** Q: {c['front'][:80]}")
            lines.append(f"  A: {c['back'][:100]}")
            if c.get("hint"):
                lines.append(f"  💡 {c['hint']}")
            lines.append(f"  掌握 {c['mastery']:.0f}% | 复习 {c['repetitions']} 次")
            lines.append("")
        lines.append("评分: learn_flashcard_rate card_id=N quality=0-5")
        return _ok("\n".join(lines))

    def handle_flashcard_rate(self, args, session, executor):
        import course_engine
        card_id = args.get("card_id")
        quality = args.get("quality", 3)
        if not card_id:
            return _error("card_id 不能为空")
        fe = course_engine.get_flashcard_engine()
        fe.review_card(int(card_id), max(0, min(5, int(quality))))
        q_labels = {0: "完全忘了 😅", 1: "有点印象 🤔", 3: "勉强答对 👍",
                    4: "顺利答对 👏", 5: "秒答！⚡"}
        return _ok(f"已评分: {q_labels.get(quality, str(quality))}\n"
                   f"系统已自动调整下次复习时间。")

    def handle_fuzzy_search(self, args, session, executor):
        """模糊搜索 — 用户说的词不精确时找最接近匹配。"""
        keyword = str(args.get("keyword", "")).strip()
        if not keyword:
            return _error("keyword 不能为空")

        # 搜索知识库
        kps = learn_db.search_knowledge_points(keyword=keyword, limit=5)
        fms = learn_db.search_formulas(keyword=keyword, limit=5)

        # 如果精确匹配失败,用包含匹配
        if not kps and not fms:
            kps = learn_db.search_knowledge_points(limit=20)
            fms = learn_db.search_formulas(limit=20)
            # 简单相似度: 找包含任意单字的
            chars = set(keyword)
            kps = [k for k in kps if chars & set(k.get("title",""))][:3]
            fms = [f for f in fms if chars & set(f.get("name",""))][:3]

        lines = []
        if kps:
            lines.append("**可能的知识点**:")
            for k in kps:
                lines.append(f"  [{k['id']}] {k['title']} ({k.get('subject','')})")
        if fms:
            lines.append("**可能的公式**:")
            for f in fms:
                lines.append(f"  [{f['id']}] {f['name']} — {f.get('plain_text','')[:40]}")

        if not lines:
            return _ok(f"未找到与 '{keyword}' 相关的内容。试试换个说法,或用 learn_search_kp 搜索。")

        lines.append("\n如果上面没有你要的,试试说具体一点。")
        return _ok("\n".join(lines))

    def handle_quick_review(self, args, session, executor):
        """快速复习 — 5分钟速览今日最该复习的内容。"""
        subject = str(args.get("subject", "")).strip()
        count = min(args.get("count") or 5, 10)

        # 收集: 到期公式 + 薄弱知识点 + 未复习错题
        formulas = learn_db.get_due_formulas(subject, 3)
        weak_kps = learn_db.get_weak_topics(subject, 3)
        mistakes = learn_db.get_mistakes(reviewed=False, limit=3)

        lines = ["⚡ 快速复习 (5分钟)\n"]

        if formulas:
            lines.append("**📐 公式速览**:")
            for f in formulas:
                lines.append(f"  • {f['name']}: {f.get('plain_text','')[:60]}")
                lines.append(f"    掌握 {f['mastery']:.0f}% | 来源: {f.get('source_doc','')} P{f.get('source_page',0)}")
            lines.append("")

        if weak_kps:
            lines.append("**⚠️ 薄弱知识点**:")
            for w in weak_kps:
                lines.append(f"  • {w['title']} ({w.get('subject','')}) — 掌握 {w['mastery']:.0f}%")
            lines.append("")

        if mistakes:
            lines.append("**❌ 待复习错题**:")
            for m in mistakes:
                q = m.get("question", "")[:60]
                lines.append(f"  • {q}...")

        lines.append("\n💡 要练习吗?说 '出几道题' 即可。")

        # 记录复习分钟数
        learn_db.log_progress(subject=subject, study_minutes=5, formulas_reviewed=len(formulas))
        return _ok("\n".join(lines))

    def handle_study_streak(self, args, session, executor):
        """查看连续学习天数和统计数据。"""
        summary = learn_db.get_progress_summary(365)
        if not summary:
            return _ok("📊 还没有学习记录。开始你的第一次学习吧！")

        # 计算连续天数
        streak = 0
        today = date.today()
        for i in range(365):
            check_date = (today - timedelta(days=i)).isoformat()
            found = any(s["date"] == check_date and s["total_ex"] > 0 for s in summary)
            if found:
                streak += 1
            elif i > 0:  # 第一天允许中断(可能今天还没学)
                break

        # 总计
        total_min = sum(s["total_minutes"] for s in summary)
        total_ex = sum(s["total_ex"] for s in summary)
        total_days = len([s for s in summary if s["total_ex"] > 0])

        return _ok(
            f"🔥 学习统计\n\n"
            f"**连续学习**: {streak} 天\n"
            f"**累计**: {total_days} 天 | {total_min} 分钟 | {total_ex} 题\n"
            f"**日均**: ~{total_min // max(1, total_days)} 分钟\n\n"
            + ("🎉 太棒了！继续保持！" if streak >= 7
               else f"💪 再坚持 {7 - streak} 天就满一周了！" if streak >= 1
               else "🌱 今天就开始吧,哪怕只学5分钟！"))



# 模糊匹配工具(供 Brain 系统提示使用)


def find_closest_term(keyword: str, kp_limit=3, fm_limit=3) -> dict:
    """在知识库中找最接近 keyword 的匹配。用于纠正语音识别错误。"""
    kps = learn_db.search_knowledge_points(keyword=keyword, limit=kp_limit)
    fms = learn_db.search_formulas(keyword=keyword, limit=fm_limit)
    if not kps and not fms:
        # 模糊回退: 拆字匹配
        all_kps = learn_db.search_knowledge_points(limit=50)
        all_fms = learn_db.search_formulas(limit=50)
        chars = set(keyword)
        kps = sorted(
            [k for k in all_kps if chars & set(k.get("title", ""))],
            key=lambda k: len(chars & set(k.get("title", ""))), reverse=True)[:kp_limit]
        fms = sorted(
            [f for f in all_fms if chars & set(f.get("name", ""))],
            key=lambda f: len(chars & set(f.get("name", ""))), reverse=True)[:fm_limit]
    return {"knowledge_points": [dict(k) for k in kps], "formulas": [dict(f) for f in fms]}



# 辅助函数


def _ok(output: str):
    from tools import ToolResult
    return ToolResult(status="done", output=output)


def _error(msg: str):
    from tools import ToolResult
    return ToolResult(status="error", output=msg)


def _mastery_bar(m: float) -> str:
    """掌握度→进度条。"""
    if not m:
        return "░░░░░"
    bars = int(m / 20)
    return "█" * bars + "░" * (5 - bars)


def _sm2_next(review_count: int, mastery: float, difficulty: float) -> str:
    """
    SM-2 间隔复习算法。
    mastery: 本次正确率(0-1), difficulty: 固有难度(0-1)
    返回: "YYYY-MM-DD" 下次复习日期
    """
    if review_count == 0:
        interval = 1
    elif mastery > 0.9:
        interval = max(1, int((review_count + 1) * 2.5 * (1 - difficulty * 0.2)))
    elif mastery > 0.6:
        interval = max(1, int((review_count + 1) * 1.5))
    else:
        interval = 1  # 没掌握,明天重来
    from datetime import date, timedelta
    next_date = date.today() + timedelta(days=min(interval, 365))
    return next_date.strftime("%Y-%m-%d")
