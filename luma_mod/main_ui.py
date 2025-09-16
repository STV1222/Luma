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
from .i18n import get_translation_manager, tr


class SearchWorker(QThread):
    results_ready = pyqtSignal(list)
    def __init__(self, folders, keywords, allow_exts, time_range, time_attr="mtime", semantic_keywords=None, file_patterns=None):
        super().__init__(); 
        self.folders=folders; self.keywords=keywords; self.allow_exts=allow_exts; 
        self.time_range=time_range; self.time_attr=time_attr
        self.semantic_keywords=semantic_keywords or []; self.file_patterns=file_patterns or []
    def run(self):
        hits=[]
        for path,score in search_files(self.folders, self.keywords, self.allow_exts, self.time_range, self.time_attr, self.semantic_keywords, self.file_patterns):
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


class RerankWorker(QThread):
    reranked = pyqtSignal(list)
    def __init__(self, ai: LumaAI, query: str, hits: List[FileHit], time_window=None, file_types=None, folders=None):
        super().__init__(); self.ai=ai; self.query=query; self.hits=hits
        self.time_window=time_window; self.file_types=file_types; self.folders=folders
    def run(self):
        try:
            paths = [h.path for h in self.hits][:30]
            scores = self.ai.rerank_by_name(self.query, paths, self.time_window, self.file_types, self.folders) or {}
            if not scores:
                self.reranked.emit(self.hits); return
            def boosted(h: FileHit) -> FileHit:
                extra = float(scores.get(h.path, 0.0))
                return FileHit(h.path, h.score + int(extra), h.mtime, h.size)
            new_hits = sorted([boosted(h) for h in self.hits], key=lambda x: x.score, reverse=True)
            self.reranked.emit(new_hits)
        except Exception:
            self.reranked.emit(self.hits)


class SpotlightUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Luma (Modular)")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(700, 160)  # Increased height to prevent squeezing
        self.setMaximumSize(700, 800)  # Keep consistent width, only height changes
        self._folders=DEFAULT_FOLDERS[:]
        self._worker: Optional[SearchWorker]=None
        self._ai_worker: Optional[AIWorker]=None
        # Initialize AI with default mode and API key
        self.openai_api_key = "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"
        self.ai_mode = "none"  # "none", "private", or "cloud"
        self.ai=LumaAI(mode="private", openai_api_key=self.openai_api_key)  # Initialize with private mode but won't be used until selected

        wrapper=QWidget(); wrapper.setObjectName("wrapper")

        # Create integrated search bar container
        self.search_container = QWidget()
        self.search_container.setObjectName("searchContainer")
        self.search_container.setMinimumHeight(60)  # Ensure container has proper height
        search_layout = QHBoxLayout(self.search_container)
        search_layout.setContentsMargins(12, 12, 12, 12)  # Add internal padding to prevent squeezing
        search_layout.setSpacing(0)
        
        # Main search input
        self.search=QLineEdit()
        self.search.setPlaceholderText("Search for apps and commands...")
        self.search.setObjectName("mainSearch")
        self.search.setMinimumHeight(36)  # Ensure minimum height to prevent squeezing
        
        # AI mode selector (integrated into search bar)
        self.ai_mode_button = QPushButton("Ask AI")
        self.ai_mode_button.setObjectName("aiModeButton")
        self.ai_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ai_mode_button.setCheckable(True)
        self.ai_mode_button.setFixedWidth(90)
        
        # Spinner holder for loading animation (replaces Tab button)
        self.spinner_holder = QWidget()
        self.spinner_holder.setObjectName("spinnerHolder")
        spinner_layout = QHBoxLayout(self.spinner_holder)
        spinner_layout.setContentsMargins(0, 0, 0, 0)
        spinner_layout.setSpacing(0)
        self.spinner_holder.setFixedWidth(50)
        
        # Add settings button to search bar (custom logo)
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("settingsButton")
        self.settings_btn.setFixedWidth(50)
        self.settings_btn.setFixedHeight(40)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.clicked.connect(self._show_settings)
        
        # Set the custom logo as icon
        logo_path = os.path.join(os.path.dirname(__file__), "..", "IMG", "logo3.png")
        if os.path.exists(logo_path):
            from PyQt6.QtGui import QIcon, QPixmap
            from PyQt6.QtCore import QSize
            icon = QIcon(logo_path)
            self.settings_btn.setIcon(icon)
            # Set icon size to 24x24 pixels
            self.settings_btn.setIconSize(QSize(24, 24))
        else:
            # Fallback to gear icon if logo not found
            self.settings_btn.setText("⚙")
        
        # Add widgets to search container
        search_layout.addWidget(self.search, 1)
        search_layout.addWidget(self.ai_mode_button, 0)
        search_layout.addWidget(self.spinner_holder, 0)
        search_layout.addWidget(self.settings_btn, 0)
        
        # Create dropdown menu for AI modes as a popup window
        self.ai_dropdown = QWidget()
        self.ai_dropdown.setObjectName("aiDropdown")
        self.ai_dropdown.setVisible(False)
        self.ai_dropdown.setFixedSize(160, 120)  # Larger size for better visibility
        self.ai_dropdown.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Popup | 
            Qt.WindowType.WindowStaysOnTopHint
        )
        # Enable popup behavior - can extend outside parent widget
        
        dropdown_layout = QVBoxLayout(self.ai_dropdown)
        dropdown_layout.setContentsMargins(8, 8, 8, 8)
        dropdown_layout.setSpacing(0)
        
        # Create AI mode buttons
        self.no_ai_btn = QPushButton("No AI")
        self.no_ai_btn.setObjectName("dropdownOption")
        self.no_ai_btn.clicked.connect(lambda: self._set_ai_mode("No AI"))
        
        self.private_mode_btn = QPushButton("Private Mode")
        self.private_mode_btn.setObjectName("dropdownOption")
        self.private_mode_btn.clicked.connect(lambda: self._set_ai_mode("Private Mode"))
        
        self.cloud_mode_btn = QPushButton("Cloud Mode")
        self.cloud_mode_btn.setObjectName("dropdownOption")
        self.cloud_mode_btn.clicked.connect(lambda: self._set_ai_mode("Cloud Mode"))
        
        dropdown_layout.addWidget(self.no_ai_btn)
        dropdown_layout.addWidget(self.private_mode_btn)
        dropdown_layout.addWidget(self.cloud_mode_btn)
        
        # Spinner for loading states (now in the spinner holder)
        self.spinner = BusySpinner(16)  # Slightly smaller for the compact space
        spinner_layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        # Main top layout
        top=QVBoxLayout()
        top.setContentsMargins(24, 24, 24, 24)
        top.setSpacing(0)
        top.addWidget(self.search_container, 0)
        # Note: ai_dropdown is now positioned as overlay, not in layout

        self._search_timer = QTimer(self); self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._perform_search)

        self.search.textChanged.connect(self._on_text_changed)
        self.search.returnPressed.connect(self._perform_search)
        self.ai_mode_button.clicked.connect(self._toggle_ai_dropdown)
        # Remove hover events from button - only click should show dropdown
        
        # Add hover events to the dropdown itself to keep it open when hovering over it
        self.ai_dropdown.enterEvent = self._on_dropdown_hover
        self.ai_dropdown.leaveEvent = self._on_dropdown_leave

        self.model=ResultsModel(); self.list=QListView(); self.list.setModel(self.model)
        self.list.setItemDelegate(ResultDelegate()); self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.list.doubleClicked.connect(self._open_selected)
        self.list.selectionModel().selectionChanged.connect(self._update_preview)  # type: ignore

        self.preview=PreviewPane(); self.preview.setVisible(False)
        # Hook summarize button to summarization (fast extractive or deep LLM)
        self.preview.btn_summarize.clicked.connect(self._summarize_selected)

        leftPane = QFrame(); leftPane.setObjectName("leftPane")
        leftLay = QVBoxLayout(leftPane); leftLay.setContentsMargins(0,0,0,0); leftLay.setSpacing(8)
        leftLay.addWidget(self.list, 1)

        self.split=QSplitter(); self.split.addWidget(leftPane); self.split.addWidget(self.preview)
        self.split.setStretchFactor(0,3); self.split.setStretchFactor(1,2)
        self.split.setSizes([600, 400])
        self.split.setVisible(False)  # Initially hidden when no search input

        # Main search page (index 0)
        search_page = QWidget(); search_layout = QVBoxLayout(search_page); search_layout.setContentsMargins(0,0,0,0); search_layout.setSpacing(0)
        
        # Top section with search bar and dropdown
        top_section = QWidget()
        top_section_layout = QVBoxLayout(top_section)
        top_section_layout.setContentsMargins(0,0,0,0)
        top_section_layout.setSpacing(0)
        top_section_layout.addLayout(top)
        
        # Bottom section with results panel
        bottom_section = QWidget()
        bottom_section_layout = QVBoxLayout(bottom_section)
        bottom_section_layout.setContentsMargins(24, 0, 24, 24)  # Match search bar margins
        bottom_section_layout.setSpacing(0)
        self.search_divider = divider()
        self.search_divider.setVisible(False)  # Initially hidden when no search input
        bottom_section_layout.addWidget(self.search_divider)
        bottom_section_layout.addWidget(self.split,1)
        
        # Add both sections to main layout
        search_layout.addWidget(top_section, 0)  # Fixed size for top section
        search_layout.addWidget(bottom_section, 1)  # Expandable for bottom section

        # Chat page (index 1) - Conversation Dialog
        self.chat_page = QWidget()
        cp_lay = QVBoxLayout(self.chat_page)
        cp_lay.setContentsMargins(0, 0, 0, 0)
        cp_lay.setSpacing(0)
        
        # Header with back arrow and input box (matching main page style)
        header_widget = QWidget()
        header_widget.setObjectName("chatHeader")
        header_widget.setFixedHeight(60)
        head = QHBoxLayout(header_widget)
        head.setContentsMargins(20, 20, 20, 20)  # Reduced margins to give more space
        head.setSpacing(12)  # Increased spacing between elements
        
        # Back arrow button (minimal style)
        self.btn_back = QPushButton("←")
        self.btn_back.setFixedWidth(40)
        self.btn_back.setFixedHeight(36)
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.setObjectName("chatBackButton")
        
        # Main input box in header (matching main search style)
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Ask AI anything...")
        self.chat_input.setObjectName("mainChatInput")
        self.chat_input.setMinimumHeight(36)
        self.chat_input.setMaximumWidth(400)  # Limit maximum width to prevent pushing mode display off screen
        self.chat_input.returnPressed.connect(self._ask_follow_up)
        
        # Mode display (matching main page style)
        self.mode_display = QLabel("No AI")
        self.mode_display.setObjectName("chatModeDisplay")
        self.mode_display.setFixedWidth(140)  # Further increased width
        self.mode_display.setFixedHeight(36)  # Match other elements height
        self.mode_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_display.setMinimumWidth(140)  # Ensure minimum width
        
        # Spinner holder for loading animation
        self.chat_spinner_holder = QWidget()
        self.chat_spinner_holder.setObjectName("chatSpinnerHolder")
        self.chat_spinner_holder.setFixedWidth(30)  # Further reduced width
        self.chat_spinner_holder.setFixedHeight(36)  # Match other elements height
        self.chat_spinner_holder.setMinimumWidth(30)
        chat_spinner_layout = QHBoxLayout(self.chat_spinner_holder)
        chat_spinner_layout.setContentsMargins(0, 0, 0, 0)
        chat_spinner_layout.setSpacing(0)
        
        # Chat-specific spinner
        self.chat_spinner = BusySpinner(14)  # Smaller spinner
        chat_spinner_layout.addWidget(self.chat_spinner, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Add widgets with proper sizing
        head.addWidget(self.btn_back, 0)  # Fixed size
        head.addWidget(self.chat_input, 1)  # Flexible size
        head.addWidget(self.mode_display, 0)  # Fixed size
        head.addWidget(self.chat_spinner_holder, 0)  # Fixed size
        
        cp_lay.addWidget(header_widget)
        
        # Main conversation area with splitter for chat and preview
        conversation_splitter = QSplitter(Qt.Orientation.Horizontal)
        conversation_splitter.setObjectName("conversationSplitter")
        
        # Left side: Conversation history
        conversation_widget = QWidget()
        conversation_widget.setObjectName("conversationWidget")
        conv_layout = QVBoxLayout(conversation_widget)
        conv_layout.setContentsMargins(16, 16, 8, 16)
        conv_layout.setSpacing(0)
        
        # Conversation view with scrollable chat history
        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)
        self.chat_view.setObjectName("conversationView")
        self.chat_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chat_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        conv_layout.addWidget(self.chat_view, 1)
        
        # Right side: Preview pane (integrated)
        self.conversation_preview = PreviewPane()
        self.conversation_preview.setObjectName("conversationPreview")
        self.conversation_preview.setVisible(False)
        
        # Add widgets to splitter
        conversation_splitter.addWidget(conversation_widget)
        conversation_splitter.addWidget(self.conversation_preview)
        conversation_splitter.setStretchFactor(0, 2)
        conversation_splitter.setStretchFactor(1, 1)
        conversation_splitter.setSizes([400, 300])
        
        cp_lay.addWidget(conversation_splitter, 1)

        # Settings page (index 2)
        self.settings_page = QWidget()
        settings_layout = QVBoxLayout(self.settings_page)
        settings_layout.setContentsMargins(24, 24, 24, 24)
        settings_layout.setSpacing(20)
        
        # Header with back arrow and settings title
        settings_head = QHBoxLayout()
        self.btn_settings_back = QPushButton("←")
        self.btn_settings_back.setFixedWidth(36)
        self.btn_settings_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings_back.setStyleSheet("font-size:18px; font-weight:600; border-radius: 8px; padding:6px 8px;")
        self.lbl_settings_title = QLabel("Settings")
        self.lbl_settings_title.setObjectName("metaHeader")
        settings_head.addWidget(self.btn_settings_back, 0)
        settings_head.addWidget(self.lbl_settings_title, 0)
        settings_head.addStretch(1)
        settings_layout.addLayout(settings_head)
        
        # Language selection section
        language_section = QFrame()
        language_section.setObjectName("settingsSection")
        language_section.setMinimumHeight(220)  # Further increased height
        language_layout = QVBoxLayout(language_section)
        language_layout.setContentsMargins(24, 40, 24, 40)  # Even more top/bottom margins
        language_layout.setSpacing(28)  # Increased spacing
        
        self.lbl_language = QLabel("Language")
        self.lbl_language.setObjectName("settingsLabel")
        self.lbl_language.setMinimumHeight(48)  # Further increased height
        self.lbl_language.setContentsMargins(0, 12, 0, 12)  # More internal padding
        language_layout.addWidget(self.lbl_language)
        
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("settingsCombo")
        self.language_combo.setMinimumHeight(50)
        self.language_combo.setMaximumHeight(50)
        # Populate with available languages
        self._populate_language_combo()
        language_layout.addWidget(self.language_combo)
        
        # Add description text
        desc_label = QLabel("Select your preferred language for the interface")
        desc_label.setObjectName("settingsDescription")
        desc_label.setWordWrap(True)
        language_layout.addWidget(desc_label)
        
        # Add some spacing
        language_layout.addStretch(1)
        
        settings_layout.addWidget(language_section)
        
        # Add more spacing between sections
        settings_layout.addSpacing(20)
        
        # Add a placeholder for future settings
        future_section = QFrame()
        future_section.setObjectName("settingsSection")
        future_section.setMinimumHeight(120)
        future_layout = QVBoxLayout(future_section)
        future_layout.setContentsMargins(24, 24, 24, 24)
        future_layout.setSpacing(16)
        
        future_label = QLabel("More Settings")
        future_label.setObjectName("settingsLabel")
        future_layout.addWidget(future_label)
        
        future_desc = QLabel("Additional settings will be available in future updates")
        future_desc.setObjectName("settingsDescription")
        future_desc.setWordWrap(True)
        future_layout.addWidget(future_desc)
        
        settings_layout.addWidget(future_section)
        settings_layout.addStretch(1)  # Push content to top

        # Stacked layout for pages
        self.stack = QStackedLayout()
        self.stack.addWidget(search_page)
        self.stack.addWidget(self.chat_page)
        self.stack.addWidget(self.settings_page)
        outer=QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)  
        outer.setSpacing(0)
        outer.addWidget(wrapper)
        wrapper.setLayout(self.stack)

        # Initialize search folders based on default scope
        self._update_search_folders()
        
        # Set initial AI mode (after stack is created)
        self._set_ai_mode("No AI")
        
        self._apply_style(); center_on_screen(self)
        self.resize(700, 160)  # Start in collapsed state (with proper height)
        self.show(); self.search.setFocus()
        
        # Dropdown is now a popup window - no parent relationship needed
        # Warm up local AI model in the background to avoid first-call delay
        try:
            QTimer.singleShot(50, self._warmup_ai)
        except Exception:
            pass
        self.btn_back.clicked.connect(self._go_back_from_conversation)
        self.btn_settings_back.clicked.connect(self._hide_settings)
        self.language_combo.currentTextChanged.connect(self._on_language_changed)
        
        # Initialize translations and update UI texts (after all UI elements are created)
        self._update_ui_texts()

    def _on_text_changed(self, text: str):
        # Handle UI visibility based on search input
        has_input = bool(text.strip())
        
        # If there's input, show normal search interface
        if has_input:
            # Hide no results widget if it's showing
            if hasattr(self, 'no_results_widget'):
                self.no_results_widget.setVisible(False)
            
            # Show/hide the main content area (files list and preview)
            self.search_divider.setVisible(True)
            self.split.setVisible(True)
            
            # Expand to show files and preview - keep same width, only change height
            current_width = self.width()
            self.resize(current_width, 640)
            self.setMinimumSize(current_width, 500)
            self.setMaximumSize(700, 800)  # Restore maximum size when expanded
            
            # Only auto-search for "no AI" mode - AI modes require Enter key
            if self.ai_mode == "none":
                self._perform_search()
        else:
            # When search bar is cleared, always collapse to initial size
            # Hide no results widget if it exists
            if hasattr(self, 'no_results_widget'):
                self.no_results_widget.setVisible(False)
            
            # Collapse to show only search bar - ensure exact starting size
            self.resize(700, 160)
            self.setMinimumSize(700, 160)
            self.setMaximumSize(700, 160)  # Lock size when collapsed
            # Clear any existing results when search is empty
            self.model.set_items([])
            self.preview.hide()
            # Stop any running workers and spinner
            self.spinner.stop()
            if self._worker and self._worker.isRunning():
                self._worker.requestInterruption()
                self._worker.quit()
                self._worker.wait(50)
            if self._ai_worker and self._ai_worker.isRunning():
                self._ai_worker.requestInterruption()
                self._ai_worker.quit()
                self._ai_worker.wait(50)
        
        # Only use timer for non-AI modes (No AI)
        if self.ai_mode == "none":
            self._search_timer.start()
        else:
            self._search_timer.stop()
    
    def _update_search_folders(self):
        """Update search folders to use default user directories."""
        # Always search only user directories
        self._folders = DEFAULT_FOLDERS[:]

    def _position_dropdown(self):
        """Position the dropdown popup relative to the AI button."""
        if not self.ai_dropdown.isVisible():
            return
        
        # Get the AI button's global position
        ai_button_global_pos = self.ai_mode_button.mapToGlobal(self.ai_mode_button.rect().bottomLeft())
        
        # Position dropdown as a popup window below the AI button
        self.ai_dropdown.move(ai_button_global_pos.x(), ai_button_global_pos.y() + 4)
    
    def _toggle_ai_dropdown(self):
        """Toggle the AI dropdown menu visibility (click-only behavior)."""
        is_visible = self.ai_dropdown.isVisible()
        
        if is_visible:
            # Hide dropdown
            self.ai_dropdown.setVisible(False)
            # Cancel any pending hide timer
            if hasattr(self, '_dropdown_hide_timer'):
                self._dropdown_hide_timer.stop()
        else:
            # Show dropdown
            self.ai_dropdown.setVisible(True)
            self._position_dropdown()
            # Cancel any pending hide timer when showing
            if hasattr(self, '_dropdown_hide_timer'):
                self._dropdown_hide_timer.stop()
    
    def _on_dropdown_hover(self, event):
        """Keep dropdown open when hovering over it."""
        # Cancel any pending hide timer
        if hasattr(self, '_dropdown_hide_timer'):
            self._dropdown_hide_timer.stop()
        # Call the parent class enterEvent properly
        QWidget.enterEvent(self.ai_dropdown, event)
    
    def _on_dropdown_leave(self, event):
        """Hide dropdown when leaving dropdown area."""
        # Use a timer to delay hiding to allow moving back to dropdown
        self._dropdown_hide_timer = QTimer()
        self._dropdown_hide_timer.setSingleShot(True)
        self._dropdown_hide_timer.timeout.connect(lambda: self.ai_dropdown.setVisible(False))
        self._dropdown_hide_timer.start(200)
        # Call the parent class leaveEvent properly
        QWidget.leaveEvent(self.ai_dropdown, event)
    
    def _set_ai_mode(self, mode_text: str):
        """Handle mode change between No AI, Private (local AI), and Cloud (OpenAI API) modes."""
        self._search_timer.stop()
        self.ai_dropdown.setVisible(False)  # Hide dropdown after selection
        
        # Update button text and styling based on mode
        if mode_text == "No AI":
            self.ai_mode = "none"
            # Switch back to search page
            self.stack.setCurrentIndex(0)
            self._clear_conversation()
        elif mode_text == "Private Mode":
            self.ai_mode = "private"
            # Reinitialize AI with private mode
            self.ai = LumaAI(mode=self.ai_mode, openai_api_key=self.openai_api_key)
            # Switch to conversation page
            self._switch_to_conversation_mode()
            # Warm up the AI mode
            try:
                QTimer.singleShot(50, self._warmup_ai)
            except Exception:
                pass
        elif mode_text == "Cloud Mode":
            self.ai_mode = "cloud"
            # Reinitialize AI with cloud mode
            self.ai = LumaAI(mode=self.ai_mode, openai_api_key=self.openai_api_key)
            # Switch to conversation page
            self._switch_to_conversation_mode()
            # Warm up the AI mode
            try:
                QTimer.singleShot(50, self._warmup_ai)
            except Exception:
                pass
        
        # Reset search state when AI mode changes
        self._has_searched = False
        
        # Update UI texts with current language (preserves language selection)
        self._update_ui_texts()

    def _start_search_with_info(self, info: dict, category: str):
        kws, tr, tattr = info.get("keywords", []), info.get("time_range"), info.get("time_attr","mtime")
        # Optional folder narrowing from parsing stage — if folders present, use them and drop folder words from keywords
        folders = info.get("folders") or []
        target_folders = folders if folders else self._folders
        if folders and kws:
            # Remove folder-like tokens to avoid filtering away files by ext match
            import re
            kws = [w for w in kws if not re.fullmatch(r"folder|folders|dir|directory", w, re.IGNORECASE)]
        allow_exts = FILETYPE_MAP.get(category, [])[:]
        ai_exts = info.get("file_types", [])
        
        # Special case: If user is searching for files in a specific folder without explicit file type,
        # show all items (files and folders) in that folder
        if folders and not ai_exts and not kws:
            # User is browsing a specific folder without file type constraints
            # Show all items including folders
            allow_exts = []
        # Also show folders when searching for folder names (like "career" search)
        elif not ai_exts and kws:
            # User is doing keyword search without file type constraints - include folders
            allow_exts = []
        elif ai_exts:
            # Always apply AI file type filtering when specified, regardless of folder scope
            allow_exts.extend(['.'+e.lstrip('.') for e in ai_exts])
        
        # Get AI understanding for intelligent search
        semantic_keywords = info.get("semantic_keywords", [])
        file_patterns = info.get("file_name_patterns", [])
        
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption(); self._worker.quit(); self._worker.wait(50)
        self.preview.hide(); self.spinner.start()
        # Store metadata for reranker guardrails
        self._last_time_range = tr
        self._last_file_types = allow_exts
        self._last_folders = target_folders
        
        self._worker=SearchWorker(target_folders, kws, allow_exts, tr, tattr, semantic_keywords, file_patterns)
        if self.ai_mode != "none":
            self._worker.results_ready.connect(lambda hits, q=self.search.text().strip(): self._maybe_rerank(q, hits))
        else:
            self._worker.results_ready.connect(self._apply_hits)
        self._worker.start()

    def _perform_search(self):
        q=self.search.text().strip()
        
        # Don't perform search if query is empty - this ensures UI stays collapsed
        if not q:
            return
        
        if self.ai_mode == "none":
            # Use non-AI keyword-based search
            info = self.ai.parse_query_nonai(q)
            self._start_search_with_info(info, "User")
        else:
            # For AI modes, switch to conversation and handle the query there
            self._switch_to_conversation_mode()
            self._handle_ai_query(q)

    def _switch_to_conversation_mode(self):
        """Switch to conversation mode and update UI accordingly."""
        self.stack.setCurrentIndex(1)
        self._update_conversation_mode_indicator()
        # Show placeholder text
        self._show_ask_anything_placeholder()
        # Resize window for conversation mode
        self.resize(900, 600)
        self.setMinimumSize(900, 600)
        self.setMaximumSize(1200, 800)
        
    def _update_conversation_mode_indicator(self):
        """Update the mode indicator in conversation header."""
        if self.ai_mode == "private":
            self.mode_display.setText("🔒 Private Mode")
            self.mode_display.setStyleSheet("color: #10b981; font-weight: 500;")
        elif self.ai_mode == "cloud":
            self.mode_display.setText("☁️ Cloud Mode")
            self.mode_display.setStyleSheet("color: #3b82f6; font-weight: 500;")
        else:
            self.mode_display.setText("No AI")
            self.mode_display.setStyleSheet("color: #6b7280; font-weight: 500;")
    
    def _clear_conversation(self):
        """Clear the conversation history."""
        self.chat_view.clear()
        self.conversation_preview.hide()
        self._current_chat_file = None
        self._show_ask_anything_placeholder()
    
    def _show_ask_anything_placeholder(self):
        """Show the 'Ask Anything' placeholder text in the conversation view."""
        self.chat_view.setHtml("""
        <div style="display: flex; align-items: center; justify-content: center; height: 100%; min-height: 300px;">
            <div style="text-align: center;">
                <div style="font-size: 24px; font-weight: 600; color: #1e293b; margin-bottom: 8px;">Ask Anything</div>
            </div>
        </div>
        """)
        
    def _handle_ai_query(self, query: str):
        """Handle AI query in conversation mode."""
        if not query.strip():
            return
            
        # Add user query to conversation
        self._add_user_message(query)
        
        # Show loading indicator
        self.chat_spinner.start()
        self.chat_view.append("AI is thinking…\n")
        
        # Process the query with AI
        if self._ai_worker and self._ai_worker.isRunning():
            try:
                self._ai_worker.requestInterruption()
                self._ai_worker.quit()
                self._ai_worker.wait(50)
            except Exception:
                pass
                
        self._ai_worker = AIWorker(self.ai, query, True)
        self._ai_worker.info_ready.connect(self._handle_ai_response)
        self._ai_worker.start()
        
    def _add_user_message(self, message: str):
        """Add user message to conversation."""
        self.chat_view.append(f"<div style='margin-bottom: 12px;'>")
        self.chat_view.append(f"<div style='background: #3b82f6; color: white; padding: 8px 12px; border-radius: 12px 12px 4px 12px; display: inline-block; max-width: 80%; margin-left: 20%;'>")
        self.chat_view.append(f"<strong>You:</strong> {message}")
        self.chat_view.append(f"</div></div>")
        
    def _add_ai_message(self, message: str):
        """Add AI message to conversation."""
        self.chat_view.append(f"<div style='margin-bottom: 12px;'>")
        self.chat_view.append(f"<div style='background: #f1f5f9; color: #1e293b; padding: 8px 12px; border-radius: 12px 12px 12px 4px; display: inline-block; max-width: 80%; margin-right: 20%;'>")
        self.chat_view.append(f"<strong>AI:</strong> {message}")
        self.chat_view.append(f"</div></div>")
        
    def _show_ai_understanding(self, info: dict):
        """Show AI's understanding of user intent to the user."""
        user_intent = info.get("user_intent", "")
        search_strategy = info.get("search_strategy", "")
        confidence = info.get("confidence", 0)
        reasoning = info.get("reasoning", "")
        
        if user_intent and user_intent != "unknown":
            # Show understanding in a special format
            self.chat_view.append(f"<div style='margin-bottom: 12px;'>")
            self.chat_view.append(f"<div style='background: #fef3c7; color: #92400e; padding: 12px; border-radius: 12px; border-left: 4px solid #f59e0b; margin-right: 20%;'>")
            self.chat_view.append(f"<div style='font-weight: 600; margin-bottom: 8px;'>🧠 AI Understanding:</div>")
            self.chat_view.append(f"<div style='margin-bottom: 6px;'><strong>Intent:</strong> {user_intent}</div>")
            if search_strategy and search_strategy != "unknown":
                self.chat_view.append(f"<div style='margin-bottom: 6px;'><strong>Strategy:</strong> {search_strategy}</div>")
            if confidence > 0:
                confidence_color = "#10b981" if confidence >= 80 else "#f59e0b" if confidence >= 60 else "#ef4444"
                self.chat_view.append(f"<div style='margin-bottom: 6px;'><strong>Confidence:</strong> <span style='color: {confidence_color};'>{confidence}%</span></div>")
            if reasoning and reasoning != "unknown":
                self.chat_view.append(f"<div style='font-size: 0.9em; color: #6b7280;'><strong>Reasoning:</strong> {reasoning}</div>")
            self.chat_view.append(f"</div></div>")
        
    def _handle_ai_response(self, info: dict):
        """Handle AI response and show results in conversation."""
        self.chat_spinner.stop()
        
        # Remove the "AI is thinking..." message
        cursor = self.chat_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        if "AI is thinking…" in cursor.selectedText():
            cursor.removeSelectedText()
            cursor.deletePreviousChar()
        
        # Show AI's understanding to the user
        self._show_ai_understanding(info)
        
        # Start search with AI info
        self._start_search_with_info(info, "User")
        
    def _apply_hits(self, hits: List[FileHit]):
        self.spinner.stop()
        
        # Mark that a search has been performed
        self._has_searched = True
        
        if hits:
            # Hide no results widget if it exists
            if hasattr(self, 'no_results_widget'):
                self.no_results_widget.setVisible(False)
            
            if self.ai_mode in ["private", "cloud"]:
                # In conversation mode, show results in conversation and preview
                self._show_results_in_conversation(hits)
            else:
                # In search mode, show traditional file list
                self.model.set_items(hits)
                # Ensure UI is expanded when results are found - keep consistent width
                self.search_divider.setVisible(True)
                self.split.setVisible(True)
                current_width = self.width()
                self.resize(current_width, 640)
                self.setMinimumSize(current_width, 500)
                self.setMaximumSize(current_width, 800)  # Reset max size
                
                idx=self.model.index(0); self.list.setCurrentIndex(idx); self.list.scrollTo(idx, QListView.ScrollHint.PositionAtTop)
                self.preview.show(); self._update_preview()
        else:
            if self.ai_mode in ["private", "cloud"]:
                # In conversation mode, show no results message
                self._add_ai_message("No files found matching your query. Try different keywords or time ranges.")
            else:
                # Hide panels and show simple no results message
                self.search_divider.setVisible(False)
                self.split.setVisible(False)
                current_width = self.width()
                self.resize(current_width, 300)  # Increased height for no results
                self.setMinimumSize(current_width, 300)
                self.setMaximumSize(current_width, 300)
                self._show_no_results_message()

    def _show_no_results_message(self):
        """Display a 'no results found' message in a clean centered layout"""
        # Hide the preview panel
        self.preview.hide()
        
        # Create a simple no results widget if it doesn't exist
        if not hasattr(self, 'no_results_widget'):
            self.no_results_widget = QWidget()
            self.no_results_widget.setObjectName("noResultsWidget")
            self.no_results_widget.setStyleSheet("""
                QWidget#noResultsWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #ffffff, stop:1 #f8fafc);
                    min-height: 200px;
                }
            """)
            
            layout = QVBoxLayout(self.no_results_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Create the no results content
            content_widget = QWidget()
            content_layout = QVBoxLayout(content_widget)
            content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            content_layout.setSpacing(20)
            
            # Icon
            icon_label = QLabel("🔍")
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_label.setStyleSheet("""
                QLabel {
                    font-size: 36px;
                    color: #9ca3af;
                    margin-bottom: 8px;
                }
            """)
            
            # Title
            title_label = QLabel(tr("no_results_found"))
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_label.setStyleSheet("""
                QLabel {
                    font-size: 20px;
                    font-weight: 600;
                    color: #374151;
                    margin-bottom: 6px;
                }
            """)
            
            # Message
            message_label = QLabel(tr("no_results_suggestion"))
            message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            message_label.setWordWrap(True)
            message_label.setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    color: #6b7280;
                    line-height: 1.4;
                    max-width: 350px;
                    padding: 0 20px;
                }
            """)
            
            content_layout.addWidget(icon_label)
            content_layout.addWidget(title_label)
            content_layout.addWidget(message_label)
            
            layout.addWidget(content_widget)
            
            # Add to search page layout - insert after the top section
            search_page = self.stack.widget(0)  # Get the search page
            search_layout = search_page.layout()
            # Insert the no results widget after the top section (index 1)
            search_layout.insertWidget(1, self.no_results_widget)
        
        # Show the no results widget
        self.no_results_widget.setVisible(True)
    
    def _show_results_in_conversation(self, hits: List[FileHit]):
        """Show search results in conversation mode."""
        # Add AI response with results
        result_count = len(hits)
        if result_count == 1:
            message = f"Found 1 file matching your query:"
        else:
            message = f"Found {result_count} files matching your query:"
        
        self._add_ai_message(message)
        
        # Create a simple file list in the conversation
        file_list_html = "<div style='margin: 8px 0; padding: 8px; background: #f8fafc; border-radius: 8px; border-left: 3px solid #3b82f6;'>"
        for i, hit in enumerate(hits):  # Show all results
            file_name = os.path.basename(hit.path)
            file_size = self._format_file_size(hit.size)
            file_date = self._format_file_date(hit.mtime)
            
            file_list_html += f"""
            <div style='margin: 4px 0; padding: 6px; background: white; border-radius: 6px; cursor: pointer; border: 1px solid #e2e8f0;' 
                 onclick='selectFile("{hit.path}")'>
                <div style='font-weight: 600; color: #1e293b;'>{file_name}</div>
                <div style='font-size: 12px; color: #64748b; margin-top: 2px;'>{file_size} • {file_date}</div>
            </div>
            """
        
        # Removed truncation - show all files
        
        file_list_html += "</div>"
        
        self.chat_view.append(file_list_html)
        
        # Show preview for first file
        if hits:
            self.conversation_preview.set_file(hits[0].path)
            self.conversation_preview.show()
            self._current_conversation_hits = hits
            self._current_selected_index = 0
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Format file size in human readable format."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def _format_file_date(self, timestamp: float) -> str:
        """Format file date in human readable format."""
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        now = datetime.now()
        diff = now - dt
        
        if diff.days == 0:
            return f"Today {dt.strftime('%H:%M')}"
        elif diff.days == 1:
            return f"Yesterday {dt.strftime('%H:%M')}"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        else:
            return dt.strftime('%Y-%m-%d')

    def _maybe_rerank(self, query: str, hits: List[FileHit]):
        # Skip LLM rerank when there are no keywords (pure date queries)
        # Only rerank when there are semantic keywords to work with
        if not query.strip() or not any(word.strip() for word in query.split() if len(word.strip()) > 2):
            self._apply_hits(hits)
            return
            
        # Launch AI reranking in background; UI stays responsive
        try:
            # Pass metadata for guardrails
            time_window = getattr(self, '_last_time_range', None)
            file_types = getattr(self, '_last_file_types', None)
            folders = getattr(self, '_last_folders', None)
            self._rerank = RerankWorker(self.ai, query, hits, time_window, file_types, folders)
            self._rerank.reranked.connect(self._apply_hits)
            self._rerank.start()
        except Exception:
            self._apply_hits(hits)

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
        def __init__(self, ai: LumaAI, path: str, use_ai: bool):
            super().__init__(); self.ai=ai; self.path=path; self.use_ai=use_ai
        def run(self):
            try:
                if self.use_ai:
                    s = self.ai.summarize_file(self.path) or "Summary unavailable. Check AI mode and dependencies."
                else:
                    s = self.ai.summarize_file_extractive(self.path) or "Summary unavailable (no text)."
            except Exception:
                s = "Summary failed."
            self.summary_ready.emit(s)

    def _summarize_selected(self):
        # Check if we're in conversation mode and get the selected file from conversation results
        if hasattr(self, '_current_conversation_hits') and self._current_conversation_hits and self.stack.currentIndex() == 1:
            # In conversation mode, get the currently selected file from conversation results
            if hasattr(self, '_current_selected_index') and 0 <= self._current_selected_index < len(self._current_conversation_hits):
                h = self._current_conversation_hits[self._current_selected_index]
            else:
                return
        else:
            # In main search mode, get the selected file from the main list
            h = self._selected_hit()
            if not h: 
                return
        # Open chat page immediately with running indicator
        self._current_chat_file = h.path
        self.lbl_chat_title.setText(os.path.basename(h.path))
        self.chat_view.clear(); self.chat_view.append("Summarizing…\n")
        self.stack.setCurrentIndex(1)
        self.chat_spinner.start()
        self.preview.summary.setVisible(False)
        # Use the selected mode for summarization
        if self.ai_mode == "none":
            use_ai = False  # Use extractive summarization
        elif self.ai_mode == "cloud":
            use_ai = True   # Use OpenAI API
        else:  # private mode
            use_ai = self.ai._ensure_ollama()  # Use local AI if available, otherwise extractive
        self._sum_worker = self._SummarizeWorker(self.ai, h.path, use_ai)
        self._sum_worker.summary_ready.connect(lambda text, path=h.path, name=os.path.basename(h.path): self._open_chat_with_summary(name, path, text))
        self._sum_worker.start()
        # Show a hint if the operation takes too long (mainly for AI mode)
        def _slow_hint():
            if getattr(self, "_sum_worker", None) and self._sum_worker.isRunning():
                if self.ai_mode == "cloud":
                    self.chat_view.append("This is taking longer than usual. Cloud Mode is processing...\n")
                elif self.ai_mode == "private":
                    self.chat_view.append("This is taking longer than usual. Private Mode is processing...\n")
                else:
                    self.chat_view.append("This is taking longer than usual. Processing...\n")
        QTimer.singleShot(2500, _slow_hint)

    def _open_chat_with_summary(self, name: str, path: str, summary: str):
        self.chat_spinner.stop()
        self._current_chat_file = path
        self.lbl_chat_title.setText(name)
        self.chat_view.clear()
        
        # Switch to conversation mode
        self.stack.setCurrentIndex(1)
        self._update_conversation_mode_indicator()
        
        # Add AI message with summary
        self._add_ai_message(f"Here's a summary of {name}:\n\n{summary}")
        
        # Show file in preview
        self.conversation_preview.set_file(path)
        self.conversation_preview.show()

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
        if not q:
            return
        self.chat_input.clear()
        
        # Add user message to conversation
        self._add_user_message(q)
        
        # Show loading indicator
        self.chat_spinner.start()
        self.chat_view.append("AI is thinking…\n")
        
        # Handle the query based on context
        if hasattr(self, "_current_chat_file") and self._current_chat_file:
            # File-specific Q&A
            self._qa_worker = self._QnAWorker(self.ai, self._current_chat_file, q)
            self._qa_worker.answer_ready.connect(self._apply_answer)
            self._qa_worker.start()
        else:
            # General AI query
            self._handle_ai_query(q)

    def _apply_answer(self, a: str):
        self.chat_spinner.stop()
        
        # Remove the "AI is thinking..." message
        cursor = self.chat_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        if "AI is thinking…" in cursor.selectedText():
            cursor.removeSelectedText()
            cursor.deletePreviousChar()
        
        # Add AI response with proper styling
        self._add_ai_message(a)
    
    def _go_back_from_conversation(self):
        """Handle back button from conversation mode."""
        # Keep the current AI mode (private or cloud) - don't reset to No AI
        # Switch back to search mode
        self.stack.setCurrentIndex(0)
        # Resize back to search mode
        self.resize(700, 160)
        self.setMinimumSize(700, 160)
        self.setMaximumSize(700, 800)

    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#wrapper {background: white; border-radius: 16px; border: none;}
        QWidget {background: transparent;}
        
        /* Integrated search container */
        QWidget#searchContainer {background: white; border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08);}
        
        /* Main search input */
        QLineEdit#mainSearch {background: transparent; border: none; padding: 8px 12px; color: #111; selection-background-color: #bcd4ff; font-size: 16px; font-weight: 400;}
        QLineEdit#mainSearch:focus {background: transparent;}
        
        /* AI mode button */
        QPushButton#aiModeButton {background: transparent; border: none; border-left: 1px solid rgba(0,0,0,0.1); padding: 8px 12px; color: #666; font-size: 13px; font-weight: 500;}
        QPushButton#aiModeButton:hover {background: rgba(0,0,0,0.05); color: #333;}
        QPushButton#aiModeButton:pressed {background: rgba(0,0,0,0.1);}
        
        /* Spinner holder (replaces Tab button) */
        QWidget#spinnerHolder {background: transparent; border: none; border-left: 1px solid rgba(0,0,0,0.1);}
        
        /* Settings button */
        QPushButton#settingsButton {background: transparent; border: none; border-left: 1px solid rgba(0,0,0,0.1); padding: 8px; color: #666; font-size: 16px; font-weight: 500;}
        QPushButton#settingsButton:hover {background: rgba(0,0,0,0.05); color: #333;}
        QPushButton#settingsButton:pressed {background: rgba(0,0,0,0.1);}
        QPushButton#settingsButton QIcon {background: transparent;}
        
        /* AI dropdown menu - popup window style */
        QWidget#aiDropdown {background: rgba(45, 55, 72, 0.95); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.3);}
        
        /* Dropdown options - dark popup style */
        QPushButton#dropdownOption {background: rgba(255, 255, 255, 0.1); border: 1px solid rgba(255,255,255,0.1); padding: 12px 16px; color: #e5e7eb; font-size: 14px; font-weight: 500; text-align: left; border-radius: 8px; margin: 3px;}
        QPushButton#dropdownOption:hover {background: rgba(59, 130, 246, 0.3); color: #ffffff; border: 1px solid rgba(59, 130, 246, 0.5);}
        QPushButton#dropdownOption:pressed {background: rgba(59, 130, 246, 0.4); color: #ffffff; border: 1px solid rgba(59, 130, 246, 0.6);}
        QPushButton#dropdownOption:checked {background: rgba(59, 130, 246, 0.35); color: #ffffff; border: 1px solid rgba(59, 130, 246, 0.55);}
        
        /* Settings page styles */
        QFrame#settingsSection {background: white; border-radius: 12px; border: 1px solid rgba(0,0,0,0.12); box-shadow: 0 4px 12px rgba(0,0,0,0.08); margin: 8px 0px;}
        QLabel#settingsLabel {color: #333; font-size: 18px; font-weight: 600; margin-bottom: 16px; padding: 12px 0px; margin-top: 16px;}
        QLabel#settingsDescription {color: #666; font-size: 14px; font-weight: 400; margin-top: 8px; padding: 4px 0px; line-height: 1.4;}
        QComboBox#settingsCombo {background: white; border: 2px solid rgba(0,0,0,0.15); border-radius: 8px; padding: 12px 16px; color: #333; font-size: 14px; font-weight: 500;}
        QComboBox#settingsCombo:hover {border-color: rgba(59, 130, 246, 0.6); background: rgba(59, 130, 246, 0.02);}
        QComboBox#settingsCombo:focus {border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);}
        QComboBox#settingsCombo::drop-down {border: none; width: 20px;}
        QComboBox#settingsCombo::down-arrow {image: none; border: none; width: 0; height: 0; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 5px solid #666;}
        
        QListView {background: white; border: none; padding: 0px; color: #222; border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08);}
        QWidget#leftPane {background: white; border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08);}
        QWidget#previewPane {background: white; border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08);}
        QWidget#previewPane QLabel {background: white; color: #222;}
        QWidget#previewPane QFrame#thumbCard {background: white; border-radius: 8px; border: 1px solid rgba(0,0,0,0.06);}
        QWidget#previewPane QTextEdit {background: white; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; padding: 8px; color: #222;}
        QWidget#previewPane QPushButton {background: #3b82f6; color: white; border: none; border-radius: 8px; padding: 6px 12px; font-weight: 600;}
        QWidget#previewPane QPushButton:hover {background: #2563eb;}
        QWidget#previewPane QPushButton:pressed {background: #1d4ed8;}
        QListView::item {border-radius: 12px; padding: 8px 8px 8px 24px; margin: 3px 0px 3px 0px;}
        QListView::item:selected {background: rgba(59, 130, 246, 0.08); border: none; border-radius: 12px;}
        QLabel#metaHeader {color:#4a4a4a; font-size:12px; font-weight:600; margin: 8px 0 4px 0;}
        QLabel#metaLabel {color:#6f6f6f; font-size:11px;}
        QLabel#metaValue {color:#111; font-size:11px;}
        QWidget#rowContainer {border: none; background: white;}
        QFrame#rowSep {background: rgba(0,0,0,0.08); min-height: 1px; max-height: 1px; margin-top: 6px;}
        QFrame#thumbCard {background: white; border: none; border-radius: 0px;}
        QSplitter::handle {background: rgba(0,0,0,0.06);}
        
        /* Conversation Mode Styles - Matching Main Page */
        QWidget#chatHeader {
            background: transparent;
            border: none;
            border-radius: 0px;
        }
        
        QPushButton#chatBackButton {
            background: transparent;
            border: none;
            color: #6b7280;
            font-size: 18px;
            font-weight: 600;
            border-radius: 8px;
        }
        QPushButton#chatBackButton:hover {
            background: rgba(0,0,0,0.05);
            color: #374151;
        }
        QPushButton#chatBackButton:pressed {
            background: rgba(0,0,0,0.1);
        }
        
        QLabel#chatModeDisplay {
            background: transparent;
            border: none;
            border-left: 1px solid rgba(0,0,0,0.1);
            color: #6b7280;
            font-size: 13px;
            font-weight: 500;
            padding: 8px 12px;
            text-align: center;
            min-width: 140px;
            line-height: 1.2;
        }
        
        QWidget#chatSpinnerHolder {
            background: transparent;
            border: none;
        }
        
        QWidget#conversationWidget {
            background: #f8fafc;
            border-radius: 0px;
        }
        
        QTextEdit#conversationView {
            background: #f8fafc;
            border: none;
            border-radius: 0px;
            padding: 16px;
            color: #1e293b;
            font-size: 14px;
            line-height: 1.5;
        }
        
        QLineEdit#mainChatInput {
            background: transparent;
            border: none;
            padding: 8px 12px;
            color: #111;
            selection-background-color: #bcd4ff;
            font-size: 16px;
            font-weight: 400;
        }
        QLineEdit#mainChatInput:focus {
            background: transparent;
        }
        
        QWidget#conversationPreview {
            background: white;
            border-left: 1px solid rgba(0,0,0,0.08);
            border-radius: 0px;
        }
        
        QSplitter#conversationSplitter::handle {
            background: rgba(0,0,0,0.08);
            width: 1px;
        }
        QSplitter#conversationSplitter::handle:hover {
            background: rgba(59, 130, 246, 0.3);
        }
        """)

    # ---------------- Warmup -----------------
    class _WarmupWorker(QThread):
        def __init__(self, ai: LumaAI):
            super().__init__(); self.ai = ai
        def run(self):
            try:
                self.ai.warmup()
            except Exception:
                pass

    def _warmup_ai(self):
        try:
            self._warm = self._WarmupWorker(self.ai)
            self._warm.start()
        except Exception:
            pass

    def _populate_language_combo(self):
        """Populate the language combo box with available languages."""
        tm = get_translation_manager()
        available_languages = tm.get_available_languages()
        
        for lang_code, lang_name in available_languages.items():
            self.language_combo.addItem(f"{lang_name} ({lang_code})", lang_code)
        
        # Set current language
        current_lang = tm.get_current_language()
        for i in range(self.language_combo.count()):
            if self.language_combo.itemData(i) == current_lang:
                self.language_combo.setCurrentIndex(i)
                break
    
    def _on_language_changed(self, text: str):
        """Handle language change from the combo box."""
        # Extract language code from the text (e.g., "English (en)" -> "en")
        lang_code = self.language_combo.currentData()
        if lang_code:
            tm = get_translation_manager()
            if tm.set_language(lang_code):
                self._update_ui_texts()
    
    def _update_ui_texts(self):
        """Update all UI texts with current translations."""
        # Store current language selection to preserve it
        current_lang_code = None
        if hasattr(self, 'language_combo') and self.language_combo.count() > 0:
            current_lang_code = self.language_combo.currentData()
        
        # Update window title
        self.setWindowTitle(tr("app_title"))
        
        # Update search placeholder based on AI mode
        if hasattr(self, 'search'):
            if self.ai_mode == "none":
                self.search.setPlaceholderText(tr("search_placeholder_auto"))
            else:
                self.search.setPlaceholderText(tr("search_placeholder_enter"))
        
        # Update AI mode button
        if hasattr(self, 'ai_mode_button'):
            if self.ai_mode == "none":
                self.ai_mode_button.setText(tr("ask_ai"))
            elif self.ai_mode == "private":
                self.ai_mode_button.setText(tr("private_mode"))
            elif self.ai_mode == "cloud":
                self.ai_mode_button.setText(tr("cloud_mode"))
        
        # Update dropdown options
        if hasattr(self, 'no_ai_btn'):
            self.no_ai_btn.setText(tr("no_ai"))
        if hasattr(self, 'private_mode_btn'):
            self.private_mode_btn.setText(tr("private_mode"))
        if hasattr(self, 'cloud_mode_btn'):
            self.cloud_mode_btn.setText(tr("cloud_mode"))
        
        # Update chat page (only if elements exist)
        if hasattr(self, 'lbl_chat_title'):
            self.lbl_chat_title.setText(tr("ask_follow_up"))
        if hasattr(self, 'chat_input'):
            self.chat_input.setPlaceholderText(tr("ask_follow_up"))
        if hasattr(self, 'chat_send'):
            self.chat_send.setText(tr("send"))
        
        # Update settings page (only if elements exist)
        if hasattr(self, 'lbl_settings_title'):
            self.lbl_settings_title.setText(tr("settings"))
        if hasattr(self, 'lbl_language'):
            self.lbl_language.setText(tr("language"))
        
        # Update tooltips
        if hasattr(self, 'settings_btn'):
            self.settings_btn.setToolTip(tr("settings"))
        
        # Restore language selection if it was preserved
        if current_lang_code and hasattr(self, 'language_combo'):
            for i in range(self.language_combo.count()):
                if self.language_combo.itemData(i) == current_lang_code:
                    self.language_combo.setCurrentIndex(i)
                    break
    
    def _show_settings(self):
        """Show settings page with proper sizing."""
        self.stack.setCurrentIndex(2)
        # Resize window to accommodate settings content
        self.resize(700, 600)  # Even taller for settings
        self.setMinimumSize(700, 600)
        self.setMaximumSize(700, 700)
    
    def _hide_settings(self):
        """Hide settings page and return to search."""
        self.stack.setCurrentIndex(0)
        # Return to normal search size
        self.resize(700, 160)
        self.setMinimumSize(700, 160)
        self.setMaximumSize(700, 800)


