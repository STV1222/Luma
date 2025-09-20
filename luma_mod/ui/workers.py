from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..ai import LumaAI
from ..search_core import search_files
from ..models import FileHit


class SearchWorker(QThread):
    results_ready = pyqtSignal(list)

    def __init__(
        self,
        folders: List[str],
        keywords: List[str],
        allow_exts: List[str],
        time_range,
        time_attr: str = "mtime",
        semantic_keywords: Optional[List[str]] = None,
        file_patterns: Optional[List[str]] = None,
    ):
        super().__init__()
        self.folders = folders
        self.keywords = keywords
        self.allow_exts = allow_exts
        self.time_range = time_range
        self.time_attr = time_attr
        self.semantic_keywords = semantic_keywords or []
        self.file_patterns = file_patterns or []

    def run(self):
        hits: List[FileHit] = []
        for path, score in search_files(
            self.folders,
            self.keywords,
            self.allow_exts,
            self.time_range,
            self.time_attr,
            self.semantic_keywords,
            self.file_patterns,
        ):
            try:
                from os import stat

                st = stat(path)
                hits.append(FileHit(path, int(score), st.st_mtime, st.st_size))
            except Exception:
                continue
        self.results_ready.emit(hits)


class AIWorker(QThread):
    info_ready = pyqtSignal(dict)

    def __init__(self, ai: LumaAI, query: str, use_ai: bool):
        super().__init__()
        self.ai = ai
        self.query = query
        self.use_ai = use_ai

    def run(self):
        try:
            info = self.ai.parse_query_ai(self.query) if self.use_ai else self.ai.parse_query_nonai(self.query)
        except Exception:
            info = self.ai.parse_query_nonai(self.query)
        self.info_ready.emit(info)


class RerankWorker(QThread):
    reranked = pyqtSignal(list)

    def __init__(
        self,
        ai: LumaAI,
        query: str,
        hits: List[FileHit],
        time_window=None,
        file_types=None,
        folders=None,
    ):
        super().__init__()
        self.ai = ai
        self.query = query
        self.hits = hits
        self.time_window = time_window
        self.file_types = file_types
        self.folders = folders

    def run(self):
        try:
            paths = [h.path for h in self.hits][:30]
            scores = self.ai.rerank_by_name(self.query, paths, self.time_window, self.file_types, self.folders) or {}
            if not scores:
                self.reranked.emit(self.hits)
                return

            def boosted(h: FileHit) -> FileHit:
                extra = float(scores.get(h.path, 0.0))
                return FileHit(h.path, h.score + int(extra), h.mtime, h.size)

            new_hits = sorted([boosted(h) for h in self.hits], key=lambda x: x.score, reverse=True)
            self.reranked.emit(new_hits)
        except Exception:
            self.reranked.emit(self.hits)


class SummarizeWorker(QThread):
    summary_ready = pyqtSignal(str)
    summary_failed = pyqtSignal(str)

    def __init__(self, ai: LumaAI, path: str, use_ai: bool):
        super().__init__()
        self.ai = ai
        self.path = path
        self.use_ai = use_ai

    def run(self):
        try:
            if self.use_ai:
                s = self.ai.summarize_file(self.path)
                if s:
                    self.summary_ready.emit(s)
                else:
                    self.summary_failed.emit("Summary unavailable. Check AI mode and dependencies.")
            else:
                s = self.ai.summarize_file_extractive(self.path)
                if s:
                    self.summary_ready.emit(s)
                else:
                    self.summary_failed.emit("Summary unavailable (no text).")
        except Exception as e:
            self.summary_failed.emit(f"Summary failed: {str(e)}")


class QnAWorker(QThread):
    answer_ready = pyqtSignal(str)

    def __init__(self, ai: LumaAI, path: str, question: str):
        super().__init__()
        self.ai = ai
        self.path = path
        self.question = question

    def run(self):
        try:
            a = self.ai.answer_about_file(self.path, self.question) or "I am not sure based on the file content."
        except Exception:
            a = "Question failed."
        self.answer_ready.emit(a)


class WarmupWorker(QThread):
    def __init__(self, ai: LumaAI):
        super().__init__()
        self.ai = ai

    def run(self):
        try:
            self.ai.warmup()
        except Exception:
            pass



class IndexWorker(QThread):
    progress = pyqtSignal(int, int, str)  # processed, total, current_path
    finished_with_result = pyqtSignal(dict)

    def __init__(self, folders: List[str], exclude: Optional[List[str]] = None, replace: bool = False):
        super().__init__()
        self.folders = folders
        self.exclude = exclude or []
        self.replace = replace

    def run(self):
        try:
            # Lazy imports to avoid heavy deps on UI thread
            from luma_mod.rag.indexer import RAGIndex, FAISS_PATH, META_PATH
            import os as _os

            if self.replace:
                try:
                    if _os.path.exists(FAISS_PATH):
                        _os.remove(FAISS_PATH)
                    if _os.path.exists(META_PATH):
                        _os.remove(META_PATH)
                except Exception:
                    pass

            idx = RAGIndex()

            def _cb(processed: int, total: int, current_path: str):
                try:
                    self.progress.emit(processed, total, current_path)
                except Exception:
                    pass

            res = idx.index_folders(self.folders, excludes=self.exclude, progress_cb=_cb)
        except Exception:
            res = {"added": 0, "deleted": 0}
        self.finished_with_result.emit(res)

