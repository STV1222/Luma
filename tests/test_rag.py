from __future__ import annotations
import os
import tempfile

from luma_mod.rag.indexer import iter_sliding_windows, RAGIndex
from luma_mod.rag.query import build_prompt


def test_iter_sliding_windows_basic():
    text = "para1\n\npara2\n\npara3"
    chunks = list(iter_sliding_windows(text, max_chars=10, overlap=2))
    assert len(chunks) >= 1


def test_build_prompt_shapes():
    hits = [
        (0.9, {"path": "/a.txt", "page": None, "text": "hello world"}),
        (0.8, {"path": "/b.pdf", "page": 3, "text": "lorem ipsum"}),
    ]
    sys, usr = build_prompt("question?", hits, n_ctx=2)
    assert "Answer ONLY" in sys
    assert "[1]" in usr and "[2]" in usr


