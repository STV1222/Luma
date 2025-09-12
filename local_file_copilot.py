#!/usr/bin/env python3
"""
Luma – Desktop Spotlight‑style UI for your file search engine (PyQt6)
--------------------------------------------------------------------
Fix: removed the background QApplication hack that caused
"QApplication was not created in the main thread" and segfaults.
Now uses a QThread worker + signal/slot to update the UI safely.

Install deps:
    pip install PyQt6 rapidfuzz Pillow
Run:
    python luma_spotlight.py
"""

from __future__ import annotations
import os, sys, re, time, subprocess, platform, threading, math, json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
from langchain.llms import Ollama
from langchain.callbacks.manager import CallbackManager
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler

# ----------------------------- UI IMPORTS ------------------------------------
from PyQt6.QtCore import Qt, QAbstractListModel, QModelIndex, QSize, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction, QPixmap # QAction must come from QtGui in PyQt6
from PyQt6.QtWidgets import (
QApplication, QWidget, QLineEdit, QListView, QVBoxLayout, QHBoxLayout,
QLabel, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QFrame,
QComboBox, QSplitter, QFileIconProvider, QMenu, QMessageBox, QPushButton
)

try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

try:
    from rapidfuzz import fuzz
    HAVE_RAPIDFUZZ = True
except Exception:
    HAVE_RAPIDFUZZ = False


# ============================ AI ASSISTANT ===================================

class LumaAI:
    """Ollama-powered AI assistant for Luma"""
    
    def __init__(self):
        self.model = None
        self.initialized = False
    
    def ensure_initialized(self):
        """Lazy initialization of the model"""
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
        """Parse a natural language query using Ollama"""
        if not self.ensure_initialized():
            # Fallback to traditional parsing if AI isn't available
            return {
                "keywords": extract_keywords(query),
                "time_range": extract_time_window(query),
                "file_types": []
            }

        system_prompt = """You are a file search assistant. Analyze the search query and extract:
1. Important keywords (excluding common words)
2. Time ranges or dates
3. File types or extensions
4. Special requirements or conditions
Format your response as JSON with these keys: keywords, time_range, file_types, special_reqs"""

        try:
            response = self.model.invoke(
                f"{system_prompt}\nQuery: {query}\nResponse:"
            )
            
            # Extract JSON from response
            json_str = response.strip()
            if not json_str.startswith("{"):
                json_str = json_str[json_str.find("{"):]
            if not json_str.endswith("}"):
                json_str = json_str[:json_str.rfind("}")+1]
                
            result = json.loads(json_str)
            
            # Convert time range to timestamps
            if result.get("time_range"):
                result["time_range"] = extract_time_window(result["time_range"])
            else:
                result["time_range"] = (None, None)
                
            return result
            
        except Exception as e:
            print(f"AI parsing failed: {e}, falling back to traditional parsing")
            return {
                "keywords": extract_keywords(query),
                "time_range": extract_time_window(query),
                "file_types": []
            }

    def enhance_results(self, query: str, results: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
        """Enhance search results ranking using AI understanding"""
        if not self.ensure_initialized():
            return results
            
        try:
            # Get AI's opinion on result relevance
            paths = [path for path, _ in results[:10]]  # Process top 10 for efficiency
            prompt = f"""Rate how relevant these files are to the query: "{query}"
Files:
{chr(10).join(paths)}

Rate each file's relevance from 0-100 based on the filename and path.
Respond with a JSON list of scores only, like: [95, 80, 70, ...]"""

            response = self.model.invoke(prompt)
            
            # Extract scores from response
            scores_str = response[response.find("["):response.find("]")+1]
            ai_scores = json.loads(scores_str)
            
            # Blend AI scores with original scores
            enhanced_results = []
            for i, (path, score) in enumerate(results):
                if i < len(ai_scores):
                    # Blend original score (70%) with AI score (30%)
                    new_score = score * 0.7 + ai_scores[i] * 0.3
                    enhanced_results.append((path, new_score))
                else:
                    enhanced_results.append((path, score))
                    
            # Sort by new scores
            enhanced_results.sort(key=lambda x: x[1], reverse=True)
            return enhanced_results
            
        except Exception as e:
            print(f"AI enhancement failed: {e}, using original results")
            return results

# ============================ SEARCH SECTION =================================
# (Adapted from your provided script; trimmed to essentials and imported here.)

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
ABS_YEAR = re.compile(r"\b(20\d{2})\b")
EXT_PATTERN = re.compile(r"\b(\w+)\s*files?\b|\.(\w{1,6})\b", re.I)
STOPWORDS = {"find","show","get","open","the","a","an","me","my","files","file","of","for","about","last","this","that","these","those","recent","latest"}


def extract_time_window(q: str) -> Tuple[float, float] | Tuple[None, None]:
    ql = q.lower()
    now = datetime.now()
    for pat, days_back, _ in REL_TIME_PATTERNS:
        if re.search(pat, ql):
            start = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
            return (start.timestamp(), end.timestamp())
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


def search_files(folders: List[str], keywords: List[str], allow_exts: List[str], time_range: Tuple[float,float] | Tuple[None,None]) -> List[Tuple[str,float]]:
    tmin, tmax = time_range
    results: List[Tuple[str,float]] = []
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
                    mtime = st.st_mtime
                    size = st.st_size
                except Exception:
                    continue
                if tmin is not None and mtime < tmin: continue
                if tmax is not None and mtime > tmax: continue
                s = filename_score(fn, keywords) + recency_boost(mtime)
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
        
        # Don't draw selection background (handled by stylesheet)
        
        # Draw icon with slight adjustment for visual balance
        icon: QIcon = index.data(Qt.ItemDataRole.DecorationRole)
        pix = icon.pixmap(32, 32)
        icon_y = r.top() + (r.height() - 32) // 2  # Center vertically
        painter.drawPixmap(r.left() + 16, icon_y, pix)
        
        # Calculate text rectangles
        text_left = r.left() + 64
        text_width = r.width() - 80
        
        # Draw filename with larger, bold font
        name = os.path.basename(hit.path)
        font = painter.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        painter.setFont(font)
        
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.GlobalColor.white)
        else:
            painter.setPen(option.palette.windowText().color())
            
        painter.drawText(text_left, r.top() + 24, name)
        
        # Draw path and metadata with smaller font
        font.setPointSize(font.pointSize() - 2)
        font.setBold(False)
        painter.setFont(font)
        
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.GlobalColor.lightGray)
        else:
            painter.setPen(option.palette.mid().color())
            
        path = elide_middle(os.path.dirname(hit.path), 60)
        dt = datetime.fromtimestamp(hit.mtime).strftime('%Y-%m-%d %H:%M')
        info = f"{path}  •  {dt}  •  {human_size(hit.size)}"
        painter.drawText(text_left, r.top() + 44, info)
        
        painter.restore()

# ============================ SEARCH WORKER ==================================

class SearchWorker(QThread):
    results_ready = pyqtSignal(list)

    def __init__(self, folders: List[str], keywords: List[str], allow_exts: List[str], time_range: Tuple[float,float] | Tuple[None,None]):
        super().__init__()
        self.folders = folders
        self.keywords = keywords
        self.allow_exts = allow_exts
        self.time_range = time_range

    def run(self):
        hits = []
        for path, score in search_files(self.folders, self.keywords, self.allow_exts, self.time_range):
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
        # Remove real-time search

        self.filter = QComboBox(); self.filter.addItems(list(FILETYPE_MAP.keys()))
        self.filter.currentIndexChanged.connect(self._perform_search)  # Search immediately when filter changes

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
        
        # Use AI to parse the query
        query_info = self.ai.parse_query(q)
        keywords = query_info["keywords"]
        time_range = query_info["time_range"]
        
        # Add any AI-detected file types to the filter
        ai_exts = query_info.get("file_types", [])
        if ai_exts and not allow_exts:  # Only use AI exts if no category filter
            allow_exts.extend(ai_exts)

        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.quit()
            self._worker.wait(50)

        self._worker = SearchWorker(self._folders, keywords, allow_exts, time_range)
        self._worker.results_ready.connect(self._apply_hits)
        self._worker.start()

    def _apply_hits(self, hits: List[FileHit]):
        if not hits:
            self.model.set_items([])
            return

        # Convert hits to format expected by enhance_results
        results = [(hit.path, float(hit.score)) for hit in hits]
        
        # Enhance results using AI
        enhanced = self.ai.enhance_results(self.search.text().strip(), results)
        
        # Convert back to FileHit objects and sort by score
        enhanced_hits = []
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
        
        # Sort by score in descending order
        enhanced_hits.sort(key=lambda x: x.score, reverse=True)
        
        # Update model and select top result
        self.model.set_items(enhanced_hits)
        if enhanced_hits:
            top_index = self.model.index(0)
            self.list.setCurrentIndex(top_index)
            self.list.scrollTo(top_index, QListView.ScrollHint.PositionAtTop)  # Ensure top result is visible

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
        hit = self._selected_hit();
        if not hit: return
        os_open(hit.path)

    def _reveal_selected(self):
        hit = self._selected_hit();
        if not hit: return
        if is_macos():
            subprocess.run(["open", "-R", hit.path])
        elif is_windows():
            subprocess.run(["explorer", "/select,", hit.path])
        else:
            subprocess.run(["xdg-open", os.path.dirname(hit.path)])

    def _copy_path(self):
        hit = self._selected_hit();
        if not hit: return
        QApplication.clipboard().setText(hit.path)
        toast(self, "Copied path to clipboard")

    def _quicklook_selected(self):
        if not is_macos(): return
        hit = self._selected_hit();
        if not hit: return
        subprocess.Popen(["qlmanage", "-p", hit.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _open_with_selected(self):
        if not is_macos(): return
        hit = self._selected_hit();
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
        self.v = QVBoxLayout(self)
        self.title = QLabel("Preview"); self.title.setObjectName("previewTitle")
        self.meta = QLabel(""); self.meta.setObjectName("previewMeta"); self.meta.setWordWrap(True)
        self.thumb = QLabel("No selection"); self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter); self.thumb.setMinimumHeight(220)
        self.v.addWidget(self.title); self.v.addWidget(self.meta); self.v.addWidget(divider()); self.v.addWidget(self.thumb, 1)

    def set_file(self, path: Optional[str]):
        if not path:
            self.title.setText("Preview"); self.meta.setText(""); self.thumb.setText("No selection"); self.thumb.setPixmap(QPixmap()); return
        self.title.setText(os.path.basename(path))
        try:
            st = os.stat(path)
            dt = datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M')
            self.meta.setText(f"{elide_middle(path, 70)}\nModified: {dt}    Size: {human_size(st.st_size)}")
        except Exception:
            self.meta.setText(elide_middle(path, 70))
        if HAVE_PIL and os.path.splitext(path)[1].lower() in FILETYPE_MAP["Images"]:
            try:
                self.thumb.setPixmap(QPixmap(path).scaled(560, 320, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.thumb.setText(""); return
            except Exception:
                pass
        self.thumb.setPixmap(QPixmap()); self.thumb.setText("No preview available")

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
    main()
