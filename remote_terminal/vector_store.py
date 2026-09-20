# -*- coding: utf-8 -*-
"""
向量存储抽象层 — 基于 ChromaDB。

设计要点:
  - 统一接口: add / query / delete / count, 切换后端只改本文件
  - chunk 管理: 自动分段 + overlap + metadata 携带
  - 分类存储: 知识点、文档片段、记忆 各自独立 collection
  - 持久化: ChromaDB 自动 persist 到磁盘
"""

import logging as _logging
import os as _os

import embedding as _emb

_log = _logging.getLogger("brain")

# 存储路径
_VECTOR_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "vector_data")

# 全局客户端(懒加载)
_client = None


def _get_client():
    """懒加载 ChromaDB 客户端(线程安全由 ChromaDB 内部保证)。"""
    global _client
    if _client is not None:
        return _client
    try:
        import chromadb
        _os.makedirs(_os.environ.get("NOUS_VECTOR_DIR", _VECTOR_DIR), exist_ok=True)
        _client = chromadb.PersistentClient(
            path=_os.environ.get("NOUS_VECTOR_DIR", _VECTOR_DIR),
        )
        _log.info("ChromaDB 已连接: %s", _VECTOR_DIR)
        return _client
    except ImportError:
        raise RuntimeError("向量数据库需要 chromadb。安装: pip install chromadb")


# Collection 名称常量
COL_KNOWLEDGE = "knowledge_points"   # 知识点
COL_DOCUMENTS = "document_chunks"    # 文档片段
COL_MEMORIES = "memories"            # 长期记忆

# Chunk 配置
CHUNK_SIZE = int(_os.environ.get("NOUS_CHUNK_SIZE", "500"))      # 每段字符数
CHUNK_OVERLAP = int(_os.environ.get("NOUS_CHUNK_OVERLAP", "50")) # 段间重叠


def _get_collection(name: str):
    """获取或创建 collection。"""
    client = _get_client()
    try:
        return client.get_collection(name)
    except Exception:
        _log.info("创建 ChromaDB collection: %s", name)
        return client.create_collection(name)


def chunk_text(text: str, chunk_size=None, overlap=None) -> list[str]:
    """
    将长文本切分为重叠的 chunk。

    参数:
      text: 原始文本
      chunk_size: 每段最大字符数(默认 CHUNK_SIZE)
      overlap: 段间重叠字符数(默认 CHUNK_OVERLAP)

    返回: chunk 列表
    """
    cs = chunk_size or CHUNK_SIZE
    ol = overlap or CHUNK_OVERLAP
    if len(text) <= cs:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + cs, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += cs - ol
    return chunks


def add_knowledge_point(kp_id: int, title: str, content: str, subject: str = "",
                        metadata: dict = None):
    """
    将知识点加入向量库。
    对 title + content 做 chunk → embed → 存入 COL_KNOWLEDGE。
    """
    coll = _get_collection(COL_KNOWLEDGE)
    full_text = f"{title}\n{content}" if content else title
    chunks = chunk_text(full_text)

    if not chunks:
        return

    vectors = _emb.embed_documents(chunks)
    ids = [f"kp_{kp_id}_{i}" for i in range(len(chunks))]
    metas = []
    for i, _ in enumerate(chunks):
        meta = {
            "kp_id": kp_id,
            "title": title[:200],
            "subject": subject or "",
            "chunk_index": i,
            **(metadata or {}),
        }
        metas.append(meta)

    try:
        coll.add(ids=ids, embeddings=vectors, documents=chunks, metadatas=metas)
        _log.info("向量库: 知识点 #%d 入库(%d chunks)", kp_id, len(chunks))
    except Exception as e:
        _log.error("向量库写入知识点失败 #%d: %s", kp_id, e)


def add_document_chunks(doc_id: int, text: str, subject: str = "",
                        stage: str = "", doc_type: str = "", metadata: dict = None):
    """
    将文档文本 chunk 后加入向量库。
    """
    coll = _get_collection(COL_DOCUMENTS)
    chunks = chunk_text(text)
    if not chunks:
        return

    vectors = _emb.embed_documents(chunks)
    ids = [f"doc_{doc_id}_{i}" for i in range(len(chunks))]
    metas = []
    for i, _ in enumerate(chunks):
        meta = {
            "doc_id": doc_id,
            "subject": subject or "",
            "stage": stage or "",
            "doc_type": doc_type or "",
            "chunk_index": i,
            "total_chunks": len(chunks),
            **(metadata or {}),
        }
        metas.append(meta)

    try:
        coll.add(ids=ids, embeddings=vectors, documents=chunks, metadatas=metas)
        _log.info("向量库: 文档 #%d 入库(%d chunks)", doc_id, len(chunks))
    except Exception as e:
        _log.error("向量库写入文档失败 #%d: %s", doc_id, e)


def add_memory(memory_id: str, text: str, memory_type: str = "conversation",
               metadata: dict = None):
    """将短期记忆加入向量库。"""
    coll = _get_collection(COL_MEMORIES)
    vector = _emb.embed_query(text)
    meta = {"memory_type": memory_type, "text_preview": text[:200], **(metadata or {})}
    try:
        coll.add(ids=[memory_id], embeddings=[vector], documents=[text], metadatas=[meta])
    except Exception as e:
        _log.error("向量库写入记忆失败: %s", e)


def search_knowledge(query: str, top_k: int = 5, subject: str = "",
                     threshold: float = 0.6) -> list[dict]:
    """
    语义检索知识点。

    参数:
      query: 查询文本
      top_k: 返回最相似的 K 条
      subject: 可选,按科目过滤
      threshold: 相似度阈值,低于此值的丢弃

    返回: [{kp_id, title, content, score, chunk_index}, ...]
    """
    coll = _get_collection(COL_KNOWLEDGE)
    qv = _emb.embed_query(query)

    where = None
    if subject:
        where = {"subject": subject}

    try:
        results = coll.query(query_embeddings=[qv], n_results=top_k,
                            where=where, include=["documents", "metadatas", "distances"])
    except Exception as e:
        _log.error("向量检索知识点失败: %s", e)
        return []

    items = []
    ids_list = results.get("ids", [[]])[0]
    docs_list = results.get("documents", [[]])[0]
    metas_list = results.get("metadatas", [[]])[0]
    dists_list = results.get("distances", [[]])[0]

    for i, cid in enumerate(ids_list):
        dist = dists_list[i] if i < len(dists_list) else 1.0
        score = 1.0 - (dist / 2.0)  # ChromaDB distance → 0~1 相似度
        score = max(0.0, min(1.0, score))
        if score < threshold:
            continue
        meta = metas_list[i] if i < len(metas_list) else {}
        items.append({
            "id": cid,
            "kp_id": meta.get("kp_id"),
            "title": meta.get("title", ""),
            "content": docs_list[i] if i < len(docs_list) else "",
            "score": round(score, 3),
            "subject": meta.get("subject", ""),
            "chunk_index": meta.get("chunk_index", 0),
        })

    return items


def search_documents(query: str, top_k: int = 5, subject: str = "",
                     doc_type: str = "", threshold: float = 0.6) -> list[dict]:
    """
    语义检索文档片段。

    返回: [{doc_id, content, score, subject, stage, doc_type, chunk_index}, ...]
    """
    coll = _get_collection(COL_DOCUMENTS)
    qv = _emb.embed_query(query)

    where = {}
    if subject:
        where["subject"] = subject
    if doc_type:
        where["doc_type"] = doc_type
    if not where:
        where = None

    try:
        results = coll.query(query_embeddings=[qv], n_results=top_k,
                            where=where, include=["documents", "metadatas", "distances"])
    except Exception as e:
        _log.error("向量检索文档失败: %s", e)
        return []

    items = []
    ids_list = results.get("ids", [[]])[0]
    docs_list = results.get("documents", [[]])[0]
    metas_list = results.get("metadatas", [[]])[0]
    dists_list = results.get("distances", [[]])[0]

    for i, cid in enumerate(ids_list):
        dist = dists_list[i] if i < len(dists_list) else 1.0
        score = 1.0 - (dist / 2.0)
        score = max(0.0, min(1.0, score))
        if score < threshold:
            continue
        meta = metas_list[i] if i < len(metas_list) else {}
        items.append({
            "id": cid,
            "doc_id": meta.get("doc_id"),
            "content": docs_list[i] if i < len(docs_list) else "",
            "score": round(score, 3),
            "subject": meta.get("subject", ""),
            "stage": meta.get("stage", ""),
            "doc_type": meta.get("doc_type", ""),
            "chunk_index": meta.get("chunk_index", 0),
        })

    return items


def search_memories(query: str, top_k: int = 5, memory_type: str = "",
                    threshold: float = 0.4) -> list[dict]:
    """语义检索长期记忆。"""
    coll = _get_collection(COL_MEMORIES)
    qv = _emb.embed_query(query)

    where = None
    if memory_type:
        where = {"memory_type": memory_type}

    try:
        results = coll.query(query_embeddings=[qv], n_results=top_k,
                            where=where, include=["documents", "metadatas", "distances"])
    except Exception as e:
        _log.error("向量检索记忆失败: %s", e)
        return []

    items = []
    ids_list = results.get("ids", [[]])[0]
    docs_list = results.get("documents", [[]])[0]
    metas_list = results.get("metadatas", [[]])[0]
    dists_list = results.get("distances", [[]])[0]

    for i, mid in enumerate(ids_list):
        dist = dists_list[i] if i < len(dists_list) else 1.0
        score = 1.0 - (dist / 2.0)
        score = max(0.0, min(1.0, score))
        if score < threshold:
            continue
        meta = metas_list[i] if i < len(metas_list) else {}
        items.append({
            "id": mid,
            "content": docs_list[i] if i < len(docs_list) else "",
            "score": round(score, 3),
            "memory_type": meta.get("memory_type", ""),
        })

    return items


def delete_knowledge_point(kp_id: int):
    """删除指定知识点的所有向量。"""
    coll = _get_collection(COL_KNOWLEDGE)
    try:
        # ChromaDB 不支持前缀删除,需先查后删
        results = coll.get(where={"kp_id": kp_id})
        ids_to_delete = results.get("ids", [])
        if ids_to_delete:
            coll.delete(ids=ids_to_delete)
            _log.info("向量库: 删除知识点 #%d (%d chunks)", kp_id, len(ids_to_delete))
    except Exception as e:
        _log.error("向量库删除知识点失败 #%d: %s", kp_id, e)


def delete_document_chunks(doc_id: int):
    """删除指定文档的所有向量。"""
    coll = _get_collection(COL_DOCUMENTS)
    try:
        results = coll.get(where={"doc_id": doc_id})
        ids_to_delete = results.get("ids", [])
        if ids_to_delete:
            coll.delete(ids=ids_to_delete)
            _log.info("向量库: 删除文档 #%d (%d chunks)", doc_id, len(ids_to_delete))
    except Exception as e:
        _log.error("向量库删除文档失败 #%d: %s", doc_id, e)


def count(collection_name: str = COL_KNOWLEDGE) -> int:
    """返回 collection 中的向量数量。"""
    try:
        coll = _get_collection(collection_name)
        return coll.count()
    except Exception:
        return 0


def rebuild_knowledge_index():
    """
    重建知识点向量索引(全量,批处理优化)。
    从 learn_db 读取所有知识点 → 批量 embed → 覆盖写入。
    """
    import sys as _sys
    try:
        import learn_db
        learn_db.init()
        kps = learn_db.search_knowledge_points(limit=10000)
    except Exception as e:
        _log.error("读取知识点失败: %s", e)
        return 0

    if not kps:
        return 0

    # 清空旧数据
    coll = _get_collection(COL_KNOWLEDGE)
    try:
        old_ids = coll.get()["ids"]
        if old_ids:
            coll.delete(ids=old_ids)
    except Exception:
        pass

    # 批量准备数据: 收集所有 chunk 文本
    all_ids, all_docs, all_metas = [], [], []
    for kp in kps:
        kp_id = kp["id"]
        title = kp.get("title", "")
        content = kp.get("content", "")
        subject = kp.get("subject", "")
        full_text = f"{title}\n{content}" if content else title
        chunks = chunk_text(full_text)
        if not chunks:
            chunks = [full_text]
        for i, ch in enumerate(chunks):
            all_ids.append(f"kp_{kp_id}_{i}")
            all_docs.append(ch)
            all_metas.append({
                "kp_id": kp_id, "title": title[:200], "subject": subject or "",
                "chunk_index": i,
            })

    if not all_docs:
        return 0

    _log.info("批量 embedding %d 个文本片段(%d 个知识点)...", len(all_docs), len(kps))

    # 分批 embedding(每批32条,避免内存爆)
    batch_size = 32
    for i in range(0, len(all_docs), batch_size):
        batch_docs = all_docs[i:i + batch_size]
        batch_ids = all_ids[i:i + batch_size]
        batch_metas = all_metas[i:i + batch_size]
        try:
            batch_vecs = _emb.embed_documents(batch_docs)
            coll.add(ids=batch_ids, embeddings=batch_vecs, documents=batch_docs, metadatas=batch_metas)
            progress = min(i + batch_size, len(all_docs))
            _sys.stdout.write(f"\r  {progress}/{len(all_docs)}")
            _sys.stdout.flush()
        except Exception as e:
            _log.error("批量 embedding 失败(batch %d): %s", i // batch_size, e)

    _sys.stdout.write("\n")
    _log.info("向量索引重建完成: %d 个知识点, %d 个 chunk", len(kps), len(all_docs))
    return len(kps)
