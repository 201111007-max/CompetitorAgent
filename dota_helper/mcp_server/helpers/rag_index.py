"""TF-IDF / FAISS RAG 索引 — 英雄知识检索

从 dota2_fastmcp.py 提取的 RAG 向量检索功能，支持本地 heroes_txt 知识库。
"""

import math
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

# 资源目录
RESOURCES_DIR = Path(__file__).parent.parent / "resources"
HEROES_TXT_DIR = RESOURCES_DIR / "heroes_txt"


def normalize_text(text: str) -> str:
    """归一化文本：小写、去标点、去多余空格

    Args:
        text: 原始文本

    Returns:
        str: 归一化后的文本
    """
    if not text:
        return ""
    text = text.lower()
    text = text.replace("_", " ").replace("-", " ").replace("'", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text: str) -> List[str]:
    """中英文混合分词

    Args:
        text: 原始文本

    Returns:
        List[str]: 词元列表
    """
    if not text:
        return []
    text = normalize_text(text)
    tokens: List[str] = re.findall(r"[a-z0-9]+", text)
    tokens.extend(re.findall(r"[\u4e00-\u9fff]", text))
    return tokens


def build_tfidf_vector(tokens: List[str], idf: Dict[str, float]) -> Dict[str, float]:
    """构建稀疏 TF-IDF 向量

    Args:
        tokens: 词元列表
        idf: IDF 字典

    Returns:
        Dict[str, float]: 词元到 TF-IDF 权重的映射
    """
    if not tokens or not idf:
        return {}
    tf: Dict[str, int] = {}
    for tok in tokens:
        tf[tok] = tf.get(tok, 0) + 1
    vector: Dict[str, float] = {}
    for tok, count in tf.items():
        weight = idf.get(tok)
        if weight is None:
            continue
        vector[tok] = (1.0 + math.log(count)) * weight
    return vector


def build_tfidf_dense(
    tokens: List[str],
    vocab: Dict[str, int],
    idf: Dict[str, float],
    dim: int,
) -> np.ndarray:
    """构建稠密 TF-IDF 向量（用于 FAISS 检索）

    Args:
        tokens: 词元列表
        vocab: 词表（词元到索引的映射）
        idf: IDF 字典
        dim: 向量维度

    Returns:
        np.ndarray: 稠密 TF-IDF 向量
    """
    if not tokens or not vocab or dim <= 0:
        return np.zeros(dim, dtype=np.float32)
    tf: Dict[str, int] = {}
    for tok in tokens:
        tf[tok] = tf.get(tok, 0) + 1
    vector = np.zeros(dim, dtype=np.float32)
    for tok, count in tf.items():
        idx = vocab.get(tok)
        if idx is None:
            continue
        weight = idf.get(tok)
        if weight is None:
            continue
        vector[idx] = (1.0 + math.log(count)) * float(weight)
    return vector


def cosine_similarity(
    vector_a: Dict[str, float],
    norm_a: float,
    vector_b: Dict[str, float],
    norm_b: float,
) -> float:
    """计算两个稀疏向量的余弦相似度

    Args:
        vector_a: 向量 A
        norm_a: 向量 A 的范数
        vector_b: 向量 B
        norm_b: 向量 B 的范数

    Returns:
        float: 余弦相似度
    """
    if not vector_a or not vector_b:
        return 0.0
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    if len(vector_a) > len(vector_b):
        vector_a, vector_b = vector_b, vector_a
    dot = 0.0
    for tok, val in vector_a.items():
        other = vector_b.get(tok)
        if other is not None:
            dot += val * other
    return dot / (norm_a * norm_b)


def parse_hero_names_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """从英雄文本中解析英文名和中文名

    Args:
        text: 英雄介绍文本

    Returns:
        Tuple[en_name, cn_name]
    """
    if not text:
        return None, None
    first_line = text.strip().splitlines()[0].strip()
    match = re.search(r"英雄名称[:：]\s*([A-Za-z0-9' \-]+?)\s+([\u4e00-\u9fff]+)", first_line)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.search(r"英雄名称[:：]\s*([^\n]+)", text)
    if match:
        parts = match.group(1).strip().split()
        if len(parts) >= 2:
            return " ".join(parts[:-1]).strip(), parts[-1].strip()
    return None, None


# ── 模块级缓存 ──

_hero_documents_cache: Optional[List[Dict[str, Any]]] = None
_hero_vector_index_cache: Optional[Dict[str, Any]] = None


def _reset_cache() -> None:
    """重置模块级缓存（用于测试）"""
    global _hero_documents_cache, _hero_vector_index_cache
    _hero_documents_cache = None
    _hero_vector_index_cache = None


def load_hero_documents() -> List[Dict[str, Any]]:
    """加载英雄文本知识库

    Returns:
        List[Dict[str, Any]]: 英雄文档列表
    """
    global _hero_documents_cache
    if _hero_documents_cache is not None:
        return _hero_documents_cache

    # 延迟导入，避免循环依赖
    from .hero_names import get_cn_name

    heroes_dir = str(HEROES_TXT_DIR)
    if not os.path.isdir(heroes_dir):
        _hero_documents_cache = []
        return []

    docs: List[Dict[str, Any]] = []
    for filename in sorted(os.listdir(heroes_dir)):
        if not filename.endswith(".txt"):
            continue
        path = os.path.join(heroes_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        name_en, name_cn = parse_hero_names_from_text(content)
        if not name_en:
            name_en = os.path.splitext(filename)[0].replace("_", " ")
        if not name_cn and name_en:
            name_cn = get_cn_name(name_en)
        name_keys: set = set()
        for candidate in (name_en, name_cn, os.path.splitext(filename)[0], filename.replace(".txt", "")):
            if candidate:
                name_keys.add(normalize_text(str(candidate)))
        name_token_list = tokenize(f"{name_en or ''} {name_cn or ''}")
        content_token_list = tokenize(content)
        name_tokens = set(name_token_list)
        content_tokens = set(content_token_list)
        all_token_list = name_token_list + content_token_list
        docs.append({
            "name_en": name_en or "",
            "name_cn": name_cn or "",
            "path": path,
            "content": content,
            "name_keys": name_keys,
            "name_tokens": name_tokens,
            "content_tokens": content_tokens,
            "name_token_list": name_token_list,
            "content_token_list": content_token_list,
            "all_token_list": all_token_list,
        })
    _hero_documents_cache = docs
    return docs


def load_hero_vector_index() -> Dict[str, Any]:
    """构建英雄文档的 TF-IDF/FAISS 向量索引

    Returns:
        Dict[str, Any]: 索引对象，包含 docs, idf, vocab, doc_vectors, faiss_index, dim
    """
    global _hero_vector_index_cache
    if _hero_vector_index_cache is not None:
        return _hero_vector_index_cache

    docs = load_hero_documents()
    if not docs:
        result = {
            "docs": [],
            "idf": {},
            "vocab": {},
            "doc_vectors": None,
            "faiss_index": None,
            "dim": 0,
        }
        _hero_vector_index_cache = result
        return result

    doc_count = len(docs)
    df: Dict[str, int] = {}
    for doc in docs:
        for tok in set(doc.get("all_token_list") or []):
            df[tok] = df.get(tok, 0) + 1
    idf = {
        tok: (math.log((doc_count + 1) / (count + 1)) + 1.0)
        for tok, count in df.items()
    }

    vocab_tokens = sorted(idf.keys())
    vocab = {tok: idx for idx, tok in enumerate(vocab_tokens)}
    dim = len(vocab_tokens)
    doc_vectors = np.zeros((doc_count, dim), dtype=np.float32) if dim > 0 else None

    for i, doc in enumerate(docs):
        vector = build_tfidf_dense(doc.get("all_token_list") or [], vocab, idf, dim)
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        if doc_vectors is not None:
            doc_vectors[i] = vector
        doc["vector"] = vector

    faiss_index = None
    if HAS_FAISS and doc_vectors is not None and dim > 0:
        faiss_index = faiss.IndexFlatIP(dim)
        faiss_index.add(doc_vectors)

    result = {
        "docs": docs,
        "idf": idf,
        "vocab": vocab,
        "doc_vectors": doc_vectors,
        "faiss_index": faiss_index,
        "dim": dim,
    }
    _hero_vector_index_cache = result
    return result


def rank_hero_documents(query: str, top_k: int) -> List[Dict[str, Any]]:
    """检索与查询最相关的英雄文档

    Args:
        query: 查询文本
        top_k: 返回数量

    Returns:
        List[Dict[str, Any]]: 排序后的检索结果
    """
    index = load_hero_vector_index()
    docs = index.get("docs") or []
    idf = index.get("idf") or {}
    vocab = index.get("vocab") or {}
    doc_vectors = index.get("doc_vectors")
    faiss_index = index.get("faiss_index")
    dim = int(index.get("dim") or 0)
    if not docs:
        return []
    query_norm = normalize_text(query)
    query_tokens = tokenize(query)
    query_vector = build_tfidf_dense(query_tokens, vocab, idf, dim)
    query_norm_value = float(np.linalg.norm(query_vector)) if dim > 0 else 0.0
    if query_norm_value > 0:
        query_vector = query_vector / query_norm_value

    vector_scores: Dict[int, float] = {}
    if faiss_index is not None and query_norm_value > 0:
        vector_k = max(10, top_k * 5)
        vector_k = min(len(docs), vector_k)
        distances, indices = faiss_index.search(
            query_vector.reshape(1, -1).astype(np.float32),
            vector_k,
        )
        for idx, score in zip(indices[0], distances[0]):
            if idx < 0:
                continue
            vector_scores[int(idx)] = float(score)

    keyword_candidates: Dict[int, int] = {}
    for idx, doc in enumerate(docs):
        name_score = 0
        content_score = 0
        if query_norm:
            for key in doc["name_keys"]:
                if not key:
                    continue
                if query_norm == key:
                    name_score += 200
                elif query_norm in key or key in query_norm:
                    name_score += 120
        if doc["name_cn"] and doc["name_cn"] in query:
            name_score += 200
        if doc["name_en"] and normalize_text(doc["name_en"]) in query_norm:
            name_score += 120
        for token in query_tokens:
            if token in doc["name_tokens"]:
                name_score += 15
            elif token in doc["content_tokens"]:
                content_score += 1

        score = name_score + content_score
        if name_score > 0 or content_score >= 4:
            keyword_candidates[idx] = score

    candidate_ids = set(keyword_candidates.keys()) | set(vector_scores.keys())

    if not candidate_ids and query_norm and docs:
        for idx, doc in enumerate(docs):
            best_ratio = 0.0
            for key in doc["name_keys"]:
                if not key:
                    continue
                best_ratio = max(best_ratio, SequenceMatcher(None, query_norm, key).ratio())
            if best_ratio >= 0.5:
                keyword_candidates[idx] = int(best_ratio * 100)
        candidate_ids = set(keyword_candidates.keys())

    if not candidate_ids:
        return []

    scored: List[Dict[str, Any]] = []
    for idx in candidate_ids:
        doc = docs[idx]
        keyword_score = keyword_candidates.get(idx, 0)
        vector_score = vector_scores.get(idx, 0.0)
        if vector_score == 0.0 and query_norm_value > 0 and doc_vectors is not None:
            vector_score = float(np.dot(query_vector, doc_vectors[idx]))
        scored.append({
            "doc": doc,
            "keyword_score": keyword_score,
            "vector_score": vector_score,
        })

    max_kw = max(item["keyword_score"] for item in scored) if scored else 0
    max_vec = max(item["vector_score"] for item in scored) if scored else 0.0
    kw_weight = 0.7
    vec_weight = 0.3
    for item in scored:
        kw_norm = (item["keyword_score"] / max_kw) if max_kw > 0 else 0.0
        vec_norm = (item["vector_score"] / max_vec) if max_vec > 0 else 0.0
        item["kw_norm"] = kw_norm
        item["vec_norm"] = vec_norm
        item["hybrid_score"] = kw_weight * kw_norm + vec_weight * vec_norm

    scored.sort(key=lambda item: item["hybrid_score"], reverse=True)
    if top_k <= 0:
        top_k = 1
    return scored[:min(top_k, len(scored))]


def format_hero_rag_output(
    query: str,
    results: List[Dict[str, Any]],
    max_chars: int,
) -> str:
    """格式化 RAG 检索结果输出

    Args:
        query: 查询文本
        results: 检索结果列表
        max_chars: 每条结果最大字符数

    Returns:
        str: 格式化的输出文本
    """
    lines: List[str] = ["# RAG 英雄介绍检索结果", f"query: {query}", ""]
    for idx, item in enumerate(results, 1):
        doc = item["doc"]
        hybrid_score = item.get("hybrid_score", 0.0)
        kw_norm = item.get("kw_norm", 0.0)
        vec_norm = item.get("vec_norm", 0.0)
        name_en = doc.get("name_en") or "Unknown"
        name_cn = doc.get("name_cn") or ""
        display_name = f"{name_cn} ({name_en})" if name_cn else name_en
        path = doc.get("path", "")
        source_rel = os.path.relpath(path, str(RESOURCES_DIR.parent)).replace("\\", "/") if path else ""
        lines.append(f"## Top {idx}: {display_name}")
        lines.append(f"score: {hybrid_score:.3f} (kw={kw_norm:.3f}, vec={vec_norm:.3f})")
        lines.append(f"source: {source_rel}")
        lines.append("")
        content = doc.get("content", "").strip()
        if max_chars and max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars].rstrip() + "\n...[truncated]"
        lines.append(content)
        lines.append("")
    return "\n".join(lines).strip()
