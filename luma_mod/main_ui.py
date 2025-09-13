from __future__ import annotations
import os
from typing import Optional, List

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget, QFrame, QLineEdit, QComboBox, QListView, QVBoxLayout, QHBoxLayout, QSplitter, QSizePolicy, QTextEdit, QPushButton, QLabel, QStackedLayout

from .utils import DEFAULT_FOLDERS, FILETYPE_MAP, divider, center_on_screen, os_open
from .widgets import BusySpinner, ToggleSwitch, PreviewPane
from .models import ResultsModel, ResultDelegate, FileHit
from .ai import LumaAI
from .search_core import search_files


class SearchWorker(QThread):
    results_ready = pyqtSignal(list)
    def __init__(self, folders, keywords, allow_exts, time_range, time_attr="mtime"):
        super().__init__(); self.folders=folders; self.keywords=keywords; self.allow_exts=allow_exts; self.time_range=time_range; self.time_attr=time_attr
    def run(self):
        hits=[]
        for path,score in search_files(self.folders, self.keywords, self.allow_exts, self.time_range, self.time_attr):
            try:
                from os import stat
                st=stat(path); hits.append(FileHit(path, int(score), st.st_mtime, st.st_size))
            except Exception: continue
        self.results_ready.emit(hits)


class AIWorker(QThread):
    info_ready = pyqtSignal(dict)
    def __init__(self, ai: LumaAI, query: str, use_ai: bool):
        super().__init__(); self.ai = ai; self.query = query; self.use_ai = use_ai
    def run(self):
        try:
            info = self.ai.parse_query_ai(self.query) if self.use_ai else self.ai.parse_query_nonai(self.query)
        except Exception:
            info = self.ai.parse_query_nonai(self.query)
        self.info_ready.emit(info)


class SpotlightUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Luma (Modular)")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(1000, 640)
        self._folders=DEFAULT_FOLDERS[:]
        self._worker: Optional[SearchWorker]=None
        self._ai_worker: Optional[AIWorker]=None
        self.ai=LumaAI()

        wrapper=QFrame(); wrapper.setObjectName("wrapper")

        self.search=QLineEdit(); self.search.setPlaceholderText("Search files…")
        self.filter=QComboBox(); self.filter.clear(); self.filter.addItems(["User (stv)"])
        self.filter.setMinimumWidth(120)
        self.filter.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ai_toggle = ToggleSwitch("Ask AI")
        self.spinner = BusySpinner(18)
        self.spinner_holder = QWidget(); _sh = QHBoxLayout(self.spinner_holder)
        _sh.setContentsMargins(0,0,0,0); _sh.setSpacing(0); _sh.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.spinner_holder.setFixedSize(28, 24)

        top=QHBoxLayout()
        top.addWidget(self.search,1)
        top.addWidget(self.filter,0)
        top.addStretch(1)
        top.addWidget(self.ai_toggle,0)
        top.addWidget(self.spinner_holder,0)

        self._search_timer = QTimer(self); self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._perform_search)

        self.search.textChanged.connect(self._on_text_changed)
        self.search.returnPressed.connect(self._perform_search)
        self.filter.currentIndexChanged.connect(self._on_filter_changed)
        self.ai_toggle.stateChanged.connect(self._on_ai_toggle)

        self.model=ResultsModel(); self.list=QListView(); self.list.setModel(self.model)
        self.list.setItemDelegate(ResultDelegate()); self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.list.doubleClicked.connect(self._open_selected)
        self.list.selectionModel().selectionChanged.connect(self._update_preview)  # type: ignore

        self.preview=PreviewPane(); self.preview.setVisible(False)
        # Hook summarize button to AI summarization
        self.preview.btn_summarize.clicked.connect(self._summarize_selected)

        leftPane = QFrame(); leftPane.setObjectName("leftPane")
        leftLay = QVBoxLayout(leftPane); leftLay.setContentsMargins(12,12,12,12); leftLay.setSpacing(8)
        leftLay.addWidget(self.list, 1)

        split=QSplitter(); split.addWidget(leftPane); split.addWidget(self.preview)
        split.setStretchFactor(0,3); split.setStretchFactor(1,2)
        split.setSizes([600, 400])

        # Main search page (index 0)
        search_page = QWidget(); search_layout = QVBoxLayout(search_page); search_layout.setContentsMargins(0,0,0,0); search_layout.setSpacing(0)
        search_layout.addLayout(top); search_layout.addWidget(divider()); search_layout.addWidget(split,1)

        # Chat page (index 1)
        self.chat_page = QWidget(); cp_lay = QVBoxLayout(self.chat_page); cp_lay.setContentsMargins(12,12,12,12); cp_lay.setSpacing(8)
        # Header with back arrow and file title
        head = QHBoxLayout();
        self.btn_back = QPushButton("←")
        self.btn_back.setFixedWidth(36)
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setStyleSheet("font-size:18px; font-weight:600; border-radius: 8px; padding:6px 8px;")
        self.lbl_chat_title = QLabel("Ask follow-up…")
        self.lbl_chat_title.setObjectName("metaHeader")
        head.addWidget(self.btn_back, 0); head.addWidget(self.lbl_chat_title, 0); head.addStretch(1)
        # Chat-specific spinner
        self.chat_spinner = BusySpinner(18)
        head.addWidget(self.chat_spinner, 0)
        cp_lay.addLayout(head)
        # Conversation
        self.chat_view = QTextEdit(); self.chat_view.setReadOnly(True)
        self.chat_view.setStyleSheet("QTextEdit {background: rgba(0,0,0,0.04); border: 1px solid rgba(0,0,0,0.08); border-radius: 10px; padding: 10px; color: #111;}")
        cp_lay.addWidget(self.chat_view, 1)
        # Input row
        in_row = QHBoxLayout();
        self.chat_input = QLineEdit(); self.chat_input.setPlaceholderText("Ask follow-up…")
        self.chat_input.setStyleSheet("QLineEdit { color: #111; }")
        self.chat_send = QPushButton("Send")
        self.chat_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chat_send.setStyleSheet("padding: 8px 14px; font-weight:600; border-radius:8px; background:#3b82f6; color:white;")
        in_row.addWidget(self.chat_input, 1); in_row.addWidget(self.chat_send, 0)
        cp_lay.addLayout(in_row)

        # Stacked layout for pages
        self.stack = QStackedLayout()
        self.stack.addWidget(search_page)
        self.stack.addWidget(self.chat_page)
        outer=QVBoxLayout(self); outer.addWidget(wrapper)
        wrapper.setLayout(self.stack)

        self._apply_style(); center_on_screen(self); self.show(); self.search.setFocus()
        self.btn_back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.chat_send.clicked.connect(self._ask_follow_up)

    def _on_text_changed(self, _text: str):
        if self.ai_toggle.isChecked():
            self._search_timer.stop(); return
        self._search_timer.start()
    def _on_filter_changed(self, _=None):
        if self.ai_toggle.isChecked(): return
        self._perform_search()
    def _on_ai_toggle(self, _state: int):
        self._search_timer.stop()
        if self.ai_toggle.isChecked(): self.search.setPlaceholderText("Search files… (press Enter to Ask AI)")
        else: self.search.setPlaceholderText("Search files…")

    def _start_search_with_info(self, info: dict, category: str):
        kws, tr, tattr = info.get("keywords", []), info.get("time_range"), info.get("time_attr","mtime")
        allow_exts = FILETYPE_MAP.get(category, [])[:]
        ai_exts = info.get("file_types", [])
        if ai_exts and not allow_exts:
            allow_exts.extend(['.'+e.lstrip('.') for e in ai_exts])
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption(); self._worker.quit(); self._worker.wait(50)
        self.preview.hide(); self.spinner.start()
        self._worker=SearchWorker(self._folders, kws, allow_exts, tr, tattr)
        self._worker.results_ready.connect(self._apply_hits)
        self._worker.start()

    def _perform_search(self):
        q=self.search.text().strip(); category=self.filter.currentText()
        if self.ai_toggle.isChecked():
            if self._ai_worker and self._ai_worker.isRunning():
                try:
                    self._ai_worker.requestInterruption(); self._ai_worker.quit(); self._ai_worker.wait(50)
                except Exception:
                    pass
            self.spinner.start()
            self._ai_worker = AIWorker(self.ai, q, True)
            self._ai_worker.info_ready.connect(lambda info, c=category: self._start_search_with_info(info, c))
            self._ai_worker.start()
            return
        info = self.ai.parse_query_nonai(q)
        self._start_search_with_info(info, category)

    def _apply_hits(self, hits: List[FileHit]):
        self.spinner.stop(); self.model.set_items(hits)
        if hits:
            idx=self.model.index(0); self.list.setCurrentIndex(idx); self.list.scrollTo(idx, QListView.ScrollHint.PositionAtTop)
            self.preview.show(); self._update_preview()
        else:
            self.preview.hide()

    def _selected_hit(self)->Optional[FileHit]:
        idx=self.list.currentIndex(); return self.model.item(idx.row()) if idx.isValid() else None
    def _open_selected(self):
        h=self._selected_hit();
        if not h: return
        os_open(h.path)
    def _update_preview(self):
        h=self._selected_hit()
        if h: self.preview.set_file(h.path)

    # ---------------- AI Summarization -----------------
    class _SummarizeWorker(QThread):
        summary_ready = pyqtSignal(str)
        def __init__(self, ai: LumaAI, path: str):
            super().__init__(); self.ai=ai; self.path=path
        def run(self):
            try:
                s = self.ai.summarize_file(self.path) or "Summary unavailable. Ensure Ollama is running and text extraction deps installed."
            except Exception:
                s = "Summary failed."
            self.summary_ready.emit(s)

    def _summarize_selected(self):
        h=self._selected_hit()
        if not h: return
        # Open chat page immediately with running indicator
        self._current_chat_file = h.path
        self.lbl_chat_title.setText(os.path.basename(h.path))
        self.chat_view.clear(); self.chat_view.append("Summarizing…\n")
        self.stack.setCurrentIndex(1)
        self.chat_spinner.start()
        self.preview.summary.setVisible(False)
        self._sum_worker = self._SummarizeWorker(self.ai, h.path)
        self._sum_worker.summary_ready.connect(lambda text, path=h.path, name=os.path.basename(h.path): self._open_chat_with_summary(name, path, text))
        self._sum_worker.start()
        # Show a hint if the operation takes too long
        def _slow_hint():
            if getattr(self, "_sum_worker", None) and self._sum_worker.isRunning():
                self.chat_view.append("This is taking longer than usual. Ensure Ollama is running and dependencies are installed.\n")
        QTimer.singleShot(4000, _slow_hint)

    def _open_chat_with_summary(self, name: str, path: str, summary: str):
        self.chat_spinner.stop()
        self._current_chat_file = path
        self.lbl_chat_title.setText(name)
        self.chat_view.clear()
        intro = f"Summary (3 sentences max):\n{summary}\n\n"
        self.chat_view.append(intro)
        self.stack.setCurrentIndex(1)

    class _QnAWorker(QThread):
        answer_ready = pyqtSignal(str)
        def __init__(self, ai: LumaAI, path: str, question: str):
            super().__init__(); self.ai=ai; self.path=path; self.question=question
        def run(self):
            try:
                a = self.ai.answer_about_file(self.path, self.question) or "I am not sure based on the file content."
            except Exception:
                a = "Question failed."
            self.answer_ready.emit(a)

    def _ask_follow_up(self):
        q = self.chat_input.text().strip()
        if not q or not getattr(self, "_current_chat_file", None):
            return
        self.chat_input.clear()
        self.chat_view.append(f"You: {q}\n")
        self.chat_view.append("AI is thinking…\n")
        self.chat_spinner.start()
        self._qa_worker = self._QnAWorker(self.ai, self._current_chat_file, q)
        self._qa_worker.answer_ready.connect(self._apply_answer)
        self._qa_worker.start()

    def _apply_answer(self, a: str):
        self.chat_spinner.stop(); self.chat_view.append(f"AI: {a}\n")

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
        QFrame#thumbCard {background: transparent; border: none; border-radius: 0px;}
        QSplitter::handle {background: rgba(0,0,0,0.06);}
        """)


