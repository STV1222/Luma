from __future__ import annotations
import os
import threading
import time
from typing import List, Optional

from watchdog.observers import Observer  # type: ignore
from watchdog.events import FileSystemEventHandler  # type: ignore

from .indexer import RAGIndex, SUPPORTED_EXTS


EXCLUDES = {"node_modules", "__pycache__", ".git"}
EXCLUDE_SUFFIXES = {".log", ".tmp", ".run"}


def _is_ignored(path: str) -> bool:
    name = os.path.basename(path)
    if name.startswith('.'):
        return True
    if any(seg in EXCLUDES for seg in path.split(os.sep)):
        return True
    if any(path.endswith(suf) for suf in EXCLUDE_SUFFIXES):
        return True
    return False


class _Handler(FileSystemEventHandler):
    def __init__(self, index: RAGIndex) -> None:
        self.index = index
        self._last: dict[str, float] = {}

    def _throttle(self, path: str, delay: float = 1.0) -> bool:
        now = time.time()
        last = self._last.get(path, 0.0)
        if now - last < delay:
            return True
        self._last[path] = now
        return False

    def on_created(self, event):  # type: ignore[no-redef]
        if event.is_directory:
            return
        path = event.src_path
        if _is_ignored(path):
            return
        if self._throttle(path):
            return
        self.index.index_file(path)

    def on_modified(self, event):  # type: ignore[no-redef]
        if event.is_directory:
            return
        path = event.src_path
        if _is_ignored(path):
            return
        if self._throttle(path):
            return
        self.index.index_file(path)

    def on_moved(self, event):  # type: ignore[no-redef]
        if event.is_directory:
            return
        # Soft-delete old, reindex new if supported
        old = event.src_path
        new = event.dest_path
        if not _is_ignored(old):
            self.index.index_file(old)  # index_file will soft-delete previous entries for same path
        if not _is_ignored(new):
            self.index.index_file(new)

    def on_deleted(self, event):  # type: ignore[no-redef]
        if event.is_directory:
            return
        # Soft-delete by indexing zero (indexer handles soft-delete by path)
        self.index.index_file(event.src_path)


class WatchService:
    def __init__(self, folders: List[str]) -> None:
        self.folders = folders
        self.index = RAGIndex()
        self.observer = Observer()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        handler = _Handler(self.index)
        for f in self.folders:
            if os.path.isdir(f):
                self.observer.schedule(handler, f, recursive=True)
        self.observer.start()

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join(timeout=2.0)


