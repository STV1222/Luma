#!/usr/bin/env python3
"""
Luma – Desktop Spotlight-style UI for your file search engine (PyQt6)
--------------------------------------------------------------------
Updates in this version:
- Robust date parsing: supports "9 Sep 2025", "September 9 2025", "2025-09-09",
  and AI JSON shapes like {"date": "..."} / {"from": "...", "to": "..."}.
- Understands intent: "edited/modified/updated" ⇒ filter by mtime;
  "created/added/new" ⇒ filter by creation time (macOS st_birthtime, else ctime).
- Search worker passes chosen time attribute to the search engine.

Install deps:
    pip install PyQt6 rapidfuzz Pillow pdf2image
Also install poppler for PDF previews:
    # macOS (Homebrew)
    brew install poppler
Run:
    python luma_spotlight.py
"""

from __future__ import annotations
import os, sys, re, time, subprocess, platform, threading, math, json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path

# LangChain (optional AI parsing/ranking)
try:
    from langchain.llms import Ollama
    from langchain.callbacks.manager import CallbackManager
    from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
    HAVE_OLLAMA = True
except Exception:
    HAVE_OLLAMA = False

# ----------------------------- UI IMPORTS ------------------------------------
from PyQt6.QtCore import Qt, QAbstractListModel, QModelIndex, QSize, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QPixmap, QImage  # QAction must be from QtGui in PyQt6
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLineEdit, QListView, QVBoxLayout, QHBoxLayout,
    QLabel, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QFrame,
    QComboBox, QSplitter, QFileIconProvider, QMenu, QMessageBox, QPushButton,
    QScrollArea, QListWidget, QListWidgetItem
)

# Optional imaging libs
try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

try:
    from pdf2image import convert_from_path
    HAVE_PDF = True
except Exception:
    HAVE_PDF = False
    print("Warning: pdf2image not found. Install with: pip install pdf2image")
    print("Note: You also need poppler installed: brew install poppler (macOS)")

try:
    from rapidfuzz import fuzz
    HAVE_RAPIDFUZZ = True
except Exception:
    HAVE_RAPIDFUZZ = False


# ============================ AI ASSISTANT ===================================

def normalize_time_range(maybe):
    """Accept many shapes (string/dict/list) and return (tmin, tmax) or None."""
    if maybe is None:
        return None
    try:
        if isinstance(maybe, str):
            t = extract_time_window(maybe)
            return None if t == (None, None) else t
        if isinstance(maybe, dict):
            # {"date": "2025-09-09"} or {"on": "9 Sep 2025"}
            for key in ("date", "on", "day", "when"):
                if isinstance(maybe.get(key), str):
                    t = extract_time_window(maybe[key])
                    return None if t == (None, None) else t
            # {"from": "...", "to": "..."}
            if isinstance(maybe.get("from"), str) and isinstance(maybe.get("to"), str):
                t1 = extract_time_window(maybe["from"]) or (None, None)
                t2 = extract_time_window(maybe["to"]) or (None, None)
                if t1 != (None, None) and t2 != (None, None):
                    return (min(t1[0], t2[0]), max(t1[1], t2[1]))
        if isinstance(maybe, list) and maybe and isinstance(maybe[0], str):
            t = extract_time_window(maybe[0])
            return None if t == (None, None) else t
    except Exception:
        pass
    return None


def detect_time_attr(query: str) -> str:
    """edited/updated/modified → 'mtime'; created/added/new → 'birthtime' (or ctime)."""
    q = query.lower()
    if any(w in q for w in ["create", "created", "added", "made", "new file"]):
        return "birthtime"
    return "mtime"


class LumaAI:
    """Ollama-powered AI assistant for Luma (optional)."""

    def __init__(self):
        self.model = None
        self.initialized = False

    def ensure_initialized(self):
        if not HAVE_OLLAMA:
            return False
        if not self.initialized:
            try:
                self.model = Ollama(
                    model="mistral",
                    callback_manager=CallbackManager([StreamingStdOutCallbackHandler()]),
                )
                self.initialized = True
            except Exception as e:
                print(f"Warning: Could not initialize Ollama: {e}")
                return False
        return True

    def parse_query(self, query: str) -> Dict[str, Any]:
        """
        Parse NL query. Returns:
          { keywords:[], time_range: Optional[(tmin,tmax)], file_types:[],
            time_attr: 'mtime' | 'birthtime' }
        """
        time_attr = detect_time_attr(query)

        if not self.ensure_initialized():
            time_range = extract_time_window(query)
            keywords = [kw for kw in extract_keywords(query)
                        if not any(m in kw.lower() for m in ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'])
                        and not kw.isdigit()]
            return {
                "keywords": keywords,
                "time_range": None if time_range == (None, None) else time_range,
                "file_types": [],
                "time_attr": time_attr,
            }

        system_prompt = (
            "You are a file search assistant. Analyze the query and extract:\n"
            "1) keywords (no filler)\n"
            "2) a specific date or date range of interest\n"
            "3) file types/extensions (e.g., pdf, ppt)\n"
            "4) whether the user meant 'edited' or 'created'\n"
            "Respond as compact JSON: "
            "{keywords:[], time_range: <string|{...}|[...]>, file_types:[], action:'edited|created'}"
        )

        try:
            response = self.model.invoke(f"{system_prompt}\nQuery: {query}\nResponse:")
            json_str = response.strip()
            if not json_str.startswith("{"):
                json_str = json_str[json_str.find("{"):]
            if not json_str.endswith("}"):
                json_str = json_str[:json_str.rfind("}") + 1]
            parsed = json.loads(json_str)

            act = (parsed.get("action") or "").lower()
            if act.startswith("creat"):
                time_attr = "birthtime"
            elif act:
                time_attr = "mtime"

            tr = normalize_time_range(parsed.get("time_range"))
            return {
                "keywords": parsed.get("keywords", []),
                "time_range": tr,
                "file_types": parsed.get("file_types", []),
                "time_attr": time_attr,
            }
        except Exception as e:
            print(f"AI parsing failed: {e}, falling back to traditional parsing")
            time_range = extract_time_window(query)
            return {
                "keywords": extract_keywords(query),
                "time_range": None if time_range == (None, None) else time_range,
                "file_types": [],
                "time_attr": time_attr,
            }

    def enhance_results(self, query: str, results: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
        """Re-rank top results using AI. No-op if Ollama unavailable."""
        if not self.ensure_initialized():
            return results
        try:
            paths = [path for path, _ in results[:10]]
            prompt = f"""Rate how relevant these files are to the query: "{query}"
Files:
{chr(10).join(paths)}

Rate each file 0-100 as JSON list like: [95,80,...]"""
            response = self.model.invoke(prompt)
            scores_str = response[response.find("["):response.find("]") + 1]
            ai_scores = json.loads(scores_str)
            enhanced = []
            for i, (path, score) in enumerate(results):
                if i < len(ai_scores):
                    enhanced.append((path, score * 0.7 + float(ai_scores[i]) * 0.3))
                else:
                    enhanced.append((path, score))
            enhanced.sort(key=lambda x: x[1], reverse=True)
            return enhanced
        except Exception as e:
            print(f"AI enhancement failed: {e}, using original results")
            return results


# ============================ SEARCH SECTION =================================

DEFAULT_FOLDERS = [
    os.path.expanduser("~/Documents"),
    os.path.expanduser("~/Downloads"),
    os.path.expanduser("~/Desktop"),
]
IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
MAX_RESULTS = 50

FILETYPE_MAP = {
    "All": [],
    "Documents": [".pdf", ".doc", ".docx", ".ppt", ".pptx", ".key", ".txt", ".md", ".rtf"],
    "Images": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"],
    "Slides": [".ppt", ".pptx", ".key"],
    "PDF": [".pdf"],
    "Spreadsheets": [".xls", ".xlsx", ".csv"],
    "Code": [".py", ".js", ".ts", ".tsx", ".cpp", ".c", ".java", ".go", ".rb", ".rs", ".dart"],
}

REL_TIME_PATTERNS = [
    (r"\btoday\b", 0, 0),
    (r"\byesterday\b", 1, 1),
    (r"\blast\s+week\b", 7, 0),
    (r"\blast\s+month\b", 30, 0),
]

# Match "Sep 9 2025", "September 9 2025", "9 Sep 2025", "2025-09-09"
DATE_PATTERNS = [
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\s*,?\s*\d{4}\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*,?\s*\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b"
]
ABS_YEAR = re.compile(r"\b(20\d{2})\b")
EXT_PATTERN = re.compile(r"\b(\w+)\s*files?\b|\.(\w{1,6})\b", re.I)
STOPWORDS = {"find","show","get","open","the","a","an","me","my","files","file","of","for","about","last","this","that","these","those","recent","latest"}


def extract_time_window(q: str) -> Tuple[float, float] | Tuple[None, None]:
    ql = q.lower()
    now = datetime.now()

    # Specific dates first
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, q, re.IGNORECASE)
        if match:
            date_str = match.group(0)
            for fmt in ["%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d"]:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                    end = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                    return (start.timestamp(), end.timestamp())
                except ValueError:
                    continue

    # Relative patterns
    for pat, days_back, _ in REL_TIME_PATTERNS:
        if re.search(pat, ql):
            start = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
            return (start.timestamp(), end.timestamp())

    # Year-only
    m = ABS_YEAR.search(q)
    if m:
        year = int(m.group(1))
        start = datetime(year, 1, 1)
        end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        return (start.timestamp(), end.timestamp())

    return (None, None)


def extract_keywords(q: str) -> List[str]:
    quoted = re.findall(r'"([^"]+)"', q)
    q_wo_quotes = re.sub(r'"[^"]+"', " ", q)
    words = re.findall(r"[A-Za-z0-9_\-]+", q_wo_quotes)
    kws = [w for w in words if w.lower() not in STOPWORDS]
    return [*quoted, *kws]


def filename_score(name: str, keywords: List[str]) -> float:
    base = name.lower()
    if not keywords:
        return 50.0
    score = 0.0
    for kw in keywords:
        kwl = kw.lower()
        if kwl in base:
            score += 60
        elif HAVE_RAPIDFUZZ:
            score += fuzz.partial_ratio(kwl, base) * 0.6
        else:
            score += 20 if any(tok in base for tok in kwl.split()) else 0
    return score / max(1, len(keywords))


def recency_boost(mtime: float) -> float:
    age_days = max(0.0, (time.time() - mtime) / 86400.0)
    if age_days < 1: return 40
    if age_days < 7: return 25
    if age_days < 30: return 15
    if age_days < 180: return 8
    return 0


def search_files(
    folders: List[str],
    keywords: List[str],
    allow_exts: List[str],
    time_range: Optional[Tuple[float, float]],
    time_attr: str = "mtime",   # NEW: 'mtime' or 'birthtime'
) -> List[Tuple[str, float]]:
    if time_range is None:
        tmin, tmax = None, None
    else:
        tmin, tmax = time_range

    print(
        f"Searching for files between: "
        f"{datetime.fromtimestamp(tmin).strftime('%Y-%m-%d %H:%M:%S') if tmin else 'None'} and "
        f"{datetime.fromtimestamp(tmax).strftime('%Y-%m-%d %H:%M:%S') if tmax else 'None'} "
        f"using {time_attr}"
    )

    results: List[Tuple[str, float]] = []
    allow_exts_l = [e.lower() for e in allow_exts] if allow_exts else []

    for root in folders:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith('.')]
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                if allow_exts_l and os.path.splitext(fn)[1].lower() not in allow_exts_l:
                    continue
                try:
                    st = os.stat(path)
                    # Choose timestamp per intent
                    if time_attr == "birthtime" and hasattr(st, "st_birthtime"):
                        tstamp = getattr(st, "st_birthtime")
                    elif time_attr == "birthtime":
                        tstamp = st.st_ctime  # best-effort on non-macOS
                    else:
                        tstamp = st.st_mtime

                    # Date filtering
                    if tmin is not None and tmax is not None:
                        fdate = datetime.fromtimestamp(tstamp).date()
                        dmin = datetime.fromtimestamp(tmin).date()
                        dmax = datetime.fromtimestamp(tmax).date()
                        if fdate < dmin or fdate > dmax:
                            continue
                    elif tmin is not None and tstamp < tmin:
                        continue
                    elif tmax is not None and tstamp > tmax:
                        continue

                except Exception:
                    continue

                # Rank by filename relevance + recency of *mtime* (so recent edits still bubble)
                s = filename_score(fn, keywords) + recency_boost(st.st_mtime)
                if s > 0:
                    results.append((path, s))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:MAX_RESULTS]


# ============================ UI DATA MODEL ==================================

@dataclass
class FileHit:
    path: str
    score: int
    mtime: float
    size: int

class ResultsModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self._items: List[FileHit] = []
        self._icon_provider = QFileIconProvider()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self._items)

    def data(self, index: QModelIndex, role: int):  # type: ignore[override]
        if not index.isValid():
            return None
        hit = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return os.path.basename(hit.path)
        if role == Qt.ItemDataRole.ToolTipRole:
            dt = datetime.fromtimestamp(hit.mtime).strftime('%Y-%m-%d %H:%M')
            sz = human_size(hit.size)
            return f"{hit.path}\nModified: {dt}\nSize: {sz}\nScore: {hit.score}"
        if role == Qt.ItemDataRole.DecorationRole:
            return self._icon_provider.icon(QFileIconProvider.IconType.File)
        return None

    def set_items(self, items: List[FileHit]):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def item(self, row: int) -> Optional[FileHit]:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

class ResultDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # type: ignore[override]
        return QSize(option.rect.width(), 64)

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex):  # type: ignore[override]
        hit: FileHit = index.model().item(index.row())  # type: ignore
        if not hit:
            return super().paint(painter, option, index)

        painter.save()
        r = option.rect

        # icon
        icon: QIcon = index.data(Qt.ItemDataRole.DecorationRole)
        pix = icon.pixmap(32, 32)
        icon_y = r.top() + (r.height() - 32) // 2
        painter.drawPixmap(r.left() + 16, icon_y, pix)

        text_left = r.left() + 64

        # filename (bold)
        name = os.path.basename(hit.path)
        font = painter.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.white if option.state & QStyle.StateFlag.State_Selected else option.palette.windowText().color())
        painter.drawText(text_left, r.top() + 24, name)

        # metadata
        font.setPointSize(font.pointSize() - 2)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(Qt.GlobalColor.lightGray if option.state & QStyle.StateFlag.State_Selected else option.palette.mid().color())
        path_dir = elide_middle(os.path.dirname(hit.path), 60)
        dt = datetime.fromtimestamp(hit.mtime).strftime('%Y-%m-%d %H:%M')
        info = f"{path_dir}  •  {dt}  •  {human_size(hit.size)}"
        painter.drawText(text_left, r.top() + 44, info)

        painter.restore()


# ============================ SEARCH WORKER ==================================

class SearchWorker(QThread):
    results_ready = pyqtSignal(list)

    def __init__(self, folders: List[str], keywords: List[str], allow_exts: List[str],
                 time_range: Tuple[float,float] | Tuple[None,None], time_attr: str = "mtime"):
        super().__init__()
        self.folders = folders
        self.keywords = keywords
        self.allow_exts = allow_exts
        self.time_range = time_range
        self.time_attr = time_attr

    def run(self):
        print(f"Search worker starting with folders: {self.folders}")
        print(f"Search parameters: keywords={self.keywords}, extensions={self.allow_exts}, "
              f"time_range={self.time_range}, time_attr={self.time_attr}")
        hits = []
        for path, score in search_files(self.folders, self.keywords, self.allow_exts, self.time_range, self.time_attr):
            try:
                st = os.stat(path)
                hits.append(FileHit(path=path, score=int(score), mtime=st.st_mtime, size=st.st_size))
            except Exception:
                continue
        self.results_ready.emit(hits)


# =============================== MAIN UI =====================================

class SpotlightUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Luma")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(980, 580)
        self._folders = DEFAULT_FOLDERS[:]
        self._worker: Optional[SearchWorker] = None

        # Initialize AI assistant
        self.ai = LumaAI()

        wrapper = QFrame(); wrapper.setObjectName("wrapper"); wrapper.setFrameShape(QFrame.Shape.NoFrame)

        self.search = QLineEdit(); self.search.setPlaceholderText("Search files… (press Enter to search)")
        self.search.returnPressed.connect(self._perform_search)  # Search on Enter

        self.filter = QComboBox(); self.filter.addItems(list(FILETYPE_MAP.keys()))
        self.filter.currentIndexChanged.connect(self._perform_search)

        top = QHBoxLayout(); top.addWidget(self.search, 1); top.addWidget(self.filter, 0)

        self.model = ResultsModel(); self.list = QListView(); self.list.setModel(self.model)
        self.list.setItemDelegate(ResultDelegate()); self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.list.doubleClicked.connect(self._open_selected)
        self.list.selectionModel().selectionChanged.connect(self._update_preview)  # type: ignore

        self.preview = PreviewPane()

        split = QSplitter(); split.addWidget(self.list); split.addWidget(self.preview)
        split.setStretchFactor(0, 2); split.setStretchFactor(1, 1)

        lay = QVBoxLayout(wrapper); lay.addLayout(top); lay.addWidget(divider()); lay.addWidget(split, 1)
        outer = QVBoxLayout(self); outer.addWidget(wrapper)

        self._apply_style(); center_on_screen(self); self.show(); self.search.setFocus()

    # --------------------------- Search plumbing ----------------------------
    def _perform_search(self):
        q = self.search.text().strip()
        category = self.filter.currentText()
        allow_exts = FILETYPE_MAP.get(category, [])

        # Use AI to parse the query (or fallback)
        query_info = self.ai.parse_query(q)
        keywords = query_info["keywords"]
        time_range = query_info["time_range"]
        time_attr = query_info.get("time_attr", "mtime")

        # Apply AI-detected file types if no category filter chosen
        ai_exts = query_info.get("file_types", [])
        if ai_exts and not allow_exts:
            allow_exts.extend(['.' + ext.lstrip('.') for ext in ai_exts])

        print(f"Keywords: {keywords}, Time range: {time_range}, Final extensions: {allow_exts}, Time attr: {time_attr}")

        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.quit()
            self._worker.wait(50)

        self._worker = SearchWorker(self._folders, keywords, allow_exts, time_range, time_attr)
        self._worker.results_ready.connect(self._apply_hits)
        self._worker.start()

    def _apply_hits(self, hits: List[FileHit]):
        if not hits:
            self.model.set_items([])
            print("\nNo matching files found for your search criteria.")
            return

        # Adapt for AI re-ranking
        scored = [(hit.path, float(hit.score)) for hit in hits]
        enhanced = self.ai.enhance_results(self.search.text().strip(), scored)

        enhanced_hits: List[FileHit] = []
        for path, score in enhanced:
            try:
                st = os.stat(path)
                enhanced_hits.append(FileHit(
                    path=path,
                    score=int(score),
                    mtime=st.st_mtime,
                    size=st.st_size
                ))
            except Exception:
                continue

        enhanced_hits.sort(key=lambda x: x.score, reverse=True)
        self.model.set_items(enhanced_hits)
        if enhanced_hits:
            top_index = self.model.index(0)
            self.list.setCurrentIndex(top_index)
            self.list.scrollTo(top_index, QListView.ScrollHint.PositionAtTop)

    # --------------------------- Actions ------------------------------------
    def contextMenuEvent(self, event):
        idx = self.list.currentIndex(); hit = self.model.item(idx.row()) if idx.isValid() else None
        menu = QMenu(self)
        menu.addAction(QAction("Open", self, triggered=self._open_selected))
        menu.addAction(QAction("Reveal in Finder" if is_macos() else "Show in Explorer", self, triggered=self._reveal_selected))
        menu.addAction(QAction("Copy Path", self, triggered=self._copy_path))
        if is_macos():
            menu.addAction(QAction("Quick Look", self, triggered=self._quicklook_selected))
            menu.addAction(QAction("Open With…", self, triggered=self._open_with_selected))
        menu.addAction(QAction("Pin Entry (Copy to Clipboard)", self, triggered=self._copy_path))
        if hit is None:
            for a in menu.actions(): a.setEnabled(False)
        menu.exec(event.globalPos())

    def keyPressEvent(self, ev):
        if (ev.modifiers() & Qt.KeyboardModifier.ControlModifier) or (is_macos() and (ev.modifiers() & Qt.KeyboardModifier.MetaModifier)):
            if ev.key() == Qt.Key.Key_F:
                self.search.setFocus(); self.search.selectAll(); return
            if ev.key() == Qt.Key.Key_C:
                self._copy_path(); return
            if ev.key() == Qt.Key.Key_Y and is_macos():
                self._quicklook_selected(); return
        if ev.key() == Qt.Key.Key_Escape:
            self.close(); return
        super().keyPressEvent(ev)

    def _selected_hit(self) -> Optional[FileHit]:
        idx = self.list.currentIndex(); return self.model.item(idx.row()) if idx.isValid() else None

    def _open_selected(self):
        hit = self._selected_hit()
        if not hit: return
        os_open(hit.path)

    def _reveal_selected(self):
        hit = self._selected_hit()
        if not hit: return
        if is_macos():
            subprocess.run(["open", "-R", hit.path])
        elif is_windows():
            subprocess.run(["explorer", "/select,", hit.path])
        else:
            subprocess.run(["xdg-open", os.path.dirname(hit.path)])

    def _copy_path(self):
        hit = self._selected_hit()
        if not hit: return
        QApplication.clipboard().setText(hit.path)
        toast(self, "Copied path to clipboard")

    def _quicklook_selected(self):
        if not is_macos(): return
        hit = self._selected_hit()
        if not hit: return
        subprocess.Popen(["qlmanage", "-p", hit.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _open_with_selected(self):
        if not is_macos(): return
        hit = self._selected_hit()
        if not hit: return
        subprocess.run(["open", "-a", "", hit.path])

    def _update_preview(self):
        hit = self._selected_hit(); self.preview.set_file(hit.path if hit else None)

    def _apply_style(self):
        self.setStyleSheet(
            """
            QWidget#wrapper {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(24,24,28,230), stop:1 rgba(28,28,34,230));
                border-radius: 16px;
                border: 1px solid rgba(255,255,255,18);
            }
            QLineEdit {
                background: rgba(255,255,255,10);
                border: 1px solid rgba(255,255,255,18);
                border-radius: 10px;
                padding: 10px 12px;
                color: #f5f5f7;
                selection-background-color: #6ea1ff;
                font-size: 16px;
            }
            QComboBox {
                background: rgba(255,255,255,10);
                border: 1px solid rgba(255,255,255,18);
                border-radius: 10px;
                padding: 8px 10px;
                color: #eaeaea;
            }
            QListView {
                background: transparent;
                border: none;
                padding: 4px;
                color: #f0f0f0;
            }
            QListView::item {
                border-radius: 8px;
                padding: 4px;
                margin: 2px 4px;
            }
            QListView::item:selected {
                background: rgba(255,255,255,0.15);
                border: 1px solid rgba(255,255,255,0.3);
            }
            QListView::item:hover:!selected {
                background: rgba(255,255,255,0.08);
            }
            QSplitter::handle { background: rgba(255,255,255,10); }
            QLabel#previewTitle { color: #ffffff; font-weight: 600; font-size: 18px; }
            QLabel#previewMeta { color: #bcbcbc; }
            """
        )


# ------------------------------ PREVIEW --------------------------------------

class PreviewPane(QWidget):
    def __init__(self):
        super().__init__()
        self.current_path: Optional[str] = None
        self.current_pdf_pages: list[QPixmap] = []  # cache rendered pages

        # Layout
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title = QLabel("Preview"); self.title.setObjectName("previewTitle")
        self.meta = QLabel(""); self.meta.setObjectName("previewMeta"); self.meta.setWordWrap(True)
        header.addWidget(self.title, 1)
        header.addStretch(1)
        root.addLayout(header)
        root.addWidget(self.meta)
        root.addWidget(divider())

        # Main area split: large page view (left) + thumbnails (right)
        self.split = QSplitter()
        self.split.setOrientation(Qt.Orientation.Horizontal)

        # Left: scrollable large view
        self.page_scroll = QScrollArea(); self.page_scroll.setWidgetResizable(True)
        self.page_holder = QWidget()
        self.page_v = QVBoxLayout(self.page_holder)
        self.page_label = QLabel("No selection")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_v.addWidget(self.page_label)
        self.page_v.addStretch(1)
        self.page_scroll.setWidget(self.page_holder)
        self.split.addWidget(self.page_scroll)

        # Right: thumbnails list
        self.thumbs = QListWidget()
        self.thumbs.setIconSize(QSize(120, 160))
        self.thumbs.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbs.setMovement(QListWidget.Movement.Static)
        self.thumbs.setSpacing(8)
        self.thumbs.setFixedWidth(160)   # similar to macOS Preview
        self.thumbs.itemClicked.connect(self._on_thumb_clicked)
        self.split.addWidget(self.thumbs)

        self.split.setStretchFactor(0, 4)
        self.split.setStretchFactor(1, 1)
        root.addWidget(self.split, 1)

    # ---------- public API ----------
    def set_file(self, path: Optional[str]):
        self.current_pdf_pages = []
        self.thumbs.clear()
        self.page_label.setPixmap(QPixmap())
        if not path:
            self.current_path = None
            self.title.setText("Preview")
            self.meta.setText("")
            self.page_label.setText("No selection")
            return

        self.current_path = path
        self.title.setText(os.path.basename(path))
        try:
            st = os.stat(path)
            dt = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M')
            self.meta.setText(f"{elide_middle(path, 70)}\nModified: {dt}    Size: {human_size(st.st_size)}")
        except Exception:
            self.meta.setText(elide_middle(path, 70))

        ext = os.path.splitext(path)[1].lower()

        # Images
        if HAVE_PIL and ext in FILETYPE_MAP["Images"]:
            self._show_image(path)
            return

        # PDFs (full preview w/ thumbnails)
        if HAVE_PDF and ext == ".pdf":
            self._show_pdf(path)
            return

        # Fallback
        self.page_label.setText("No preview available")

    # ---------- helpers ----------
    def _show_image(self, path: str):
        pix = QPixmap(path)
        if pix.isNull():
            self.page_label.setText("Image preview failed")
            return
        self.page_label.setText("")
        self.page_label.setPixmap(
            pix.scaled(900, 1100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
    
    def find_poppler_bin() -> Optional[str]:
        """Return a directory containing pdftoppm or None."""
        candidates = [
            "/opt/homebrew/bin",        # Apple Silicon Homebrew
            "/usr/local/bin",           # Intel Homebrew
            "/usr/bin"                  # fallback
        ]
        for p in candidates:
            if os.path.isfile(os.path.join(p, "pdftoppm")):
                return p
        return None

    def _show_pdf(self, path: str):
        try:
            poppler_bin = find_poppler_bin()
            kwargs = {"dpi": 144, "first_page": 1, "last_page": 1}
            if poppler_bin:
                kwargs["poppler_path"] = poppler_bin

            pages = convert_from_path(path, **kwargs)
            if not pages:
                self.page_label.setText("PDF is empty")
                return

            img = pages[0]
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Build QImage with correct bytes-per-line
            w, h = img.width, img.height
            data = img.tobytes("raw", "RGB")
            bytes_per_line = w * 3
            qimg = QImage(data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)

            self.page_label.setText("")
            self.page_label.setPixmap(
                pixmap.scaled(900, 1100, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
            )
        except Exception as e:
            print(f"PDF preview failed: {e}")
            self.page_label.setText("PDF preview failed – is Poppler installed?")


    def _show_page(self, idx: int):
        if 0 <= idx < len(self.current_pdf_pages):
            big = self.current_pdf_pages[idx].scaled(
                1100, 1400, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.page_label.setText("")
            self.page_label.setPixmap(big)
            # Center the current page at top
            self.page_scroll.ensureWidgetVisible(self.page_label, 0, 0)

    def _on_thumb_clicked(self, item: QListWidgetItem):
        row = self.thumbs.row(item)
        self._show_page(row)



# ------------------------------ HELPERS --------------------------------------

def is_macos():
    return platform.system().lower().startswith('darwin')

def is_windows():
    return platform.system().lower().startswith('win')

def os_open(path: str):
    try:
        if is_macos():
            subprocess.run(["open", path], check=False)
        elif is_windows():
            os.startfile(path)  # type: ignore
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception as e:
        QMessageBox.warning(None, "Open failed", f"Could not open file:\n{e}")

def human_size(n: int) -> str:
    if n <= 0: return "0 B"
    units = ['B','KB','MB','GB','TB']
    i = min(int(math.log(n, 1024)), len(units)-1)
    return f"{n/ (1024**i):.1f} {units[i]}"

def elide_middle(text: str, max_chars: int) -> str:
    if len(text) <= max_chars: return text
    half = (max_chars - 1) // 2
    return text[:half] + '…' + text[-half:]

def center_on_screen(w: QWidget):
    screen = QApplication.primaryScreen().availableGeometry()
    w.move(int((screen.width()-w.width())/2), int((screen.height()-w.height())/3))

def divider() -> QFrame:
    d = QFrame(); d.setFrameShape(QFrame.Shape.HLine); d.setStyleSheet("color: rgba(255,255,255,20);"); return d

def toast(parent: QWidget, msg: str, msec: int = 1200):
    b = QPushButton(msg, parent)
    b.setEnabled(False)
    b.setStyleSheet("background: rgba(60,60,60,220); color: white; border-radius: 12px; padding: 6px 10px; border: 1px solid rgba(255,255,255,30);")
    b.adjustSize(); b.move(parent.width()-b.width()-20, parent.height()-b.height()-20)
    b.show(); QTimer.singleShot(msec, b.deleteLater)


# ------------------------------- MAIN ----------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Luma")
    ui = SpotlightUI()
    sys.exit(app.exec())

if __name__ == "__main__":
    # Delegate to modular app entrypoint
    try:
        from luma.app import main as run
        run()
    except Exception:
        # Fallback to local main if package import fails during transition
        main()
