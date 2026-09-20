# -*- coding: utf-8 -*-
"""
Nous 学习引擎 — 文档处理管道。

流程:
  PDF/Word/txt → DocumentProcessor 提取纯文本
  → StructureParser (LLM 分片分析) 提取结构化知识
  → KnowledgeIndexer 去重写入 learn_db

设计原则:
  - LLM 调用通过回调注入(call_model),本模块不直接依赖 brain.py
  - 大文档分片处理(每5页一组),避免超上下文
  - 所有输出可追溯来源文档+页码
"""

import json
import logging
import os
import re
import threading

import learn_db
import subject_experts

log = logging.getLogger("doc_engine")

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learn_docs")

# 串行化入库:同一时刻只解析一份文档,避免多份大文件并发 OCR/LLM 把内存撑爆
_INGEST_LOCK = threading.Lock()
OCR_MAX_MB = 40        # 超过此大小走分块 OCR(避免 OOM)
OCR_CHUNKED_MAX_MB = 200  # 分块 OCR 上限(与 process_document 的 MAX_MB 一致)
OCR_MAX_PAGES = 120
OCR_DPI = 110          # 低内存服务器:降分辨率省内存(够识别)
OCR_CHUNK_PAGES = 15   # 分块 OCR 每批处理的页数


def _ensure_docs_dir():
    os.makedirs(DOCS_DIR, exist_ok=True)



# 文档处理器 — 不同格式 → 纯文本


class DocumentProcessor:
    """将 PDF/Word/txt 文件转为纯文本。"""

    @staticmethod
    def parse(filepath: str) -> str:
        """
        返回文件全文(str)。大文件调用方应自行分片。
        支持: .pdf, .docx, .txt, .md
        """
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".txt" or ext == ".md":
            return DocumentProcessor._read_txt(filepath)
        elif ext == ".pdf":
            return DocumentProcessor._read_pdf(filepath)
        elif ext in (".docx", ".doc"):
            return DocumentProcessor._read_docx(filepath)
        else:
            raise ValueError(f"不支持的文件格式: {ext}")

    @staticmethod
    def _read_txt(filepath: str) -> str:
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                with open(filepath, encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        return ""

    @staticmethod
    def _read_pdf(filepath: str) -> str:
        """提取 PDF 文本:PyPDF2 → pdfplumber → (文本层为空=扫描版)OCR 兜底。"""
        best = ""
        # 1) PyPDF2
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(filepath)
            best = "\n\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            pass
        except Exception as e:
            log.warning("PyPDF2 失败: %s", e)
        # 2) pdfplumber(取更长的)
        if len(best.strip()) < 100:
            try:
                import pdfplumber
                with pdfplumber.open(filepath) as pdf:
                    t2 = "\n\n".join(p.extract_text() or "" for p in pdf.pages)
                if len(t2.strip()) > len(best.strip()):
                    best = t2
            except ImportError:
                pass
            except Exception as e:
                log.warning("pdfplumber 失败: %s", e)
        # 有文字层 → 直接用
        if len(best.strip()) >= 100:
            return best
        # 3) 扫描版 → OCR
        log.info("PDF 文字层近乎为空,启用 OCR: %s", os.path.basename(filepath))
        ocr = DocumentProcessor._ocr_pdf(filepath)
        return ocr if len(ocr.strip()) > len(best.strip()) else best

    @staticmethod
    def _ocr_pdf(filepath: str, max_pages=OCR_MAX_PAGES, dpi=OCR_DPI) -> str:
        """扫描版 PDF OCR。≤40MB 走直接 OCR;40-200MB 走分块 OCR。"""
        try:
            size_mb = os.path.getsize(filepath) / 1048576
        except OSError:
            size_mb = 0

        if size_mb > OCR_CHUNKED_MAX_MB:
            raise RuntimeError(
                f"扫描件 {size_mb:.0f}MB 过大(上限 {OCR_CHUNKED_MAX_MB}MB)。请拆分后再传。")

        if size_mb > OCR_MAX_MB:
            log.info("大扫描件 %.0fMB,走分块 OCR(每批 %d 页)", size_mb, OCR_CHUNK_PAGES)
            return DocumentProcessor._ocr_pdf_chunked(filepath, max_pages, dpi)

        # ≤40MB: 直接全量 OCR(最优路径)
        return DocumentProcessor._ocr_pdf_direct(filepath, max_pages, dpi)

    @staticmethod
    def _ocr_pdf_direct(filepath: str, max_pages=OCR_MAX_PAGES, dpi=OCR_DPI) -> str:
        """直接 OCR(≤40MB 文件,单次遍历)。"""
        try:
            import fitz
        except ImportError:
            raise RuntimeError(
                "扫描版/图片型 PDF 需要 OCR。请在服务器执行:\n"
                "  apt-get install -y tesseract-ocr tesseract-ocr-chi-sim poppler-utils\n"
                "  pip3 install --break-system-packages pymupdf pytesseract pillow")
        try:
            import io
            import pytesseract
            from PIL import Image
        except ImportError:
            raise RuntimeError(
                "扫描版 PDF 需要 OCR 依赖。请在服务器执行:\n"
                "  apt-get install -y tesseract-ocr tesseract-ocr-chi-sim\n"
                "  pip3 install --break-system-packages pytesseract pillow")
        parts = []
        doc = fitz.open(filepath)
        try:
            for i in range(min(len(doc), max_pages)):
                page = doc[i]
                pix = page.get_pixmap(dpi=dpi)
                try:
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    try:
                        txt = pytesseract.image_to_string(img, lang="chi_sim+eng")
                    except Exception:
                        txt = pytesseract.image_to_string(img)
                    if txt.strip():
                        parts.append(txt)
                    img.close()
                finally:
                    pix = None
        finally:
            doc.close()
        return "\n\n".join(parts)

    @staticmethod
    def _ocr_pdf_chunked(filepath: str, max_pages=OCR_MAX_PAGES,
                          pages_per_chunk=OCR_CHUNK_PAGES, dpi=OCR_DPI) -> str:
        """分块 OCR(40-200MB 大扫描件):逐批渲染+识别,每批后释放内存。"""
        try:
            import fitz
        except ImportError:
            raise RuntimeError("扫描版 PDF 需要 OCR 依赖(PyMuPDF)。")
        try:
            import io
            import gc
            import pytesseract
            from PIL import Image
        except ImportError:
            raise RuntimeError("扫描版 PDF 需要 OCR 依赖(pytesseract+pillow)。")

        parts = []
        doc = fitz.open(filepath)
        total_pages = min(len(doc), max_pages)
        try:
            for batch_start in range(0, total_pages, pages_per_chunk):
                batch_end = min(batch_start + pages_per_chunk, total_pages)
                log.info("分块 OCR: 第 %d-%d 页 / %d 页",
                         batch_start + 1, batch_end, total_pages)
                batch_parts = []
                for i in range(batch_start, batch_end):
                    page = doc[i]
                    pix = page.get_pixmap(dpi=dpi)
                    try:
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        try:
                            txt = pytesseract.image_to_string(img, lang="chi_sim+eng")
                        except Exception:
                            txt = pytesseract.image_to_string(img)
                        if txt.strip():
                            batch_parts.append(txt)
                        img.close()
                    finally:
                        pix = None
                if batch_parts:
                    parts.extend(batch_parts)
                # 每批后强制 GC,释放该批 pixmap 内存
                gc.collect()
        finally:
            doc.close()
        return "\n\n".join(parts)

    @staticmethod
    def _read_docx(filepath: str) -> str:
        try:
            from docx import Document
            doc = Document(filepath)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise RuntimeError("未安装 python-docx。请运行: pip install python-docx")

    @staticmethod
    def count_pages(filepath: str) -> int:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".pdf":
            try:
                from PyPDF2 import PdfReader
                return len(PdfReader(filepath).pages)
            except Exception:
                try:
                    import pdfplumber
                    with pdfplumber.open(filepath) as pdf:
                        return len(pdf.pages)
                except Exception:
                    return 0
        return 0



# 结构解析器 — 文本 → 结构化 JSON (LLM 驱动)


_PARSE_PROMPT = (
    "你是教材/讲义结构化专家。分析以下文本片段,提取所有可识别的知识点、公式和题目。\n\n"
    "输出严格 JSON,格式如下(不要 markdown 代码块,不要多余文字):\n"
    '{\n'
    '  "subject": "推断的科目(math/english/chinese/cs/physics/chemistry/other)",\n'
    '  "chapter": "章节名(如:第三章 导数与微分)",\n'
    '  "chapter_order": 3,\n'
    '  "sections": [{\n'
    '    "title": "小节标题(如:3.2 链式法则)",\n'
    '    "order": 2,\n'
    '    "knowledge_points": [{\n'
    '      "title": "知识点名",\n'
    '      "content": "知识点正文(关键定义/定理/方法)",\n'
    '      "type": "definition|theorem|method|concept|example",\n'
    '      "difficulty": 2,\n'
    '      "prerequisites": ["前置知识点名1","前置知识点名2"],\n'
    '      "formulas": [\n'
    '        {"name": "公式名","latex": "LaTeX表达式","plain": "纯文本表达式"}\n'
    '      ],\n'
    '      "exercises": [\n'
    '        {"question": "题目","answer": "答案或解题步骤"}\n'
    '      ]\n'
    '    }]\n'
    '  }]\n'
    '}\n\n'
    "规则:\n"
    "- 如果某个字段不存在(如无公式),填空数组[]或空字符串\n"
    "- difficulty: 1基础定义 2理解应用 3综合 4考试级\n"
    "- 每个知识点尽量独立,不要合并不同概念\n"
    "- 公式的 plain 字段用纯文本可读写法(LaTeX 在手机上不渲染)\n"
    "- 题目和答案要完整,不要截断"
)


# 题库专用:重点拆每道题 → 题干+答案/解析。允许把题直接放在 section 级,免得提不出知识点就丢题。
_PARSE_PROMPT_EXERCISES = _PARSE_PROMPT + (
    "\n\n【重要·题库模式】这是一份习题/试卷/题库。务必**逐题提取,一题都别漏**:\n"
    "- 即使识别不出明确知识点,也要把每道题放进所在 section 的 \"exercises\" 数组里:\n"
    '  sections:[{ "title":"大题/部分名(如 一、选择题)", "exercises":[{"question":"完整题干含选项","answer":"答案与解析"}], "knowledge_points":[] }]\n'
    "- question 要完整(含 ABCD 选项),answer 尽量带答案+解析\n"
    "- 整张卷子至少产出与题目数量相当的 exercises,不要返回空 sections"
)
# 课本专用:重点拆知识点/定义/定理/公式
_PARSE_PROMPT_TEXTBOOK = _PARSE_PROMPT + (
    "\n\n【重要·课本模式】这是一份教材/讲义。请把重点放在**知识体系**:\n"
    "- 完整提取定义/定理/方法/公式,按章节层级组织\n"
    "- 知识点要独立、可检索;example 类可少量保留为 exercises"
)


class StructureParser:
    """
    将纯文本切片送 LLM 分析,返回结构化知识点+公式+题目。
    call_model(convo: list, model: str, use_tools: bool) -> dict
    返回 {"role":"assistant","content":"..."}
    doc_type: "" 自动 / "textbook" 课本 / "exercises" 题库
    """

    def __init__(self, call_model, model=None, doc_type=""):
        self.call_model = call_model
        self.model = model
        self.doc_type = doc_type

    def parse_chunk(self, text: str, source_doc="", start_page=0) -> dict:
        """分析一个文本切片(通常5页),返回结构化 JSON。"""
        base = _PARSE_PROMPT
        if self.doc_type == "exercises":
            base = _PARSE_PROMPT_EXERCISES
        elif self.doc_type == "textbook":
            base = _PARSE_PROMPT_TEXTBOOK
        prompt = base + f"\n\n--- 以下是要分析的文本片段(来源:{source_doc},页码约{start_page+1}-{start_page+5})---\n\n{text[:12000]}"
        convo = [{"role": "user", "content": prompt}]
        try:
            content = (self.call_model(convo, self.model, False).get("content") or "").strip()
            return _extract_json(content)
        except Exception as e:
            log.error("LLM 解析片段失败(%s, p%d): %s", source_doc, start_page, e)
            return {}

    def parse_full(self, full_text: str, source_doc="", total_pages=0,
                   chunk_pages=5, on_progress=None) -> list:
        """
        将全文分片,逐片送 LLM 分析,合并结果。
        on_progress(current, total): 进度回调
        返回: list of section dict
        """
        chunks = self._split_text(full_text, chunk_pages)
        all_sections = []
        all_kps = set()  # 去重用

        for i, chunk in enumerate(chunks):
            if on_progress:
                on_progress(i + 1, len(chunks))
            result = self.parse_chunk(
                chunk, source_doc=source_doc,
                start_page=i * chunk_pages)
            if not result:
                continue
            for sec in result.get("sections", []):
                for kp in sec.get("knowledge_points", []):
                    kp["source_doc"] = source_doc
                    kp["source_page"] = i * chunk_pages + 1
                    kp["subject"] = result.get("subject", "")
                    kp["chapter"] = result.get("chapter", "")
                    kp["section"] = sec.get("title", "")
                all_sections.append(sec)
                for kp in sec.get("knowledge_points", []):
                    all_kps.add((kp["title"], kp.get("chapter", "")))

        log.info("解析完成: %s, %d 切片, %d 节, %d 知识点",
                source_doc, len(chunks), len(all_sections), len(all_kps))
        return all_sections

    def parse_vocab(self, full_text: str, source_doc="", on_progress=None) -> list:
        """词汇资料 → [{word,meaning,example,subject}](去重)。"""
        chunks = self._split_text(full_text, 5)
        words, seen = [], set()
        for i, ch in enumerate(chunks):
            if on_progress:
                on_progress(i + 1, len(chunks))
            prompt = _VOCAB_PROMPT + f"\n\n--- 文本片段 ---\n{ch[:12000]}"
            try:
                content = (self.call_model([{"role": "user", "content": prompt}],
                                           self.model, False).get("content") or "")
                data = _extract_json(content)
            except Exception as e:
                log.warning("词汇解析片段失败: %s", e)
                data = {}
            subj = data.get("subject", "")
            for w in data.get("words", []):
                wd = (w.get("word") or "").strip()
                if not wd or wd.lower() in seen:
                    continue
                seen.add(wd.lower())
                words.append({"word": wd, "meaning": (w.get("meaning") or "").strip(),
                              "example": (w.get("example") or "").strip(), "subject": subj})
        return words

    @staticmethod
    def _split_text(text: str, pages_per_chunk=5) -> list:
        """按页数分片(用换页符或空行分隔,约2500字≈1页)。"""
        words_per_page = 2500
        words = text.split()
        chunk_size = pages_per_chunk * words_per_page
        chunks = []
        current = []
        count = 0
        for w in words:
            current.append(w)
            count += 1
            if count >= chunk_size:
                chunks.append(" ".join(current))
                current = []
                count = 0
        if current:
            chunks.append(" ".join(current))
        return chunks



# 知识索引器 — JSON → learn_db 写入 + 去重


class KnowledgeIndexer:
    """接收 StructureParser 输出,去重后写入数据库。"""

    def __init__(self):
        learn_db.init()

    def index_sections(self, sections: list, source_doc="", subject_default="", stage="") -> dict:
        """
        将解析结果写入数据库。subject/stage 强制用文档级值(保证一份资料归一类)。
        返回: {"kps_added": N, "formulas_added": N, "exercises_added": N}
        """
        stats = {"kps_added": 0, "formulas_added": 0, "exercises_added": 0}
        subject = subject_default  # 强制:整份文档同一科目

        # 先建章节级父知识点
        chapter_kps = {}
        for sec in sections:
            chapter = sec.get("title", "") or source_doc
            if chapter not in chapter_kps:
                parent_id = learn_db.add_knowledge_point(
                    subject=subject,
                    title=chapter,
                    chapter=chapter,
                    source_doc=source_doc,
                    difficulty=1,
                    stage=stage)
                chapter_kps[chapter] = parent_id

            # section 级题目(题库模式:题目可能不挂在知识点下,直接挂章节,避免丢题)
            for ex in sec.get("exercises", []):
                q = (ex.get("question") or "").strip()
                if not q:
                    continue
                learn_db.add_exercise(
                    knowledge_point_id=chapter_kps.get(chapter),
                    question=q, answer=ex.get("answer", ""), difficulty=2,
                    source_doc=source_doc)
                stats["exercises_added"] += 1

            for kp_data in sec.get("knowledge_points", []):
                title = kp_data.get("title", "").strip()
                if not title:
                    continue

                # 去重: 同(科目,标题)精确匹配,避免 LIKE 误并/漏并
                existing = learn_db.find_kp_by_title(subject, title)
                if existing:
                    kp_id = existing["id"]
                else:
                    kp_id = learn_db.add_knowledge_point(
                        subject=subject,
                        title=title,
                        content=kp_data.get("content", ""),
                        chapter=kp_data.get("chapter", ""),
                        section=kp_data.get("section", ""),
                        parent_id=chapter_kps.get(chapter),
                        prerequisites=kp_data.get("prerequisites", []),
                        difficulty=kp_data.get("difficulty", 2),
                        source_doc=source_doc,
                        source_page=kp_data.get("source_page", 0),
                        stage=stage)
                    stats["kps_added"] += 1

                # 提取公式
                for fm in kp_data.get("formulas", []):
                    name = fm.get("name", "").strip()
                    if not name:
                        continue
                    # 去重公式
                    exist_fm = learn_db.search_formulas(keyword=name, limit=1)
                    if not exist_fm:
                        learn_db.add_formula(
                            name=name,
                            latex=fm.get("latex", ""),
                            plain_text=fm.get("plain", ""),
                            subject=subject,
                            knowledge_point_id=kp_id,
                            source_doc=source_doc,
                            source_page=kp_data.get("source_page", 0),
                            usage_tags=[title])
                        stats["formulas_added"] += 1

                # 提取题目
                for ex in kp_data.get("exercises", []):
                    q = ex.get("question", "").strip()
                    if not q:
                        continue
                    learn_db.add_exercise(
                        knowledge_point_id=kp_id,
                        question=q,
                        answer=ex.get("answer", ""),
                        difficulty=kp_data.get("difficulty", 2),
                        source_doc=source_doc,
                        source_page=kp_data.get("source_page", 0))
                    stats["exercises_added"] += 1

        return stats



# 完整管道 — 一步执行


# Subject canonical mapping: aliases / LLM output → canonical name
# This is configurable — users should customize for their domain.
_SUBJECT_CANONICAL = {
    "数学": "数学", "高数": "数学", "math": "数学",
    "英语": "英语", "英文": "英语", "english": "英语",
    "物理": "物理", "physics": "物理",
    "化学": "化学", "chemistry": "化学",
    "计算机": "计算机", "CS": "计算机", "cs": "计算机",
    "政治": "政治",
}

# subject_experts key → canonical name
_SUBJECT_KEY_TO_CANONICAL = {
    "math": "数学", "english": "英语", "chinese": "语文",
    "cs": "计算机", "physics": "物理", "chemistry": "化学",
}


def _keyword_vote_subject(sample_text: str) -> str:
    """用 subject_experts 的关键词对样本文字做频率统计,返回得分最高的规范科目名。"""
    if not sample_text:
        return ""
    text_lower = sample_text.lower()
    scores = {}
    for subj_key, keywords in subject_experts.SUBJECT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[subj_key] = score
    if not scores:
        return ""
    best_key = max(scores, key=scores.get)
    return _SUBJECT_KEY_TO_CANONICAL.get(best_key, "")


def classify_document(call_model, filename, sample_text, taxonomy=None) -> dict:
    """
    一次性分类(便宜模型):返回 {stage, subject, doc_type}。
    增加 keyword 交叉校验:若 LLM 输出与关键词统计矛盾,以关键词统计为准。
    taxonomy: {"stages":[...],"subjects":[...],"doc_types":[...]} 已有词表,优先复用,避免别名分裂。
    """
    taxonomy = taxonomy or {}
    def _hint(label, vals):
        return f"已有{label}(优先从中选,确实没有再新建):{', '.join(vals)}\n" if vals else ""

    # 构建科目提示(含各科涵盖范围,减少 LLM 自由发挥)
    subject_guide = (
        "科目必须从以下标准名称中选一(或留空让我自动判断):\n"
        "- 高等数学(含:微积分/线性代数/概率/函数/导数/积分/方程/几何/数列)\n"
        "- 英语(含:词汇/语法/阅读/写作/翻译/完形/听力)\n"
        "- 大学语文(含:文言文/现代文/诗歌/作文/文学常识/修辞)\n"
        "- 计算机(含:编程/网络/多媒体/数据库/操作系统/算法/数据结构/信息安全)\n"
        "- 政治(含:马原/毛概/思修/时政)\n"
        "务必用以上标准名称,不要用简称或自创科目。\n"
    )
    prompt = (
        "你是学习资料分类专家。根据文件名和正文片段,判断这份资料的三个分类,只输出 JSON:\n"
        '{"stage":"备考阶段","subject":"科目","doc_type":"类型"}\n\n'
        "- stage 备考阶段:如 考研 / 高考 / 四六级 / 通用(无法判断填 通用)\n"
        + subject_guide
        + "- doc_type 类型:课本 / 讲义 / 题库 / 试卷 / 单词 / 笔记 / 资料 之一(单词表/词汇/必背词填『单词』)\n"
        + _hint("阶段", taxonomy.get("stages", []))
        + _hint("科目", taxonomy.get("subjects", []))
        + _hint("类型", taxonomy.get("doc_types", []))
        + f"\n文件名:{filename}\n正文片段:\n{(sample_text or '')[:1500]}"
    )
    try:
        content = (call_model([{"role": "user", "content": prompt}], None, False).get("content") or "")
        meta = _extract_json(content)
    except Exception as e:
        log.warning("分类失败,用默认: %s", e)
        meta = {}

    subject = (meta.get("subject") or "其他").strip()[:30]

    # keyword 交叉校验:防止"多媒体/网络"误分类为"高等数学"
    kw_subject = _keyword_vote_subject(sample_text)
    if kw_subject and subject != kw_subject:
        # 检查 LLM 输出是否与关键词统计明显矛盾
        # 如果样本中某个科目的关键词密度显著(>=3 个命中),且 LLM 给了不同科目,以关键词为准
        text_lower = (sample_text or "").lower()
        llm_mapped = _SUBJECT_CANONICAL.get(subject, "")
        if llm_mapped and llm_mapped != kw_subject:
            # 统计 LLM 科目对应的关键词命中数
            llm_key = None
            for skey, cname in _SUBJECT_KEY_TO_CANONICAL.items():
                if cname == llm_mapped:
                    llm_key = skey
                    break
            kw_score = sum(1 for kw in subject_experts.SUBJECT_KEYWORDS.get(
                _reverse_subject_key(kw_subject), []) if kw.lower() in text_lower)
            llm_score = sum(1 for kw in subject_experts.SUBJECT_KEYWORDS.get(
                llm_key or "", []) if kw.lower() in text_lower) if llm_key else 0
            if kw_score > llm_score:
                log.info("keyword 交叉校验:LLM 输出'%s'(得分%d) 被关键词统计'%s'(得分%d) 覆盖 for %s",
                         subject, llm_score, kw_subject, kw_score, filename)
                subject = kw_subject

    # 规范化映射:别名 -> 规范全称
    subject = _SUBJECT_CANONICAL.get(subject, subject)

    return {
        "stage": (meta.get("stage") or "通用").strip()[:20],
        "subject": subject,
        "doc_type": (meta.get("doc_type") or "资料").strip()[:10],
    }


def _reverse_subject_key(canonical_name: str) -> str:
    """从规范科目名反查 subject_experts 的 key。"""
    for skey, cname in _SUBJECT_KEY_TO_CANONICAL.items():
        if cname == canonical_name:
            return skey
    return ""


# 单词/词汇:抽成词卡(word/释义/例句)
_VOCAB_PROMPT = (
    "你在把一份单词/词汇资料结构化。提取其中所有词汇,严格输出 JSON(不要 markdown,不要多余文字):\n"
    '{"subject":"科目(如 英语)","words":[{"word":"单词或词组","meaning":"中文释义(可含词性)","example":"例句(没有就空字符串)"}]}\n'
    "规则:尽量提全、一词一项;释义简洁;保留原词形;没有例句填空串。"
)

# 类型中文 → 解析模式
_DOCTYPE_MODE = {"题库": "exercises", "试卷": "exercises", "习题": "exercises", "真题": "exercises",
                 "课本": "textbook", "讲义": "textbook", "教材": "textbook",
                 "单词": "vocab", "词汇": "vocab", "词汇表": "vocab", "单词表": "vocab"}


def process_document(filepath: str, call_model, model=None,
                     subject="", doc_type="", stage="", taxonomy=None,
                     keep_original=False, on_progress=None) -> dict:
    """
    完整文档处理管道: 分类 → 解析 → 结构提取 → 入库。
    subject/stage/doc_type 留空时由 LLM 一次性分类;非空则尊重用户指定。
    call_model: 入库用的(便宜)LLM 调用函数
    """
    _ensure_docs_dir()
    learn_db.init()

    filename = os.path.basename(filepath)
    filetype = os.path.splitext(filepath)[1].lower()

    # 大文件保护:避免一次性读爆内存
    try:
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
    except OSError:
        size_mb = 0
    MAX_MB = 200

    # 重复上传 = 刷新:先清掉同名旧文档及其知识点
    try:
        learn_db.delete_document_by_filename(filename)
    except Exception:
        pass

    # 先登记文档(status=parsing),即使后面失败也能在列表里看到+看到原因
    dest = os.path.join(DOCS_DIR, filename)
    doc_id = learn_db.add_document(
        filename=filename, filepath=dest, filetype=filetype,
        subject=subject, total_pages=0, stage=stage, doc_type=doc_type)
    learn_db.update_document_status(doc_id, "parsing", note="", progress="")

    try:
        if size_mb > MAX_MB:
            raise RuntimeError(f"文件 {size_mb:.0f}MB 超过 {MAX_MB}MB 上限,请拆分后上传")

        # 1. 解析为纯文本
        if on_progress:
            on_progress("parsing", 0, 1)
        processor = DocumentProcessor()
        full_text = processor.parse(filepath)   # 图片/不支持格式会在此抛错 → 进 except,可见
        total_pages = processor.count_pages(filepath)
        if not full_text.strip():
            raise RuntimeError("文档内容为空或无法提取文本(扫描版/图片需先 OCR)")

        # 复制原件到 learn_docs/
        if filepath != dest:
            import shutil
            shutil.copy2(filepath, dest)

        # 1.5 分类(缺啥补啥,一次便宜模型调用)
        if not (subject and stage and doc_type):
            meta = classify_document(call_model, filename, full_text[:1500], taxonomy)
            stage = stage or meta["stage"]
            subject = subject or meta["subject"]
            doc_type = doc_type or meta["doc_type"]
        learn_db.update_document_meta(doc_id, stage=stage, subject=subject, doc_type=doc_type)
        log.info("文档分类: %s → 阶段=%s 科目=%s 类型=%s", filename, stage, subject, doc_type)

        # 3. 结构解析(模式由类型决定),进度写回 DB
        if on_progress:
            on_progress("parsing_structure", 0, total_pages or 1)
        parse_mode = _DOCTYPE_MODE.get(doc_type, "")
        parser = StructureParser(call_model, model, doc_type=parse_mode)

        def _chunk_progress(cur, tot):
            try:
                learn_db.update_document_status(doc_id, "parsing", progress=f"{cur}/{tot}")
            except Exception:
                pass
            if on_progress:
                on_progress("parsing_structure", cur, tot)

        if parse_mode == "vocab":
            # 单词资料 → 词卡(flashcards),带 SM-2,可做每日背诵/复习
            words = parser.parse_vocab(full_text, source_doc=filename, on_progress=_chunk_progress)
            for w in words:
                try:
                    learn_db.add_flashcard(front=w["word"], back=w["meaning"],
                                           hint=w.get("example", ""), subject=subject,
                                           source=filename, deck=(subject or "词汇"))
                except Exception:
                    pass
            stats = {"kps_added": len(words), "formulas_added": 0, "exercises_added": 0}
            learn_db.mark_document_parsed(doc_id, kp_count=len(words), ex_count=0)
        else:
            sections = parser.parse_full(
                full_text, source_doc=filename, total_pages=total_pages,
                on_progress=_chunk_progress)
            if on_progress:
                on_progress("indexing", 0, 1)
            indexer = KnowledgeIndexer()
            stats = indexer.index_sections(sections, source_doc=filename,
                                           subject_default=subject, stage=stage)
            # 兜底:结构化抽空(0知识点0题)但其实有文字 → 别丢
            if stats["kps_added"] == 0 and stats["exercises_added"] == 0:
                qs = _fallback_questions(full_text)
                if len(qs) >= 5:        # 像试卷/习题 → 按题号切成题目
                    kp = learn_db.add_knowledge_point(
                        subject=subject, title=os.path.splitext(filename)[0][:40],
                        chapter=filename, source_doc=filename, difficulty=2, stage=stage)
                    for q in qs:
                        learn_db.add_exercise(knowledge_point_id=kp, question=q,
                                              answer="", difficulty=2, source_doc=filename)
                    stats["exercises_added"] = len(qs)
                    log.info("兜底题号切分: %s → %d 题", filename, len(qs))
                else:                   # 讲义/资料 → 原文切块存成知识点
                    for title, ch in _fallback_text_kps(full_text):
                        learn_db.add_knowledge_point(
                            subject=subject, title=title, content=ch,
                            chapter=os.path.splitext(filename)[0][:40],
                            source_doc=filename, difficulty=2, stage=stage)
                        stats["kps_added"] += 1
                    if stats["kps_added"]:
                        log.info("兜底原文切块: %s → %d 段知识点", filename, stats["kps_added"])
            learn_db.mark_document_parsed(doc_id, stats["kps_added"], stats["exercises_added"])
        # 默认解析后删原件,只留知识点(省盘:30G 也能存上万本)
        if not keep_original:
            for fp in {dest, filepath}:
                try:
                    if os.path.isfile(fp):
                        os.remove(fp)
                except Exception:
                    pass
    except Exception as e:
        learn_db.update_document_status(doc_id, "error", note=str(e)[:300])
        log.error("文档处理失败 %s: %s", filename, e)
        raise

    # RAG: 将知识点和文档片段写入向量库
    _index_to_vector_db(doc_id, filename, subject, stage, doc_type, full_text)

    result = {"doc_id": doc_id, "pages": total_pages, "filename": filename,
              "stage": stage, "subject": subject, "doc_type": doc_type, **stats}
    log.info("文档处理完成: %s", json.dumps(result, ensure_ascii=False))
    return result



# 工具函数


_Q_MARK = re.compile(
    r'(?m)^\s*(?:第?\s*\d{1,3}\s*[\.\、\)）]|\(\s*\d{1,3}\s*\)|（\s*\d{1,3}\s*）|[一二三四五六七八九十]+\s*[、\.])')


def _fallback_questions(text: str, max_q=400) -> list:
    """LLM 没抽出题时的兜底:按题号(1. / 2、/ (3) / 一、)切原文成题块。"""
    if not text:
        return []
    marks = [m.start() for m in _Q_MARK.finditer(text)]
    if len(marks) < 3:        # 题号太少,不像题库
        return []
    blocks = []
    for i, s in enumerate(marks):
        e = marks[i + 1] if i + 1 < len(marks) else len(text)
        b = text[s:e].strip()
        if 8 <= len(b) <= 2000:
            blocks.append(b)
        if len(blocks) >= max_q:
            break
    return blocks


def _fallback_text_kps(full_text: str, max_chunks=80, size=1200) -> list:
    """结构化抽空时的兜底:把原文按长度切块,每块当一个知识点(标题取首行)。保证有内容就能调用。"""
    text = (full_text or "").strip()
    if len(text) < 60:
        return []
    out = []
    for i in range(0, len(text), size):
        ch = text[i:i + size].strip()
        if len(ch) < 30:
            continue
        first = ""
        for ln in ch.splitlines():
            ln = ln.strip()
            if len(ln) >= 4:
                first = ln[:40]; break
        out.append((first or f"片段{len(out) + 1}", ch))
        if len(out) >= max_chunks:
            break
    return out


# RAG 向量索引
def _index_to_vector_db(doc_id, filename, subject, stage, doc_type, full_text):
    """
    将文档内容写入向量库(后台任务,失败不影响主流程)。
    1) 所有知识点 → vector_store.add_knowledge_point()
    2) 文档原文 chunk → vector_store.add_document_chunks()
    """
    try:
        import vector_store
    except ImportError:
        log.warning("vector_store 未安装,跳过向量索引")
        return

    try:
        # 1) 索引该文档的所有知识点
        import learn_db
        kps = learn_db.search_knowledge_points(source_doc=filename, limit=5000)
        for kp in kps:
            try:
                vector_store.add_knowledge_point(
                    kp["id"], kp.get("title", ""), kp.get("content", ""),
                    kp.get("subject", subject or ""),
                )
            except Exception as e:
                log.error("向量索引知识点 #%s 失败: %s", kp.get("id"), e)
        if kps:
            log.info("RAG: 已索引 %d 个知识点 → 向量库", len(kps))

        # 2) 索引文档原文
        if full_text and len(full_text) > 100:
            vector_store.add_document_chunks(
                doc_id, full_text, subject=subject or "",
                stage=stage or "", doc_type=doc_type or "",
            )
    except Exception as e:
        log.error("向量索引失败 doc #%d: %s", doc_id, e)


def _extract_json(text: str) -> dict:
    """从 LLM 回复中提取 JSON(容错 markdown 代码块)。"""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("{") or p.startswith("json"):
                if p.startswith("json"):
                    p = p[4:]
                try:
                    return json.loads(p)
                except Exception:
                    pass
    # 直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 截取 { 到 }
    s = text.find("{")
    e = text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except Exception:
            pass
    return {}



# 大文件处理 — 流式分页解析


class LargeFileProcessor:
    """
    处理大于 50MB 的 PDF。

    策略:
      1. 先只解析目录页/前10页 → 给用户快速预览
      2. 后台逐批解析(每10页一组) → 进度通过回调报告
      3. 支持断点续传: 记录已解析到第几页
      4. 单页可独立重解析
    """

    MAX_PREVIEW_PAGES = 10
    CHUNK_PAGES = 10
    MAX_FILE_MB = 200  # 绝对上限

    @staticmethod
    def preview(filepath: str) -> dict:
        """快速预览: 只解析前10页 + 目录,返回概览。"""
        processor = DocumentProcessor()
        total = processor.count_pages(filepath)
        full_text = processor.parse(filepath)
        preview_text = full_text[:25000]  # ~10页

        return {
            "total_pages": total,
            "filepath": filepath,
            "preview_text": preview_text[:3000],
            "size_mb": round(os.path.getsize(filepath) / (1024 * 1024), 1),
        }

    @staticmethod
    def parse_streaming(filepath: str, call_model, model=None,
                        on_page_progress=None, subject="") -> dict:
        """
        流式解析大文件: 逐批处理,每批报告进度。

        on_page_progress(current_page, total_pages, stage)
        返回: {"kps_added": N, "pages_processed": N, ...}
        """
        processor = DocumentProcessor()
        total = processor.count_pages(filepath)
        full_text = processor.parse(filepath)
        words = full_text.split()
        words_per_page = 2500

        stats = {"kps_added": 0, "formulas_added": 0, "exercises_added": 0,
                 "pages_processed": 0, "chunks_processed": 0}

        parser = StructureParser(call_model, model)
        indexer = KnowledgeIndexer()
        filename = os.path.basename(filepath)

        for chunk_start in range(0, total, LargeFileProcessor.CHUNK_PAGES):
            chunk_end = min(chunk_start + LargeFileProcessor.CHUNK_PAGES, total)
            if on_page_progress:
                on_page_progress(chunk_start, total, "parsing")

            start_word = chunk_start * words_per_page
            end_word = chunk_end * words_per_page
            chunk_text = " ".join(words[start_word:min(end_word, len(words))])
            if not chunk_text.strip():
                continue

            result = parser.parse_chunk(
                chunk_text, source_doc=filename,
                start_page=chunk_start)

            if result:
                chunk_stats = indexer.index_sections(
                    result.get("sections", []),
                    source_doc=filename, subject_default=subject)
                for k, v in chunk_stats.items():
                    stats[k] = stats.get(k, 0) + v

            stats["pages_processed"] = chunk_end
            stats["chunks_processed"] += 1

        return stats



# 图片识别 — OCR + 视觉 LLM


class ImageRecognizer:
    """
    图片 → 文字 + 结构化题目。

    策略:
      1. 优先用 Tesseract OCR (本地,免费)
      2. 公式/复杂图表 → 上传给支持视觉的 LLM (GPT-4o/Claude/Gemini)
      3. 自动判断图片类型: 题目截图 / 课本页 / 手写笔记
    """

    @staticmethod
    def ocr(filepath: str) -> str:
        """Tesseract OCR 提取文字。"""
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(filepath)
            return pytesseract.image_to_string(img, lang="chi_sim+eng")
        except ImportError:
            raise RuntimeError(
                "OCR 需要: pip install pytesseract Pillow\n"
                "以及系统包: apt install tesseract-ocr tesseract-ocr-chi-sim")
        except Exception as e:
            raise RuntimeError(f"OCR 失败: {e}")

    @staticmethod
    def analyze_with_vision(filepath: str, question: str,
                            vision_call_model) -> str:
        """
        用视觉 LLM 分析图片(公式/图表/手写)。

        vision_call_model: 支持图片的 LLM 调用函数
        """
        # 将图片编码为 base64
        import base64
        with open(filepath, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        prompt = (
            f"{question}\n\n"
            "如果图片是数学题,输出题目文本和解题步骤。\n"
            "如果是课本页,提取所有知识点和公式。\n"
            "如果是手写笔记,转写为可编辑文本。"
        )

        # 构造 vision API 请求(OpenAI 格式)
        import config
        import model_gateway_bridge as gateway_bridge
        api_key = (getattr(config, "VISION_API_KEY", "") or
                   getattr(config, "LLM_API_KEY", ""))
        api_url = (getattr(config, "VISION_API_URL", "") or
                   getattr(config, "LLM_API_URL", "").replace(
                       "/chat/completions", "/chat/completions"))
        model = getattr(config, "VISION_MODEL", "gpt-4o")
        messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            }]
        result = gateway_bridge.invoke_message(
            messages,
            endpoint=api_url,
            api_key=api_key,
            model=model,
            timeout_s=60,
            vision=True,
            max_tokens=2000,
        )
        return str(result.message.get("content") or "")

    @staticmethod
    def classify(filepath: str) -> str:
        """
        判断图片类型: problem / textbook / handwritten / other。
        基于图片特征(不需要 LLM)。
        """
        try:
            from PIL import Image
            img = Image.open(filepath)
            w, h = img.size
            # 简单启发式: 长方形+大尺寸 = 课本页, 方形+小尺寸 = 题目截图
            ratio = w / h if h > 0 else 1
            if ratio > 1.5:
                return "textbook"  # 横向大图 → 课本
            elif ratio < 0.7:
                return "textbook"  # 纵向 → 课本
            elif w < 800:
                return "problem"   # 小图 → 题目截图
            return "textbook"
        except Exception:
            return "other"
