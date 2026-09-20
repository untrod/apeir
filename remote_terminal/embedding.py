# -*- coding: utf-8 -*-
"""
Embedding 模型层。

三模式(自动检测,优先级从高到低):
  1. API 模式: NOUS_EMBED_API_URL/KEY/MODEL → OpenAI 兼容 embedding API
  2. fastembed(默认): BAAI/bge-small-zh-v1.5, ONNX, ~50MB, CPU, 中文优化
  3. ChromaDB 内置(回退): all-MiniLM-L6-v2, ONNX, ~80MB, 英文

设计: 懒加载 + 线程安全 + 零额外依赖(仅需 chromadb)
"""

import logging as _logging
import os as _os
import threading as _threading
import time as _time

_log = _logging.getLogger("brain")

# API 模式(可选)
_EMBED_API_URL = _os.environ.get("NOUS_EMBED_API_URL", "")
_EMBED_API_KEY = _os.environ.get("NOUS_EMBED_API_KEY", "")
_EMBED_API_MODEL = _os.environ.get("NOUS_EMBED_API_MODEL", "text-embedding-3-small")

_EMBED_MODEL = _os.environ.get("NOUS_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
_EMBED_BATCH = int(_os.environ.get("NOUS_EMBED_BATCH", "32"))

# 单例
_ef = None
_lock = _threading.Lock()
_mode = None  # "api" | "fastembed" | "chromadb"


def _detect_mode() -> str:
    global _mode
    if _mode is not None:
        return _mode

    # 1) API 优先
    if _EMBED_API_URL and _EMBED_API_KEY:
        _mode = "api"
        _log.info("embedding: API 模式(%s)", _EMBED_API_MODEL)
        return _mode

    # 2) fastembed(轻量中文 ONNX)
    try:
        from fastembed import TextEmbedding
        _mode = "fastembed"
        _log.info("embedding: fastembed(%s)", _EMBED_MODEL)
        return _mode
    except ImportError:
        pass

    # 3) ChromaDB 内置(英文回退)
    try:
        import chromadb.utils.embedding_functions
        _mode = "chromadb"
        _log.info("embedding: ChromaDB 内置 ONNX(英文)")
        return _mode
    except ImportError:
        pass

    raise RuntimeError(
        "无法加载 embedding。请:\n"
        "  1) pip install fastembed (推荐,中文优化,~50MB)\n"
        "  2) 或 pip install chromadb (英文回退)\n"
        "  3) 或设置 NOUS_EMBED_API_URL/KEY 使用远程 API"
    )


def _get_ef():
    """懒加载 embedding function。"""
    global _ef
    if _ef is not None:
        return _ef
    with _lock:
        if _ef is not None:
            return _ef
        mode = _detect_mode()
        if mode == "api":
            return None  # API 模式不需要本地对象
        elif mode == "fastembed":
            from fastembed import TextEmbedding
            _ef = TextEmbedding(model_name=_EMBED_MODEL, threads=2)
            _log.info("fastembed 已就绪: %s", _EMBED_MODEL)
        elif mode == "chromadb":
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
            _ef = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
            _log.info("ChromaDB ONNX 已就绪(英文)")
    return _ef


def embed(texts):
    """对文本列表做 embedding。单条文本传 str。返回 list[list[float]]。"""
    single = isinstance(texts, str)
    if single:
        texts = [texts]
    if not texts:
        return []

    mode = _detect_mode()

    if mode == "api":
        return _embed_api(texts, single)
    else:
        ef = _get_ef()
        t0 = _time.time()
        if mode == "fastembed":
            vectors = list(ef.embed(texts))
        else:
            vectors = ef(texts)
        _log.debug("embed %d 条, %.2fs", len(texts), _time.time() - t0)
        return vectors[0] if single else vectors


def _embed_api(texts, single):
    """远程 API embedding (OpenAI 兼容)。"""
    try:
        import model_gateway_bridge as gateway_bridge
    except ImportError:
        from remote_terminal import model_gateway_bridge as gateway_bridge
    all_vectors = []
    bs = _EMBED_BATCH
    for i in range(0, len(texts), bs):
        batch = texts[i : i + bs]
        all_vectors.extend(
            gateway_bridge.invoke_embeddings(
                batch,
                endpoint=_EMBED_API_URL,
                api_key=_EMBED_API_KEY,
                model=_EMBED_API_MODEL,
                timeout_s=30,
            )
        )

    return all_vectors[0] if single else all_vectors


def embed_query(text: str):
    """单条查询 embedding。"""
    return embed([text])[0]


def embed_documents(texts: list[str]):
    """批量文档 embedding。"""
    return embed(texts)
