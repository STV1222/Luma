#!/usr/bin/env python3
"""
Luma – Desktop Spotlight-style UI for your file search engine (PyQt6)
"""

from __future__ import annotations
import os, sys, re, time, subprocess, platform, math, json, tempfile, shutil, calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any

from PyQt6.QtCore import Qt, QAbstractListModel, QModelIndex, QSize, QTimer, QThread, pyqtSignal, QFileInfo
from PyQt6.QtGui import QIcon, QPixmap, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLineEdit, QListView, QVBoxLayout, QHBoxLayout,
    QLabel, QStyledItemDelegate, QStyleOptionViewItem, QFrame, QComboBox,
    QSplitter, QFileIconProvider, QMessageBox, QGridLayout, QCheckBox,
    QSizePolicy, QStyle
)

# ---------- optional libs ----------
try:
    from PIL import Image  # noqa: F401
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

try:
    from pdf2image import convert_from_path
    HAVE_PDF = True
except Exception:
    HAVE_PDF = False
    print("Warning: pdf2image not installed. `pip install pdf2image`")
    print("Also install Poppler: brew install poppler")

try:
    from rapidfuzz import fuzz
    HAVE_RAPIDFUZZ = True
except Exception:
    HAVE_RAPIDFUZZ = False

# ---------- AI (optional via Ollama) ----------
HAVE_OLLAMA = False
try:
    from langchain.llms import Ollama
    from langchain.callbacks.manager import CallbackManager
    from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
    HAVE_OLLAMA = True
except Exception:
    HAVE_OLLAMA = False

# ============================ constants / config =============================
DEFAULT_FOLDERS = [os.path.expanduser("~/Documents"),
                   os.path.expanduser("~/Downloads"),
                   os.path.expanduser("~/Desktop")]
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

DATE_PATTERNS = [
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\s*,?\s*\d{4}\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*,?\s*\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
]
# Month-year without a day (e.g., "May 2025" or "2025 May" or "2025-05")
MONTH_YEAR_PATTERNS = [
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b",
    r"\b\d{4}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\b",
    r"\b(20\d{2})-(0[1-9]|1[0-2])\b",
]
REL_TIME_PATTERNS = [(r"\btoday\b", 0), (r"\byesterday\b", 1), (r"\blast\s+week\b", 7), (r"\blast\s+month\b", 30)]
ABS_YEAR = re.compile(r"\b(20\d{2})\b")
STOPWORDS = {"find","show","get","open","the","a","an","me","my","files","file","of","for","about","last","this","that","these","those","recent","latest"}

def is_macos(): return platform.system().lower().startswith("darwin")
def is_windows(): return platform.system().lower().startswith("win")
def find_poppler_bin() -> Optional[str]:
    for p in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        if os.path.isfile(os.path.join(p, "pdftoppm")):
            return p
    return None
def human_size(n: int) -> str:
    if n <= 0: return "0 B"
    units = ["B","KB","MB","GB","TB"]; i = min(int(math.log(n, 1024)), len(units)-1)
    return f"{n/(1024**i):.1f} {units[i]}"
def elide_middle(s: str, n: int) -> str:
    if len(s) <= n: return s
    half = (n - 1)//2
    return s[:half] + "…" + s[-half:]
def center_on_screen(w: QWidget):
    g = QApplication.primaryScreen().availableGeometry()
    w.move(int((g.width()-w.width())/2), int((g.height()-w.height())/3))
def divider() -> QFrame:
    d = QFrame(); d.setFrameShape(QFrame.Shape.HLine); d.setStyleSheet("color: rgba(0,0,0,0.08);"); return d
def os_open(path: str):
    try:
        if is_macos(): subprocess.run(["open", path], check=False)
        elif is_windows(): os.startfile(path)  # type: ignore
        else: subprocess.run(["xdg-open", path], check=False)
    except Exception as e:
        QMessageBox.warning(None, "Open failed", f"Could not open file:\n{e}")

# ---------- dates ----------
def extract_time_window(q: str) -> Tuple[float, float] | Tuple[None, None]:
    if not q: return (None, None)
    ql = q.lower(); now = datetime.now()
    for pat in DATE_PATTERNS:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            ds = m.group(0)
            for fmt in ["%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d"]:
                try:
                    dt = datetime.strptime(ds, fmt)
                    s = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                    e = dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
                    return (s, e)
                except ValueError:
                    pass
    # Month-year handling (e.g., "May 2025" or "2025 May" or "2025-05")
    for pat in MONTH_YEAR_PATTERNS:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            token = m.group(0)
            year = None; month = None
            # Try numeric YYYY-MM
            mnum = re.match(r"^(20\d{2})-(0[1-9]|1[0-2])$", token)
            if mnum:
                year = int(mnum.group(1)); month = int(mnum.group(2))
            else:
                # Try named month first or second
                parts = re.findall(r"(20\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*)", token, re.IGNORECASE)
                if len(parts) >= 2:
                    # Normalize month name
                    def to_month(p: str) -> int | None:
                        try:
                            return datetime.strptime(p[:3].title(), "%b").month
                        except Exception:
                            return None
                    # Determine order
                    if parts[0].isdigit():
                        year = int(parts[0]); month = to_month(parts[1])
                    else:
                        month = to_month(parts[0]); year = int(parts[1]) if parts[1].isdigit() else None
            if year and month:
                start = datetime(year, month, 1)
                last_day = calendar.monthrange(year, month)[1]
                end = datetime(year, month, last_day, 23, 59, 59, 999999)
                return (start.timestamp(), end.timestamp())
    for pat, days_back in REL_TIME_PATTERNS:
        if re.search(pat, ql):
            s = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            return (s, now.timestamp())
    m = ABS_YEAR.search(q)
    if m:
        year = int(m.group(1)); s = datetime(year,1,1); e = datetime(year+1,1,1) - timedelta(seconds=1)
        return (s.timestamp(), e.timestamp())
    return (None, None)

# ============================ AI helper ======================================
class LumaAI:
    def __init__(self):
        self._model = None

    def _ensure(self) -> bool:
        if not HAVE_OLLAMA: return False
        if self._model is None:
            try:
                self._model = Ollama(model="mistral",
                                     callback_manager=CallbackManager([StreamingStdOutCallbackHandler()]))
            except Exception:
                return False
        return True

    def parse_query_nonai(self, query: str) -> Dict[str, Any]:
        tr = extract_time_window(query)
        kws = strip_time_keywords(extract_keywords(query), query, tr)
        return {"keywords": kws,
                "time_range": None if tr==(None,None) else tr,
                "file_types": [], "time_attr": "mtime"}

    def parse_query_ai(self, query: str) -> Dict[str, Any]:
        # Use an LLM to extract filters; fall back to non-AI if unavailable.
        if not self._ensure() or not query.strip():
            return self.parse_query_nonai(query)
        prompt = (
            "Extract a JSON object for a file search UI.\n"
            "Fields: keywords (array), time_range (string date or null), "
            "file_types (array like ['pdf','png'] or []), action ('edited'|'created').\n"
            f"Query: {query}\nJSON:"
        )
        try:
            raw = self._model.invoke(prompt).strip()
            if not raw.startswith("{"): raw = raw[raw.find("{"):]
            if not raw.endswith("}"): raw = raw[:raw.rfind("}")+1]
            data = json.loads(raw)
            # Prefer month-wide ranges if the natural-language query contains a month-year,
            # even if the LLM narrowed it to a specific day.
            tr_model = extract_time_window(str(data.get("time_range","")) or "")
            tr_query = extract_time_window(query)
            def span(t):
                if not t or t==(None,None): return 0
                s,e=t; 
                if s is None or e is None: return 0
                return max(0, e - s)
            tr = tr_query if span(tr_query) > span(tr_model) else tr_model
            allow = ['.'+e.lstrip('.') for e in data.get("file_types", [])]
            time_attr = "birthtime" if str(data.get("action","")).lower().startswith("creat") else "mtime"
            kws = data.get("keywords", []) or extract_keywords(query)
            kws = strip_time_keywords(kws, query, tr)
            return {"keywords": kws,
                    "time_range": None if tr==(None,None) else tr,
                    "file_types": allow, "time_attr": time_attr}
        except Exception:
            return self.parse_query_nonai(query)

# ============================ search core ====================================
def extract_keywords(q: str) -> List[str]:
    quoted = re.findall(r'"([^"]+)"', q)
    q_wo = re.sub(r'"[^"]+"', ' ', q)
    words = re.findall(r"[A-Za-z0-9_\-]+", q_wo)
    return [*quoted, *[w for w in words if w.lower() not in STOPWORDS]]

def strip_time_keywords(keywords: List[str], original_query: str, time_range: Tuple[float,float] | Tuple[None,None]) -> List[str]:
    if not keywords:
        return keywords
    # Remove month names and years if we already have an explicit time window
    months = {
        "jan","january","feb","february","mar","march","apr","april","may","jun","june",
        "jul","july","aug","august","sep","sept","september","oct","october","nov","november","dec","december"
    }
    noise = {"edited","created","modified","updated","on","in","during","between","from","to","at"}
    has_time = time_range and time_range != (None, None)
    cleaned: List[str] = []
    for w in keywords:
        wl = w.lower()
        if wl in noise:
            continue
        if wl in months:
            # Drop month tokens so they don't constrain filenames
            continue
        if has_time and re.fullmatch(r"20\d{2}", wl):
            # If a range is detected, year tokens in keywords are redundant
            continue
        cleaned.append(w)
    return cleaned

def filename_score(name: str, kws: List[str]) -> float:
    base = name.lower()
    if not kws: return 50.0
    score=0.0
    for kw in kws:
        k=kw.lower()
        if k in base: score+=60
        elif HAVE_RAPIDFUZZ: score += fuzz.partial_ratio(k, base)*0.6
    return score/max(1,len(kws))

def recency_boost(mtime: float) -> float:
    age = max(0.0,(time.time()-mtime)/86400.0)
    if age<1: return 40
    if age<7: return 25
    if age<30: return 15
    if age<180: return 8
    return 0

def search_files(folders: List[str], keywords: List[str], allow_exts: List[str],
                 time_range: Optional[Tuple[float,float]], time_attr: str="mtime") -> List[Tuple[str,float]]:
    tmin,tmax = (time_range or (None,None))
    results=[]; allow=[e.lower() for e in allow_exts] if allow_exts else []
    for root in folders:
        if not os.path.isdir(root): continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith('.')]
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                if allow and os.path.splitext(fn)[1].lower() not in allow: continue
                try:
                    st = os.stat(path)
                    tstamp = st.st_mtime if time_attr=="mtime" else getattr(st, "st_birthtime", st.st_ctime)
                    if tmin is not None and tmax is not None:
                        d = datetime.fromtimestamp(tstamp).date()
                        if not (datetime.fromtimestamp(tmin).date() <= d <= datetime.fromtimestamp(tmax).date()):
                            continue
                    elif tmin is not None and tstamp < tmin: continue
                    elif tmax is not None and tstamp > tmax: continue
                except Exception:
                    continue
                s = filename_score(fn, keywords) + recency_boost(st.st_mtime)
                if s>0: results.append((path, s))
    results.sort(key=lambda x:x[1], reverse=True)
    return results[:MAX_RESULTS]

# ============================ UI model / delegate ============================
@dataclass
class FileHit:
    path: str; score: int; mtime: float; size: int

class ResultsModel(QAbstractListModel):
    def __init__(self):
        super().__init__(); self._items: List[FileHit]=[]; self._icon=QFileIconProvider()
    def rowCount(self, parent: QModelIndex=QModelIndex()) -> int: return len(self._items)  # type: ignore[override]
    def data(self, index: QModelIndex, role: int):  # type: ignore[override]
        if not index.isValid(): return None
        h=self._items[index.row()]
        if role==Qt.ItemDataRole.DisplayRole: return os.path.basename(h.path)
        if role==Qt.ItemDataRole.ToolTipRole:
            return f"{h.path}\nModified: {datetime.fromtimestamp(h.mtime):%Y-%m-%d %H:%M}\nSize: {human_size(h.size)}\nScore: {h.score}"
        if role==Qt.ItemDataRole.DecorationRole: return self._icon.icon(QFileInfo(h.path))
        return None
    def set_items(self, items: List[FileHit]): self.beginResetModel(); self._items=items; self.endResetModel()
    def item(self, row:int)->Optional[FileHit]: return self._items[row] if 0<=row<len(self._items) else None

class ResultDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # type: ignore[override]
        return QSize(option.rect.width(),56)
    def paint(self, p, opt: QStyleOptionViewItem, idx: QModelIndex):  # type: ignore[override]
        h: FileHit = idx.model().item(idx.row())  # type: ignore
        if not h: return super().paint(p,opt,idx)
        p.save(); r=opt.rect
        icon:QIcon = idx.data(Qt.ItemDataRole.DecorationRole)
        # Render slightly smaller, crisp icons aligned with filename baseline (16px, HiDPI aware)
        dpr = p.device().devicePixelRatioF() if hasattr(p.device(), 'devicePixelRatioF') else 1.0
        icon_size = 16
        gap_px = 20  # space between icon and text
        size_px = int(icon_size * dpr)
        pix = icon.pixmap(size_px, size_px)
        try:
            pix.setDevicePixelRatio(dpr)
        except Exception:
            pass
        # Align icon vertically with the filename baseline
        f=p.font(); f.setPointSize(f.pointSize()+1); f.setBold(True); p.setFont(f)
        fm = p.fontMetrics()
        base_y = r.top()+24  # text baseline for the filename
        # Center icon around the visual midline of the text (ascent-descent)/2 above baseline
        text_mid_y = base_y - ((fm.ascent() - fm.descent()) / 2.0)
        icon_x = r.left()+12
        icon_y = int(text_mid_y - (icon_size/2))
        p.drawPixmap(icon_x, icon_y, pix)
        name=os.path.basename(h.path)
        meta=f"{elide_middle(os.path.dirname(h.path),42)}  •  {human_size(h.size)}"
        text_x = icon_x + icon_size + gap_px
        p.setPen(opt.palette.windowText().color()); p.drawText(text_x, r.top()+24, name)
        f.setPointSize(f.pointSize()-2); f.setBold(False); p.setFont(f)
        p.setPen(opt.palette.mid().color()); p.drawText(text_x, r.top()+40, meta)
        p.restore()

# ============================ spinner ==============================
class BusySpinner(QWidget):
    def __init__(self, diameter=18, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._timer = QTimer(self); self._timer.timeout.connect(self._tick)
        self.setFixedSize(diameter, diameter); self.hide()
    def start(self): self.show(); self._timer.start(16)
    def stop(self): self._timer.stop(); self.hide(); self.update()
    def _tick(self): self._angle = (self._angle + 10) % 360; self.update()
    def paintEvent(self, ev):
        if not self.isVisible(): return
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2,2,-2,-2)
        base = QPen(self.palette().mid().color(), 2)
        hi = QPen(self.palette().highlight().color(), 2)
        p.setPen(base); p.drawArc(rect, 0, 16*360)
        p.setPen(hi); p.drawArc(rect, int(-16*self._angle), 16*110)

# ============================ preview (Spotlight-like) =======================
def ext_to_type(ext: str) -> str:
    ext = ext.lower()
    if ext in FILETYPE_MAP["PDF"]: return "PDF document"
    if ext in FILETYPE_MAP["Slides"]: return "Presentation"
    if ext in FILETYPE_MAP["Images"]: return "Image"
    if ext in FILETYPE_MAP["Spreadsheets"]: return "Spreadsheet"
    if ext in FILETYPE_MAP["Code"]: return "Code"
    return (ext[1:].upper()+" file") if ext else "File"

class PreviewPane(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self); root.setContentsMargins(24,12,24,12)
        top = QHBoxLayout(); top.setSpacing(24)

        # Thumbnail card only (no big filename)
        self.card = QFrame(); self.card.setObjectName("thumbCard")
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        cLay = QVBoxLayout(self.card); cLay.setContentsMargins(0,0,0,0)
        self.thumb = QLabel(); self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Let the thumbnail grow to fill available preview space without shifting layout
        self.thumb.setMinimumSize(0, 0)
        self.thumb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.thumb.setScaledContents(False)
        cLay.addWidget(self.thumb)

        # Make the thumbnail region expand to available width/height
        top.addWidget(self.card, 1)

        metaHeader = QLabel("Metadata"); metaHeader.setObjectName("metaHeader")

        gridWrap = QVBoxLayout(); gridWrap.setSpacing(0)
        self._rows: list[tuple[QLabel, QLabel]] = []
        def add_row(label_text: str):
            row = QGridLayout(); row.setContentsMargins(0,0,0,0); row.setHorizontalSpacing(12)
            l = QLabel(label_text); l.setObjectName("metaLabel")
            v = QLabel("—"); v.setObjectName("metaValue")
            # Ensure long values wrap and don't get covered by separators
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            v.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            row.setColumnStretch(0, 0)
            row.setColumnStretch(1, 1)
            row.addWidget(l, 0, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(v, 0, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
            wrap = QVBoxLayout(); wrap.setSpacing(4); wrap.setContentsMargins(0,6,0,6)
            cont = QWidget(); cont.setLayout(row); cont.setObjectName("rowContainer")
            wrap.addWidget(cont)
            sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setObjectName("rowSep")
            wrap.addWidget(sep)
            holder = QWidget(); holder.setLayout(wrap)
            gridWrap.addWidget(holder)
            self._rows.append((l, v))
            return v

        self.v_name    = add_row("Name")
        self.v_where   = add_row("Where")
        self.v_type    = add_row("Type")
        self.v_size    = add_row("Size")
        self.v_tags    = add_row("Tags")
        self.v_created = add_row("Created")

        # Group metadata header + rows so stretch applies to the whole section
        metaWrap = QVBoxLayout(); metaWrap.setSpacing(6); metaWrap.setContentsMargins(0,0,0,0)
        metaWrap.addWidget(metaHeader)
        metaWrap.addLayout(gridWrap)

        # Allocate 2/3 of vertical space to preview, 1/3 to metadata
        root.addLayout(top, 10)
        root.addLayout(metaWrap, 1)
        self._orig_thumb: Optional[QPixmap] = None
        self._orig_orientation: Optional[str] = None  # 'portrait' | 'landscape'

    def set_file(self, path: Optional[str]):
        self._orig_thumb = None
        self.thumb.clear()
        for _,v in self._rows: v.setText("—")
        if not path: return
        try:
            st = os.stat(path)
            ext = os.path.splitext(path)[1].lower()
            self.v_name.setText(os.path.basename(path))
            self.v_where.setText(elide_middle(os.path.dirname(path) or path, 80))
            self.v_type.setText(ext_to_type(ext))
            self.v_size.setText(human_size(st.st_size))
            self.v_tags.setText("—")
            self.v_created.setText(datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y at %H:%M:%S"))
        except Exception:
            self.v_where.setText(elide_middle(path,80))

        # thumbnail
        ext = os.path.splitext(path)[1].lower()
        if HAVE_PIL and ext in FILETYPE_MAP["Images"]:
            pix = QPixmap(path)
            if not pix.isNull():
                self._set_thumb(pix)
                self._orig_orientation = 'landscape' if pix.width() >= pix.height() else 'portrait'
                return
        if HAVE_PDF and ext == ".pdf":
            self._show_pdf_thumb(path); return
        # Try macOS Quick Look for common document types (Word/PowerPoint/Excel/etc.)
        if is_macos() and ext in {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".rtf", ".txt", ".md"}:
            if self._show_quicklook_thumb(path):
                return
        # Fallback: large system file icon
        self._show_generic_icon(path)

    def resizeEvent(self, ev):
        super().resizeEvent(ev); self._fit_thumb()
    def _set_thumb(self, pixmap: QPixmap):
        self._orig_thumb = pixmap; self._fit_thumb()
    def _fit_thumb(self):
        if not self._orig_thumb or self._orig_thumb.isNull(): return
        # Choose orientation-aware fitting and maximize visual size (frameless)
        target = self.card.contentsRect().size()
        # Render pixmap at device pixel ratio for crisp Retina/HiDPI previews
        dpr = self.devicePixelRatioF()
        tw = max(1, int(target.width() * dpr))
        th = max(1, int(target.height() * dpr))
        scaled = self._orig_thumb.scaled(
            tw, th,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        try:
            scaled.setDevicePixelRatio(dpr)
        except Exception:
            pass
        self.thumb.setPixmap(scaled)
    def _show_pdf_thumb(self, path: str):
        try:
            poppler_bin = find_poppler_bin() or "/usr/local/bin"
            # Render a higher-resolution first page for a crisper preview
            base_dpi = 300
            dpr = self.devicePixelRatioF()
            dpi = max(150, int(base_dpi * dpr))
            pages = convert_from_path(path, dpi=dpi, first_page=1, last_page=1, poppler_path=poppler_bin)
            if not pages: self.thumb.setText("PDF has no pages."); return
            img = pages[0]
            if img.mode != "RGB": img = img.convert("RGB")
            w, h = img.width, img.height
            qimg = QImage(img.tobytes("raw","RGB"), w, h, w*3, QImage.Format.Format_RGB888)
            qpix = QPixmap.fromImage(qimg)
            self._orig_orientation = 'landscape' if w >= h else 'portrait'
            self._set_thumb(qpix)
        except Exception:
            self.thumb.setText("PDF preview failed")

    def _show_quicklook_thumb(self, path: str) -> bool:
        # macOS-only: use Quick Look to generate a thumbnail image for many types
        try:
            if not is_macos():
                return False
            dpr = self.devicePixelRatioF()
            size = max(256, min(1024, int(512 * dpr)))
            temp_dir = tempfile.mkdtemp(prefix="luma_ql_")
            try:
                subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", temp_dir, path],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                # Find the newest image in temp_dir
                candidates = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
                              if f.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff"))]
                if not candidates:
                    return False
                best = max(candidates, key=os.path.getmtime)
                pix = QPixmap(best)
                if pix.isNull():
                    return False
                self._set_thumb(pix)
                return True
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            return False

    def _show_generic_icon(self, path: str):
        try:
            provider = QFileIconProvider()
            icon = provider.icon(QFileInfo(path))
            # Request a large pixmap; HiDPI scaling handled in _fit_thumb
            pix = icon.pixmap(256, 256)
            if pix.isNull():
                pix = icon.pixmap(128, 128)
            if not pix.isNull():
                self._set_thumb(pix)
                return
        except Exception:
            pass
        self.thumb.setText("No preview")

# ============================ worker =========================================
class SearchWorker(QThread):
    results_ready = pyqtSignal(list)
    def __init__(self, folders, keywords, allow_exts, time_range, time_attr="mtime"):
        super().__init__(); self.folders=folders; self.keywords=keywords; self.allow_exts=allow_exts; self.time_range=time_range; self.time_attr=time_attr
    def run(self):
        hits=[]
        for path,score in search_files(self.folders, self.keywords, self.allow_exts, self.time_range, self.time_attr):
            try:
                st=os.stat(path); hits.append(FileHit(path, int(score), st.st_mtime, st.st_size))
            except Exception: continue
        self.results_ready.emit(hits)

# ============================ toggle (Ask AI) ================================
class ToggleSwitch(QCheckBox):
    """Mac-like pill switch."""
    def __init__(self, text="Ask AI", parent=None):
        super().__init__(text, parent)
        self.setChecked(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()
    def _apply_style(self):
        self.setStyleSheet("""
        QCheckBox { spacing: 8px; font-weight: 600; color: #4a4a4a; }
        QCheckBox::indicator { width: 36px; height: 22px; }
        QCheckBox::indicator:unchecked { border-radius: 11px; background: rgba(0,0,0,0.08); }
        QCheckBox::indicator:unchecked:pressed { background: rgba(0,0,0,0.15); }
        QCheckBox::indicator:checked { border-radius: 11px; background: #3b82f6; }
        QCheckBox::indicator:checked:pressed { background: #2563eb; }
        """)

# ============================ main window ====================================
class SpotlightUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Luma")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(1000, 640)
        self._folders=DEFAULT_FOLDERS[:]
        self._worker: Optional[SearchWorker]=None
        self.ai=LumaAI()

        wrapper=QFrame(); wrapper.setObjectName("wrapper")

        # Top bar
        self.search=QLineEdit(); self.search.setPlaceholderText("Search files…")
        # Removed leading arrow icon per request
        self.filter=QComboBox(); self.filter.clear(); self.filter.addItems(["User (stv)"])
        self.filter.setMinimumWidth(120)
        self.filter.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ai_toggle = ToggleSwitch("Ask AI")
        # Spinner holder keeps a fixed slot so the top bar never shifts
        self.spinner = BusySpinner(18)
        self.spinner_holder = QWidget()
        _sh = QHBoxLayout(self.spinner_holder)
        _sh.setContentsMargins(0,0,0,0); _sh.setSpacing(0)
        _sh.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.spinner_holder.setFixedSize(28, 24)

        top=QHBoxLayout()
        top.addWidget(self.search,1)
        top.addWidget(self.filter,0)
        top.addStretch(1)                 # push toggle to far right
        top.addWidget(self.ai_toggle,0)
        top.addWidget(self.spinner_holder,0)

        # Debounce for non-AI instant search
        self._search_timer = QTimer(self); self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)  # snappy
        self._search_timer.timeout.connect(self._perform_search)

        # Wiring: text changes only trigger when AI is OFF
        self.search.textChanged.connect(self._on_text_changed)
        self.search.returnPressed.connect(self._perform_search)
        self.filter.currentIndexChanged.connect(self._on_filter_changed)
        self.ai_toggle.stateChanged.connect(self._on_ai_toggle)

        # Results + preview
        self.model=ResultsModel(); self.list=QListView(); self.list.setModel(self.model)
        self.list.setItemDelegate(ResultDelegate()); self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.list.doubleClicked.connect(self._open_selected)
        self.list.selectionModel().selectionChanged.connect(self._update_preview)  # type: ignore

        self.preview=PreviewPane()
        self.preview.setVisible(False)  # hidden until results ready

        # Left pane with header + list, right pane is preview
        leftPane = QFrame(); leftPane.setObjectName("leftPane")
        leftLay = QVBoxLayout(leftPane); leftLay.setContentsMargins(12,12,12,12); leftLay.setSpacing(8)
        leftLay.addWidget(self.list, 1)

        split=QSplitter(); split.addWidget(leftPane); split.addWidget(self.preview)
        # Default to 60:40 split (left:list, right:preview)
        split.setStretchFactor(0,3); split.setStretchFactor(1,2)
        split.setSizes([600, 400])

        lay=QVBoxLayout(wrapper); lay.addLayout(top); lay.addWidget(divider()); lay.addWidget(split,1)
        outer=QVBoxLayout(self); outer.addWidget(wrapper)

        self._apply_style(); center_on_screen(self); self.show(); self.search.setFocus()

    # --------- NEW: input handling respecting AI mode ----------
    def _on_text_changed(self, _text: str):
        if self.ai_toggle.isChecked():
            # AI mode: do nothing until Enter
            self._search_timer.stop()
            return
        # Non-AI: refresh instantly (debounced)
        self._search_timer.start()

    def _on_filter_changed(self, _=None):
        if self.ai_toggle.isChecked():
            # AI mode: wait for Enter
            return
        self._perform_search()

    def _on_ai_toggle(self, _state: int):
        # Clear any pending instant search and update hint
        self._search_timer.stop()
        if self.ai_toggle.isChecked():
            self.search.setPlaceholderText("Search files… (press Enter to Ask AI)")
        else:
            self.search.setPlaceholderText("Search files…")

    # search flow: hide preview while searching; show when results arrive
    def _perform_search(self):
        q=self.search.text().strip(); category=self.filter.currentText(); allow_exts=FILETYPE_MAP.get(category, [])
        info = self.ai.parse_query_ai(q) if self.ai_toggle.isChecked() else self.ai.parse_query_nonai(q)
        kws, tr, tattr = info["keywords"], info["time_range"], info.get("time_attr","mtime")
        ai_exts=info.get("file_types", [])
        if ai_exts and not allow_exts: allow_exts.extend(['.'+e.lstrip('.') for e in ai_exts])

        # stop any running worker; kick off new search
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption(); self._worker.quit(); self._worker.wait(50)
        self.preview.hide()
        self.spinner.start()
        self._worker=SearchWorker(self._folders, kws, allow_exts, tr, tattr)
        self._worker.results_ready.connect(self._apply_hits)
        self._worker.start()

    def _apply_hits(self, hits: List[FileHit]):
        self.spinner.stop()
        self.model.set_items(hits)
        if hits:
            idx=self.model.index(0); self.list.setCurrentIndex(idx); self.list.scrollTo(idx, QListView.ScrollHint.PositionAtTop)
            self.preview.show()
            self._update_preview()
        else:
            self.preview.hide()

    def _selected_hit(self)->Optional[FileHit]:
        idx=self.list.currentIndex(); return self.model.item(idx.row()) if idx.isValid() else None

    def _open_selected(self):
        h=self._selected_hit()
        if not h: return
        os_open(h.path)

    def _update_preview(self):
        h=self._selected_hit()
        if h: self.preview.set_file(h.path)

    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#wrapper {background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(248,248,248,235), stop:1 rgba(245,245,245,235)); border-radius: 16px; border: 1px solid rgba(0,0,0,0.08);}
        QLineEdit {background: rgba(0,0,0,0.04); border: 1px solid rgba(0,0,0,0.08); border-radius: 10px; padding: 10px 12px; color: #111; selection-background-color: #bcd4ff; font-size: 16px;}
        QComboBox {background: rgba(0,0,0,0.04); border: 1px solid rgba(0,0,0,0.08); border-radius: 10px; padding: 8px 10px; color: #222;}
        QListView {background: transparent; border: none; padding: 4px; color: #222;}
        QListView::item {border-radius: 8px; padding: 6px; margin: 2px 4px;}
        QListView::item:selected {background: rgba(0,0,0,0.06); border: 1px solid rgba(0,0,0,0.12);}
        QLabel#metaHeader {color:#4a4a4a; font-size:14px; font-weight:600; margin: 12px 0 8px 0;}
        QLabel#metaLabel {color:#6f6f6f; font-size:14px;}
        QLabel#metaValue {color:#111; font-size:14px;}
        QWidget#rowContainer {border: none;}
        QFrame#rowSep {background: rgba(0,0,0,0.08); min-height: 1px; max-height: 1px; margin-top: 6px;}
        /* Frameless preview card */
        QFrame#thumbCard {background: transparent; border: none; border-radius: 0px;}
        QSplitter::handle {background: rgba(0,0,0,0.06);}
        """)

# --------------------------------- main --------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Luma")
    ui = SpotlightUI()
    sys.exit(app.exec())
