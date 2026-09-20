# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — 课程体系 + 闪卡系统。

课程引擎:
  - 构建有序课程树(科目→章→节→知识点)
  - 追踪每章完成度
  - AI 自动推荐下一步学什么

闪卡引擎:
  - 从知识点自动生成 Anki 式卡片
  - 内建 SM-2 间隔复习
  - 支持自定义牌组
"""

import json
import logging

import learn_db

log = logging.getLogger("course_flashcard")



# 课程引擎


class CourseEngine:
    """课程树管理 + 进度追踪。"""

    def create_course(self, name, subject="", description="") -> int:
        return learn_db.add_course(name, subject, description)

    def add_chapter(self, course_id, title, sort_order=0,
                    description="", estimated_hours=1.0) -> int:
        cid = learn_db.add_chapter(course_id, title, sort_order,
                                    description, estimated_hours)
        learn_db.update_course_progress(course_id)
        return cid

    def get_course_tree(self, course_id: int) -> dict:
        """获取完整课程树（含每章进度）。"""
        course = learn_db.get_course(course_id)
        if not course:
            return {}
        chapters = learn_db.list_chapters(course_id)
        # 更新每章进度
        for ch in chapters:
            learn_db.update_chapter_progress(ch["id"])
        chapters = learn_db.list_chapters(course_id)  # 重新读
        course["chapters"] = chapters
        course["progress_pct"] = round(
            100 * course["completed_kps"] / max(1, course["total_kps"]), 1)
        return course

    def list_courses(self) -> list:
        courses = learn_db.list_courses()
        for c in courses:
            c["progress_pct"] = round(
                100 * c["completed_kps"] / max(1, c["total_kps"]), 1)
        return courses

    def get_next_to_learn(self, course_id: int) -> dict:
        """推荐下一个该学的章节（第一门未完成）。"""
        chapters = learn_db.list_chapters(course_id)
        for ch in chapters:
            learn_db.update_chapter_progress(ch["id"])
        chapters = learn_db.list_chapters(course_id)
        for ch in chapters:
            if ch["status"] != "done":
                # 找该章最弱的知识点
                weak = learn_db.search_knowledge_points(
                    keyword=ch["title"], limit=5)
                return {
                    "chapter": ch,
                    "suggestion": f"学习 {ch['title']}（预计 {ch['estimated_hours']} 小时）",
                    "weak_kps": [w for w in weak if w.get("mastery", 0) < 70][:3],
                }
        return {"suggestion": "🎉 全部完成！可以开始下一门课或复习弱项。"}

    def build_from_knowledge_base(self, subject="", course_name="",
                                   call_model=None, model=None) -> dict:
        """从已有知识库自动构建课程树（LLM 分类知识点）。"""
        kps = learn_db.search_knowledge_points(subject=subject, limit=200)
        if not kps:
            return {"error": f"知识库中没有 {subject or '任何'} 科目的知识点。请先上传教材。"}

        if not call_model:
            return {"error": "需要 LLM"}

        titles = "\n".join(f"- [{k['id']}] {k.get('chapter','')}/{k['title']} "
                          f"({k.get('subject','')}) 掌握{k['mastery']:.0f}%"
                          for k in kps[:50])

        prompt = (
            "你是课程设计师。将以下零散知识点组织成有序的课程结构。\n\n"
            f"知识点列表:\n{titles}\n\n"
            "输出 JSON:\n"
            '{\n'
            '  "course_name": "课程名",\n'
            '  "subject": "math",\n'
            '  "chapters": [\n'
            '    {"title": "章名","sort_order":1,"description":"本章内容概述","estimated_hours":2.0,\n'
            '     "kp_ids": [1,2,3]}\n'
            '  ]\n'
            '}\n\n'
            "规则: 5-10章,按学习顺序排列,每章关联已有知识点 ID。"
        )

        content = (call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        result = self._parse_json(content)
        if not result:
            return {"error": "课程构建失败"}

        name = course_name or result.get("course_name", f"{subject} 课程")
        cid = self.create_course(name, result.get("subject", subject),
                                  result.get("description", ""))

        for ch in result.get("chapters", []):
            self.add_chapter(cid, ch["title"], ch.get("sort_order", 0),
                             ch.get("description", ""),
                             ch.get("estimated_hours", 1.0))
        learn_db.update_course_progress(cid)
        course = self.get_course_tree(cid)
        return {
            "course_id": cid,
            "course_name": name,
            "chapters_count": len(course.get("chapters", [])),
            "total_kps": len(kps),
        }

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            for part in text.split("```"):
                part = part.strip()
                if part.startswith("{") or part.startswith("json"):
                    if part.startswith("json"): part = part[4:]
                    try: return json.loads(part)
                    except Exception: pass
        try: return json.loads(text)
        except Exception: pass
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1:
            try: return json.loads(text[s:e+1])
            except Exception: pass
        return {}



# 闪卡引擎


_FLASHCARD_GEN_PROMPT = (
    "你是闪卡生成专家。根据以下知识点/公式,生成 Anki 式闪卡。\n\n"
    "## 来源\n{source_text}\n\n"
    "## 要求\n"
    "每张卡片: 正面是问题/提示,背面是答案/解释。每张卡片一个知识点。\n\n"
    "输出 JSON 数组:\n"
    '[\n'
    '  {"front": "导数的定义是什么？","back": "...","hint": "极限","deck": "math"}\n'
    ']\n\n'
    "正面形式多样: 定义填空、判断对错、计算题、记忆题。背面要完整。"
)


class FlashcardEngine:
    """闪卡生成 + SM-2 复习调度。"""

    def __init__(self, call_model=None):
        self.call_model = call_model

    def generate_from_kp(self, kp_id: int, count=3, model=None) -> list:
        """从单个知识点生成闪卡。"""
        kp = learn_db.get_knowledge_point(kp_id)
        if not kp:
            return [{"error": f"知识点 {kp_id} 不存在"}]
        formulas = learn_db.search_formulas(
            subject=kp.get("subject", ""), limit=5)
        fm_text = "\n".join(
            f"- {f['name']}: {f['plain_text'][:80]}" for f in formulas
            if f.get("knowledge_point_id") == kp_id)[:3]

        source = (f"知识点: {kp['title']}\n内容: {kp.get('content','')[:500]}\n"
                  f"相关公式:\n{fm_text}")

        prompt = _FLASHCARD_GEN_PROMPT.format(source_text=source) + \
                 f"\n生成 {count} 张卡片,deck='{kp.get('subject','')}'。"
        return self._generate_and_save(prompt, kp_id, kp.get("subject", ""), model)

    def generate_from_subject(self, subject: str, count=10, model=None) -> list:
        """从科目所有知识点生成闪卡。"""
        kps = learn_db.search_knowledge_points(subject=subject, limit=50)
        if not kps:
            return [{"error": f"科目 {subject} 没有知识点"}]
        titles = "\n".join(
            f"- [{k['id']}] {k['title']}: {k.get('content','')[:100]}"
            for k in kps[:20])
        prompt = _FLASHCARD_GEN_PROMPT.format(source_text=titles) + \
                 f"\n生成 {count} 张卡片,deck='{subject}'。"
        return self._generate_and_save(prompt, None, subject, model)

    def get_due_cards(self, deck="", limit=20) -> list:
        return learn_db.get_due_flashcards(deck, limit)

    def review_card(self, card_id: int, quality: int) -> dict:
        """quality: 0=完全忘 1=有印象 3=勉强对 5=秒答"""
        learn_db.update_flashcard_review(card_id, quality)
        return {"reviewed": card_id, "quality": quality}

    def get_stats(self, deck="") -> dict:
        total = learn_db.count_flashcards(deck)
        due = len(learn_db.get_due_flashcards(deck, 999))
        return {
            "total_cards": total,
            "due_today": due,
            "deck": deck or "all",
        }

    def _generate_and_save(self, prompt, kp_id, subject, model) -> list:
        if not self.call_model:
            return [{"error": "LLM 未配置"}]
        content = (self.call_model([{"role": "user", "content": prompt}],
                   model, False).get("content") or "").strip()
        try:
            cards = json.loads(content) if content.startswith("[") else \
                    self._parse_json(content)
        except Exception:
            return [{"error": f"生成失败: {content[:200]}"}]
        result = []
        for c in cards:
            fid = learn_db.add_flashcard(
                front=c.get("front", ""), back=c.get("back", ""),
                hint=c.get("hint", ""), subject=subject,
                knowledge_point_id=kp_id, deck=c.get("deck", subject or "default"))
            result.append({"id": fid, "front": c.get("front", "")[:80],
                           "back": c.get("back", "")[:80]})
        return result

    @staticmethod
    def _parse_json(text: str):
        text = text.strip()
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("[") or part.startswith("json"):
                if part.startswith("json"): part = part[4:]
                try: return json.loads(part)
                except Exception: pass
        s, e = text.find("["), text.rfind("]")
        if s != -1 and e != -1:
            try: return json.loads(text[s:e+1])
            except Exception: pass
        return []



# 便捷函数


_course_engine = None
_flashcard_engine = None


def get_course_engine():
    global _course_engine
    if not _course_engine:
        _course_engine = CourseEngine()
    return _course_engine


def get_flashcard_engine(call_model=None):
    global _flashcard_engine
    if not _flashcard_engine:
        _flashcard_engine = FlashcardEngine(call_model)
    return _flashcard_engine
