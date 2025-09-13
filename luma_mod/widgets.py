from __future__ import annotations
import os, tempfile, shutil, subprocess
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QFileInfo
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QGridLayout, QSizePolicy, QCheckBox, QFileIconProvider, QPushButton, QTextEdit

try:
    from .utils import is_macos, find_poppler_bin, FILETYPE_MAP, human_size, elide_middle
except Exception:
    # Fallback for when the module is run without package context
    from luma_mod.utils import is_macos, find_poppler_bin, FILETYPE_MAP, human_size, elide_middle

try:
    from pdf2image import convert_from_path
    HAVE_PDF = True
except Exception:
    HAVE_PDF = False

try:
    from PIL import Image  # noqa: F401
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False


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
        from PyQt6.QtGui import QPainter, QPen
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2,2,-2,-2)
        base = QPen(self.palette().mid().color(), 2)
        hi = QPen(self.palette().highlight().color(), 2)
        p.setPen(base); p.drawArc(rect, 0, 16*360)
        p.setPen(hi); p.drawArc(rect, int(-16*self._angle), 16*110)


class ToggleSwitch(QCheckBox):
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

        self.card = QFrame(); self.card.setObjectName("thumbCard")
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        cLay = QVBoxLayout(self.card); cLay.setContentsMargins(0,0,0,0)
        self.thumb = QLabel(); self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setMinimumSize(0, 0)
        self.thumb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.thumb.setScaledContents(False)
        cLay.addWidget(self.thumb)
        top.addWidget(self.card, 1)

        metaHeader = QLabel("Metadata"); metaHeader.setObjectName("metaHeader")
        self.btn_summarize = QPushButton("Summarize")
        self.btn_summarize.setVisible(False)
        self.btn_summarize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_summarize.setToolTip("Generate a concise summary of this file with the local AI")
        self.btn_summarize.setStyleSheet("padding: 6px 12px; font-weight: 600; border-radius: 8px; background:#3b82f6; color:white;")
        gridWrap = QVBoxLayout(); gridWrap.setSpacing(0)
        self._rows: list[tuple[QLabel, QLabel]] = []
        def add_row(label_text: str):
            row = QGridLayout(); row.setContentsMargins(0,0,0,0); row.setHorizontalSpacing(12)
            l = QLabel(label_text); l.setObjectName("metaLabel")
            v = QLabel("—"); v.setObjectName("metaValue")
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

        metaWrap = QVBoxLayout(); metaWrap.setSpacing(6); metaWrap.setContentsMargins(0,0,0,0)
        headerRow = QHBoxLayout(); headerRow.setContentsMargins(0,0,0,0)
        headerRow.addWidget(metaHeader); headerRow.addStretch(1)
        metaWrap.addLayout(headerRow)
        metaWrap.addLayout(gridWrap)

        root.addLayout(top, 10)
        root.addLayout(metaWrap, 1)
        self._orig_thumb: Optional[QPixmap] = None
        self._orig_orientation: Optional[str] = None
        # Summary section
        sumHeader = QLabel("Summary"); sumHeader.setObjectName("metaHeader")
        sumRow = QHBoxLayout(); sumRow.setContentsMargins(0,0,0,0)
        sumRow.addWidget(sumHeader); sumRow.addStretch(1); sumRow.addWidget(self.btn_summarize)
        root.addLayout(sumRow, 0)
        self.summary = QTextEdit(); self.summary.setReadOnly(True); self.summary.setVisible(False)
        root.addWidget(self.summary, 2)

    def set_file(self, path: Optional[str]):
        self._orig_thumb = None
        self.thumb.clear()
        for _,v in self._rows: v.setText("—")
        self.summary.clear(); self.summary.setVisible(False); self.btn_summarize.setVisible(False)
        if not path: return
        try:
            from os import stat
            st = stat(path)
            ext = os.path.splitext(path)[1].lower()
            self.v_name.setText(os.path.basename(path))
            self.v_where.setText(elide_middle(os.path.dirname(path) or path, 80))
            self.v_type.setText(ext_to_type(ext))
            self.v_size.setText(human_size(st.st_size))
            self.v_tags.setText("—")
            from datetime import datetime
            self.v_created.setText(datetime.fromtimestamp(st.st_mtime).strftime("%d %b %Y at %H:%M:%S"))
        except Exception:
            self.v_where.setText(elide_middle(path,80))

        ext = os.path.splitext(path)[1].lower()
        if HAVE_PIL and ext in FILETYPE_MAP["Images"]:
            pix = QPixmap(path)
            if not pix.isNull():
                self._set_thumb(pix)
                self._orig_orientation = 'landscape' if pix.width() >= pix.height() else 'portrait'
                # Images not summarized by default (OCR not enabled)
                return
        if HAVE_PDF and ext == ".pdf":
            self._show_pdf_thumb(path); self.btn_summarize.setVisible(True); return
        if is_macos() and ext in {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv", ".rtf", ".txt", ".md"}:
            if self._show_quicklook_thumb(path):
                # Show summarize for text and supported office types
                self.btn_summarize.setVisible(ext in {".txt", ".md", ".docx", ".pptx"})
                return
        self._show_generic_icon(path)
        # Show summarize button for selected file; enable guidance via tooltip
        if ext in {".txt",".md",".py",".json",".csv",".log",".yaml",".yml",".ini",".cfg",".toml",".pdf",".docx",".pptx"}:
            self.btn_summarize.setVisible(True)

    def resizeEvent(self, ev):
        super().resizeEvent(ev); self._fit_thumb()
    def _set_thumb(self, pixmap: QPixmap):
        self._orig_thumb = pixmap; self._fit_thumb()
    def _fit_thumb(self):
        if not self._orig_thumb or self._orig_thumb.isNull(): return
        target = self.card.contentsRect().size()
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
        try:
            if not is_macos():
                return False
            dpr = self.devicePixelRatioF()
            size = max(256, min(1024, int(512 * dpr)))
            temp_dir = tempfile.mkdtemp(prefix="luma_ql_")
            try:
                subprocess.run(["qlmanage", "-t", "-s", str(size), "-o", temp_dir, path],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
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
            pix = icon.pixmap(256, 256)
            if pix.isNull(): pix = icon.pixmap(128,128)
            if not pix.isNull():
                self._set_thumb(pix)
                return
        except Exception:
            pass
        self.thumb.setText("No preview")


