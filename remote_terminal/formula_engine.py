# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — 公式引擎 + SM-2 调度 + 变式题生成。

核心功能:
  1. SM-2 间隔复习调度 — 决定哪天复习哪个公式
  2. 公式复习卡片 — 今日待复习列表
  3. 变式题生成器 — 从公式出发,生成不同难度和 Bloom 层次的题
  4. 认知状态追踪 — mastery 更新 + 遗忘曲线

设计原则:
  - LLM 调用通过回调注入,本模块不依赖 brain.py
  - 数据持久化依赖 learn_db
"""

import json
import logging
import time
from datetime import date, timedelta

import learn_db

log = logging.getLogger("formula_engine")



# SM-2 间隔复习算法


class SM2Scheduler:
    """
    SuperMemo SM-2 变体。

    参数:
      quality: 0-5 用户自评(或根据正确率换算)
      interval: 当前间隔天数
      repetitions: 已复习次数
      ease_factor: 难度因子(默认 2.5, 范围 1.3-2.5)

    输出: (new_interval, new_ef, next_review_date)
    """

    @staticmethod
    def schedule(quality: int, interval: int = 1, repetitions: int = 0,
                 ease_factor: float = 2.5) -> tuple:
        """
        quality: 0(完全忘) 1(记得一点) 2(犹豫答对) 3(勉强对) 4(顺利) 5(完美)
        返回: (new_interval, new_ef, next_date_str)
        """
        quality = max(0, min(5, quality))

        if quality >= 3:
            # 正确 → 扩大间隔
            if repetitions == 0:
                new_interval = 1
            elif repetitions == 1:
                new_interval = 6
            else:
                new_interval = int(round(interval * ease_factor))

            # 调整难度因子
            new_ef = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            new_ef = max(1.3, new_ef)
            new_reps = repetitions + 1
        else:
            # 错误 → 重置
            new_interval = 1
            new_reps = 0
            new_ef = max(1.3, ease_factor - 0.2)

        next_date = date.today() + timedelta(days=min(new_interval, 365))
        return new_interval, new_reps, new_ef, next_date.strftime("%Y-%m-%d")

    @staticmethod
    def mastery_to_quality(mastery_pct: float) -> int:
        """掌握度(0-100) → SM-2 quality(0-5)。"""
        if mastery_pct >= 95:
            return 5
        elif mastery_pct >= 85:
            return 4
        elif mastery_pct >= 70:
            return 3
        elif mastery_pct >= 50:
            return 2
        elif mastery_pct >= 30:
            return 1
        return 0



# 公式复习管理器


class FormulaReviewManager:
    """管理公式的复习调度和掌握度更新。"""

    def __init__(self):
        learn_db.init()
        self.scheduler = SM2Scheduler()

    def get_today_review(self, subject="", count=5, include_new=True) -> list:
        """
        获取今日待复习公式。

        优先级:
          1. 到期未复习的 (next_review <= today)
          2. 掌握度 < 30% 的困难公式
          3. 新学习的公式(learned_at = today,未复习过)

        返回: list of formula dicts + scheduled review info
        """
        due = learn_db.get_due_formulas(subject, count * 2)

        # 按 mastery 升序(最弱优先)
        due.sort(key=lambda x: x.get("mastery", 0))

        result = []
        seen = set()
        for f in due:
            if len(result) >= count:
                break
            fid = f["id"]
            if fid in seen:
                continue
            seen.add(fid)
            f["_review_type"] = "due"
            result.append(f)

        # 如果不够,补充新学的公式
        if include_new and len(result) < count:
            today = time.strftime("%Y-%m-%d")
            all_fm = learn_db.search_formulas(subject, "", count * 3)
            for f in all_fm:
                if len(result) >= count:
                    break
                if f["id"] in seen:
                    continue
                if f.get("learned_at", "") == today and f.get("review_count", 0) == 0:
                    seen.add(f["id"])
                    f["_review_type"] = "new"
                    result.append(f)

        return result[:count]

    def record_review(self, formula_id: int, quality: int,
                      formula_engine_call_model=None) -> dict:
        """
        记录一次公式复习结果。
        quality: 0-5 (SM-2 标准)

        更新: mastery, review_count, last_reviewed, next_review, ease_factor
        返回: {"new_mastery": N, "next_review": "YYYY-MM-DD"}
        """
        fm = learn_db.get_formula(formula_id)
        if not fm:
            return {"error": f"公式 ID {formula_id} 不存在"}

        interval = fm.get("review_count", 0)
        reps = fm.get("review_count", 0)

        new_interval, new_reps, new_ef, next_date = self.scheduler.schedule(
            quality, interval, reps)

        # 更新 mastery: quality 0-5 → 0-100
        old_m = fm.get("mastery", 0)
        if quality >= 4:
            new_m = min(100, old_m + 20)
        elif quality >= 3:
            new_m = min(100, old_m + 10)
        elif quality >= 2:
            new_m = old_m  # 保持不变
        else:
            new_m = max(0, old_m - 15)

        learn_db.update_formula_mastery(formula_id, new_m)
        learn_db.update_formula_next_review(formula_id, next_date)
        learn_db.log_progress(
            subject=fm.get("subject", ""),
            formulas_reviewed=1)

        return {
            "formula_id": formula_id,
            "name": fm["name"],
            "old_mastery": old_m,
            "new_mastery": new_m,
            "quality": quality,
            "next_review": next_date,
            "interval_days": new_interval,
        }

    def batch_review(self, results: list) -> list:
        """
        批量记录复习结果。
        results: [{"formula_id": N, "quality": 0-5}, ...]
        """
        return [self.record_review(r["formula_id"], r["quality"]) for r in results]



# 变式题生成引擎


class QuizGenerator:
    """
    从公式/知识点生成变式练习题。

    支持:
      - Bloom 认知层次 L1-L6
      - 难度自适应(根据当前 mastery)
      - 变式生成(同类型不同数据)
      - 避免近期重复
    """

    BLOOM_TEMPLATES = {
        1: "出一道记忆型题目，让学生回忆这个概念/公式的定义或表达式。",
        2: "出一道理解型题目，让学生用自己的话解释这个概念或判断对错。",
        3: "出一道应用型题目，给具体数值让学生用这个公式计算。",
        4: "出一道分析型题目，给一个稍微复杂的场景让学生拆解成步骤。",
        5: "出一道评价型题目，让学生比较两种方法的优缺点或选择最优方案。",
        6: "出一道创造型题目，让学生自己设计一个能用这个知识解决的问题。",
    }

    def __init__(self, call_model=None):
        self.call_model = call_model
        self.review_mgr = FormulaReviewManager()

    def generate_from_formula(self, formula_id: int, count=3,
                               difficulty=None, bloom_level=3,
                               model=None) -> list:
        """
        从一个公式生成变式题。

        流程:
          1. 获取公式详情
          2. 获取关联知识点
          3. 获取近期题目(避免重复)
          4. LLM 生成变式题
          5. 入库返回

        返回: list of exercise dicts with ids
        """
        fm = learn_db.get_formula(formula_id)
        if not fm:
            return [{"error": f"公式 ID {formula_id} 不存在"}]

        # 自适应难度
        mastery = fm.get("mastery", 0)
        if difficulty is None:
            difficulty = self._adaptive_difficulty(mastery, bloom_level)

        # 自适应 Bloom 层(掌握度越高,层次越深)
        if bloom_level == 3 and mastery > 70:
            bloom_level = min(6, 4 + int((mastery - 70) / 15))

        # 关联知识点
        kp_id = fm.get("knowledge_point_id")
        kp = learn_db.get_knowledge_point(kp_id) if kp_id else {}

        # 近期题目
        recent = learn_db.get_recent_exercises(limit=8)
        avoid = "\n".join(f"- {r['question'][:80]}" for r in recent) if recent else "无"

        bloom_desc = self.BLOOM_TEMPLATES.get(bloom_level, self.BLOOM_TEMPLATES[3])

        prompt = (
            f"你是{fm.get('subject','math')}题库专家。根据以下信息生成 {count} 道练习题。\n\n"
            f"**公式**: {fm['name']}\n"
            f"**表达式**: {fm['plain_text'] or fm['latex']}\n"
            f"**关联知识点**: {kp.get('title','')}\n"
            f"**难度**: {difficulty}/4  (1基础 2中等 3综合 4考试)\n"
            f"**题型**: {bloom_desc}\n\n"
            f"**最近做过的题(避免重复)**:\n{avoid}\n\n"
            "输出 JSON 数组(不要 markdown 代码块):\n"
            '[\n'
            '  {\n'
            '    "question": "题目(完整,清晰)",\n'
            '    "answer": "答案",\n'
            '    "solution_steps": ["步骤1: ...","步骤2: ...","步骤3: ..."],\n'
            '    "difficulty": 2,\n'
            '    "bloom_level": 3,\n'
            '    "hint": "提示(可选)"\n'
            '  }\n'
            ']\n\n'
            "要求:\n"
            "- 每题之间有明显区分(不同数据/不同场景)\n"
            "- 答案要完整正确,步骤详细\n"
            "- 第1题最简单(热身),难度递增"
        )

        if not self.call_model:
            return [{"error": "LLM 未配置,无法生成题目"}]

        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()

        questions = self._parse_json(content)
        if not questions:
            return [{"error": f"题目生成失败,LLM回复: {content[:300]}"}]

        # 入库
        result = []
        for q in questions:
            q_text = q.get("question", q.get("q", ""))
            if not q_text:
                continue
            ex_id = learn_db.add_exercise(
                knowledge_point_id=kp_id,
                formula_ids=[formula_id],
                question=q_text,
                answer=q.get("answer", q.get("a", "")),
                solution_steps=q.get("solution_steps", q.get("steps", [])),
                difficulty=q.get("difficulty", difficulty),
                bloom_level=q.get("bloom_level", bloom_level))
            result.append({
                "exercise_id": ex_id,
                "question": q_text,
                "answer": q.get("answer", "")[:200],
                "difficulty": q.get("difficulty", difficulty),
                "bloom_level": q.get("bloom_level", bloom_level),
                "hint": q.get("hint", ""),
            })

        return result

    def generate_from_knowledge_point(self, kp_id: int, count=3,
                                       difficulty=None, bloom_level=3,
                                       model=None) -> list:
        """从知识点生成题目(含关联公式)。"""
        kp = learn_db.get_knowledge_point(kp_id)
        if not kp:
            return [{"error": f"知识点 ID {kp_id} 不存在"}]

        # 找关联公式
        related_fms = learn_db.search_formulas(subject=kp.get("subject", ""), limit=10)
        related_fms = [f for f in related_fms
                       if f.get("knowledge_point_id") == kp_id]

        if difficulty is None:
            difficulty = self._adaptive_difficulty(kp.get("mastery", 0), bloom_level)

        recent = learn_db.get_recent_exercises(limit=8)
        avoid = "\n".join(f"- {r['question'][:80]}" for r in recent) if recent else "无"
        bloom_desc = self.BLOOM_TEMPLATES.get(bloom_level, self.BLOOM_TEMPLATES[3])

        formulas_text = ""
        if related_fms:
            formulas_text = "**相关公式**:\n" + "\n".join(
                f"- {f['name']}: {f['plain_text'][:80]}" for f in related_fms[:5])

        prompt = (
            f"你是{kp.get('subject','math')}题库专家。生成 {count} 道练习题。\n\n"
            f"**知识点**: {kp['title']}\n"
            f"**内容**: {kp.get('content','')[:500]}\n"
            f"{formulas_text}\n"
            f"**难度**: {difficulty}/4\n"
            f"**题型**: {bloom_desc}\n"
            f"**避免重复**:\n{avoid}\n\n"
            "输出 JSON 数组:\n"
            '[{"question":"...","answer":"...","solution_steps":["..."],"difficulty":2,"bloom_level":3}]\n'
            "要求: 题目间有区分度,答案完整,步骤详细。"
        )

        if not self.call_model:
            return [{"error": "LLM 未配置"}]

        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()

        questions = self._parse_json(content)
        if not questions:
            return [{"error": f"生成失败: {content[:300]}"}]

        result = []
        for q in questions:
            q_text = q.get("question", q.get("q", ""))
            if not q_text:
                continue
            fids = [f["id"] for f in related_fms[:3]]
            ex_id = learn_db.add_exercise(
                knowledge_point_id=kp_id, formula_ids=fids,
                question=q_text,
                answer=q.get("answer", q.get("a", "")),
                solution_steps=q.get("solution_steps", q.get("steps", [])),
                difficulty=q.get("difficulty", difficulty),
                bloom_level=q.get("bloom_level", bloom_level))
            result.append({
                "exercise_id": ex_id,
                "question": q_text,
                "answer": q.get("answer", "")[:200],
                "difficulty": q.get("difficulty", difficulty),
                "bloom_level": q.get("bloom_level", bloom_level),
            })

        return result

    def _adaptive_difficulty(self, mastery: float, bloom: int) -> int:
        """根据掌握度和 Bloom 层自适应难度。"""
        if mastery < 30:
            return max(1, bloom - 2)
        elif mastery < 60:
            return max(1, bloom - 1)
        elif mastery < 85:
            return min(4, bloom)
        else:
            return min(4, bloom + 1)

    @staticmethod
    def _parse_json(text: str) -> list:
        """从 LLM 回复中解析 JSON 数组。"""
        text = text.strip()
        if text.startswith("```"):
            for part in text.split("```"):
                part = part.strip()
                if part.startswith("[") or part.startswith("json"):
                    if part.startswith("json"):
                        part = part[4:]
                    try:
                        return json.loads(part)
                    except Exception:
                        pass
        try:
            return json.loads(text)
        except Exception:
            pass
        s = text.find("[")
        e = text.rfind("]")
        if s != -1 and e != -1:
            try:
                return json.loads(text[s:e + 1])
            except Exception:
                pass
        return []



# 便捷函数(供 learn_tools 直接调用)


_formula_review_mgr = None
_quiz_generator = None


def get_review_mgr():
    global _formula_review_mgr
    if not _formula_review_mgr:
        _formula_review_mgr = FormulaReviewManager()
    return _formula_review_mgr


def get_quiz_generator(call_model=None):
    global _quiz_generator
    if not _quiz_generator:
        _quiz_generator = QuizGenerator(call_model)
    return _quiz_generator
