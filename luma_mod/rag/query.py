from __future__ import annotations
import os
import json
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Iterable

try:
    import faiss  # type: ignore
    HAVE_FAISS = True
except Exception:
    faiss = None  # type: ignore
    HAVE_FAISS = False

import numpy as np  # type: ignore
try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    HAVE_ST = True
except Exception:
    SentenceTransformer = None  # type: ignore
    HAVE_ST = False

from .indexer import RAG_HOME, FAISS_PATH, META_PATH, read_meta_lines


def _lazy_index():
    if not HAVE_FAISS:
        return None
    if not os.path.isfile(FAISS_PATH):
        return None
    try:
        return faiss.read_index(FAISS_PATH)
    except Exception:
        return None


def _lazy_model():
    if not HAVE_ST:
        return None
    return SentenceTransformer("all-MiniLM-L6-v2")


def _normalize(X: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    return X / norms


def _prefilter_meta(items: Iterable[Dict[str, object]], folder: Optional[str], time_from: Optional[str], time_to: Optional[str], prefilter_paths: Optional[List[str]]) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    pf_set = set(prefilter_paths or [])
    t_from = datetime.fromisoformat(time_from) if time_from else None
    t_to = datetime.fromisoformat(time_to) if time_to else None
    for obj in items:
        if obj.get("deleted"):
            continue
        if folder and obj.get("folder") != folder:
            continue
        if pf_set and all(not str(obj.get("path", "")).startswith(p) for p in pf_set):
            continue
        try:
            mt = datetime.fromisoformat(str(obj.get("mtime_iso")))
            if t_from and mt < t_from:
                continue
            if t_to and mt > t_to:
                continue
        except Exception:
            pass
        out.append(obj)
    return out


def search(query: str, k: int = 20, folder: Optional[str] = None, time_from: Optional[str] = None, time_to: Optional[str] = None, prefilter_paths: Optional[List[str]] = None) -> List[Tuple[float, Dict[str, object]]]:
    index = _lazy_index()
    if index is None or index.ntotal == 0:
        return []
    model = _lazy_model()
    if model is None:
        return []
    qv = model.encode([query], convert_to_numpy=True)
    qv = _normalize(qv.astype("float32"))

    # We need to map meta row order to FAISS vector order: meta.jsonl is append-only aligned with index addition order.
    metas_all = list(read_meta_lines())
    metas = list(_prefilter_meta(metas_all, folder, time_from, time_to, prefilter_paths))
    # If prefilter wiped everything but we do have data, back off to local-folder heuristic using the query terms
    if not metas and prefilter_paths:
        metas = list(_prefilter_meta(metas_all, folder, time_from, time_to, None))
    if not metas:
        return []

    # FAISS search over all vectors, then filter to top-k of metas via scores join.
    D, I = index.search(qv, min(k * 5, max(50, k * 3)))  # wider search then filter
    candidates: List[Tuple[int, float]] = []
    seen_ids: set[int] = set()
    for idx, score in zip(I[0].tolist(), D[0].tolist()):
        if idx in seen_ids:
            continue
        seen_ids.add(idx)
        # Guard index range
        if idx < 0:
            continue
        candidates.append((idx, float(score)))

    # Join with metas by vector id (stored under 'id') and filter deleted
    meta_by_id = {int(m.get("id")): m for m in metas}
    hits: List[Tuple[float, Dict[str, object]]] = []
    for idx, score in candidates:
        m = meta_by_id.get(idx)
        if not m:
            continue
        hits.append((float(score), m))

    hits.sort(key=lambda x: x[0], reverse=True)
    return hits[:k]


def build_prompt(query: str, hits: List[Tuple[float, Dict[str, object]]], n_ctx: int = 12) -> Tuple[str, str]:
    """Build a bounded context prompt from top hits.

    Returns (system_message, user_message). If no sufficient hits, the caller can handle low-confidence.
    """
    snippets: List[str] = []
    for i, (score, m) in enumerate(hits[:n_ctx], start=1):
        path = str(m.get("path"))
        page = m.get("page")
        tag = f"{path}:p{page}" if page else path
        text = str(m.get("text", ""))
        text = text.strip().replace("\n\n", "\n")
        snippets.append(f"[{i}] {tag}\n{text}")
    user_msg = (
        f"Question: {query}\n\n"
        + "\n---\n".join(snippets)
    )
    system_msg = (
        "Answer ONLY from the provided snippets. Cite sources like [1], [2] inline. "
        "If the answer is not found in the snippets, say: 'Not enough info from the provided files.'"
    )
    return system_msg, user_msg


