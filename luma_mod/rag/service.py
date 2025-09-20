from __future__ import annotations
import argparse
import os
import sys
from typing import List, Dict, Any, Tuple

from .indexer import RAGIndex
from .query import search as rag_search, build_prompt


_STATUS: Dict[str, Any] = {
    "watching": False,
    "folders": [],
    "chunks": 0,
    "last_update": None,
}


def ensure_index_started(
    folders: List[str],
    exclude: List[str] | None = None,
    replace: bool = False,
    progress_cb: "callable | None" = None,
) -> None:
    """Build/refresh the index.

    - folders: roots to index (recursive)
    - exclude: names to skip
    - replace: if True, clear existing FAISS/meta before indexing so only these folders are included
    """
    idx = RAGIndex()
    if replace:
        # Hard reset: remove existing index and meta
        try:
            import os
            from .indexer import FAISS_PATH, META_PATH
            if os.path.exists(FAISS_PATH):
                os.remove(FAISS_PATH)
            if os.path.exists(META_PATH):
                os.remove(META_PATH)
            # Recreate empty index lazily on first add
        except Exception:
            pass
    try:
        res = idx.index_folders(folders, excludes=exclude, progress_cb=progress_cb)
    except TypeError:
        # Backward compatibility if indexer signature differs
        res = idx.index_folders(folders, excludes=exclude)
    _STATUS["folders"] = folders
    _STATUS["chunks"] = idx.size
    _STATUS["last_update"] = res


def get_status() -> Dict[str, Any]:
    return dict(_STATUS)


def _call_model(system_msg: str, user_msg: str) -> str:
    # Prefer local/Ollama if available via ai.py, but keep this minimal
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI()
        prompt = f"{system_msg}\n\n{user_msg}"
        resp = client.responses.create(
            model="gpt-5-nano",
            input=prompt,
            text={"verbosity": "low"}
        )
        return (getattr(resp, "output_text", None) or "").strip()
    except Exception:
        # If offline/unavailable
        return "Not enough info from the provided files."


def rag_answer(query: str, n_ctx: int = 12) -> Dict[str, Any]:
    try:
        hits = rag_search(query, k=max(20, n_ctx * 2))
    except Exception:
        hits = []
    low_conf = True
    if hits:
        max_score = max(s for s, _ in hits)
        low_conf = (max_score < 0.2) or (len(hits) < 3)
    if not hits:
        return {"answer": "Not enough info from the provided files.", "hits": [], "low_confidence": True}
    system_msg, user_msg = build_prompt(query, hits, n_ctx=n_ctx)
    answer = _call_model(system_msg, user_msg)
    return {"answer": answer, "hits": hits[:n_ctx], "low_confidence": low_conf}


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser("Luma RAG Service")
    p.add_argument("--init", action="store_true", help="Build initial index")
    p.add_argument("--folders", nargs="*", default=[], help="Folders to index")
    p.add_argument("--watch", action="store_true", help="Start watcher (background)")
    p.add_argument("--status", action="store_true", help="Print status")
    args = p.parse_args(argv)

    if args.init:
        ensure_index_started(args.folders or [os.path.expanduser("~/Documents")], exclude=["node_modules", "__pycache__", ".git"])
        print("Initialized index.")
    if args.watch:
        # Minimal: indexing already updates; a full watch loop would be added if needed
        print("Watcher is not implemented as a blocking CLI loop in this minimal service.")
    if args.status:
        print(get_status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


