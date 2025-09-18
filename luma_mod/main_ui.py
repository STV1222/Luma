from __future__ import annotations
import os
from typing import Optional, List

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtWidgets import QWidget, QFrame, QLineEdit, QComboBox, QListView, QVBoxLayout, QHBoxLayout, QSplitter, QSizePolicy, QTextEdit, QPushButton, QLabel, QStackedLayout, QTextBrowser, QFileDialog, QDialog, QListWidget, QDialogButtonBox
from PyQt6.QtGui import QTextCursor, QMouseEvent, QKeyEvent, QGuiApplication

from .utils import DEFAULT_FOLDERS, FILETYPE_MAP, divider, center_on_screen, os_open, make_paths_clickable
from .widgets import BusySpinner, ToggleSwitch, PreviewPane, LoadingOverlay
from .models import ResultsModel, ResultDelegate, FileHit
from .ai import LumaAI
from .search_core import search_files
from .i18n import get_translation_manager, tr
from .ui.chat_browser import ChatBrowser
from .ui.workers import (
    SearchWorker,
    AIWorker,
    RerankWorker,
    SummarizeWorker,
    QnAWorker,
    WarmupWorker,
)
from .config import get_openai_api_key, get_default_ai_mode


# ChatBrowser moved to luma_mod.ui.chat_browser


# SearchWorker moved to luma_mod.ui.workers


# AIWorker moved to luma_mod.ui.workers


# RerankWorker moved to luma_mod.ui.workers


class SpotlightUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Luma (Modular)")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(700, 160)  # Increased height to prevent squeezing
        self.setMaximumSize(700, 800)  # Keep consistent width, only height changes
        self._folders=DEFAULT_FOLDERS[:]
        self._turn_idx = 0
        self._rag_folders: List[str] = []
        self._worker: Optional[SearchWorker]=None
        self._ai_worker: Optional[AIWorker]=None
        # Initialize AI with environment-configured defaults (no hardcoded secrets)
        self.openai_api_key = get_openai_api_key()
        self.ai_mode = get_default_ai_mode()  # "none", "private", or "cloud"
        self.ai = LumaAI(mode=self.ai_mode, openai_api_key=self.openai_api_key)

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
        self.search.setPlaceholderText("Search for files or folders...")
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
        
        # Folder chooser button next to spinner
        self.folder_btn = QPushButton("Folders")
        self.folder_btn.setObjectName("aiModeButton")
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.setFixedWidth(90)
        self.folder_btn.setFixedHeight(36)
        self.folder_btn.clicked.connect(self._toggle_folder_dropdown)
        # Small chip showing current folder scope
        self.folder_chip = QLabel("All folders")
        self.folder_chip.setObjectName("folderChip")
        self.folder_chip.setToolTip("RAG searches all indexed folders")
        self.folder_chip.setFixedHeight(36)
        
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
        search_layout.addWidget(self.folder_btn, 0)
        search_layout.addWidget(self.folder_chip, 0)
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
        
        # Quick folder dropdown (lists known folders; allows open dialog)
        self.folder_dropdown = QWidget()
        self.folder_dropdown.setObjectName("aiDropdown")
        self.folder_dropdown.setVisible(False)
        self.folder_dropdown.setFixedSize(320, 240)
        self.folder_dropdown.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Popup | 
            Qt.WindowType.WindowStaysOnTopHint
        )
        fd_lay = QVBoxLayout(self.folder_dropdown); fd_lay.setContentsMargins(8,8,8,8); fd_lay.setSpacing(6)
        self.lbl_folder_hint = QLabel("Choose folders for RAG. Recently used and defaults shown:"); self.lbl_folder_hint.setStyleSheet("color:#e5e7eb; font-size:12px;")
        fd_lay.addWidget(self.lbl_folder_hint)
        self.folder_list = QListWidget(); self.folder_list.setSelectionMode(self.folder_list.SelectionMode.ExtendedSelection)
        fd_lay.addWidget(self.folder_list)
        row = QHBoxLayout(); self.btn_add_folder = QPushButton("Add…"); self.btn_use_selected = QPushButton("Use"); self.btn_use_all = QPushButton("Use all"); row.addWidget(self.btn_add_folder); row.addStretch(1); row.addWidget(self.btn_use_all); row.addWidget(self.btn_use_selected)
        fd_lay.addLayout(row)
        self.btn_add_folder.clicked.connect(self._add_folder_to_list)
        self.btn_use_selected.clicked.connect(self._apply_selected_folders)
        self.btn_use_all.clicked.connect(self._apply_all_folders)

        # Reuse the same dropdown for chat header button
        def _toggle_chat_folder_dropdown():
            is_visible = self.folder_dropdown.isVisible()
            if is_visible:
                self.folder_dropdown.setVisible(False)
            else:
                g = self.chat_folder_btn.mapToGlobal(self.chat_folder_btn.rect().bottomLeft())
                self.folder_dropdown.move(g.x(), g.y() + 4)
                self._update_ui_texts()
                self.folder_dropdown.setVisible(True)
        self._toggle_folder_dropdown_chat = _toggle_chat_folder_dropdown
        
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
        # Initially hide summarize button since we start in "No AI" mode
        self.preview.btn_summarize.setVisible(False)

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
        # Add keyboard event handling for Cmd/Ctrl+Enter
        self.chat_input.keyPressEvent = self._handle_chat_key_press
        
        # Mode display (matching main page style)
        self.mode_display = QLabel("No AI")
        self.mode_display.setObjectName("chatModeDisplay")
        self.mode_display.setFixedWidth(140)  # Further increased width
        self.mode_display.setFixedHeight(36)  # Match other elements height
        self.mode_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_display.setMinimumWidth(140)  # Ensure minimum width

        # Chat header folder scope controls (hidden by default; only for AI modes)
        self.chat_folder_btn = QPushButton("Folders")
        self.chat_folder_btn.setObjectName("aiModeButton")
        self.chat_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chat_folder_btn.setFixedWidth(90)
        self.chat_folder_btn.setFixedHeight(36)
        self.chat_folder_btn.clicked.connect(self._toggle_folder_dropdown_chat)
        self.chat_folder_btn.setVisible(False)

        self.chat_folder_chip = QLabel("All folders")
        self.chat_folder_chip.setObjectName("folderChip")
        self.chat_folder_chip.setToolTip("RAG searches all indexed folders")
        self.chat_folder_chip.setVisible(False)
        self.chat_folder_chip.setFixedHeight(36)
        
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
        head.addWidget(self.chat_folder_btn, 0)
        head.addWidget(self.chat_folder_chip, 0)
        head.addWidget(self.chat_spinner_holder, 0)  # Fixed size
        
        cp_lay.addWidget(header_widget)
        
        # Main conversation area with splitter for chat and preview
        conversation_splitter = QSplitter(Qt.Orientation.Horizontal)
        conversation_splitter.setObjectName("conversationSplitter")
        
        # Left side: Conversation history
        conversation_widget = QWidget()
        conversation_widget.setObjectName("conversationWidget")
        conv_layout = QVBoxLayout(conversation_widget)
        conv_layout.setContentsMargins(0, 0, 0, 0)  # Align with search bar
        conv_layout.setSpacing(0)
        
        # Conversation view with scrollable chat history
        self.chat_view = ChatBrowser()
        self.chat_view.setObjectName("conversationView")
        self.chat_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chat_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        conv_layout.addWidget(self.chat_view, 1)
        
        # Right side: Preview pane (integrated)
        self.conversation_preview = PreviewPane()
        self.conversation_preview.setObjectName("conversationPreview")
        self.conversation_preview.setVisible(False)
        # Hook conversation preview summarize button to summarization
        self.conversation_preview.btn_summarize.clicked.connect(self._summarize_selected)
        
        # Add widgets to splitter
        conversation_splitter.addWidget(conversation_widget)
        conversation_splitter.addWidget(self.conversation_preview)
        conversation_splitter.setStretchFactor(0, 2)
        conversation_splitter.setStretchFactor(1, 1)
        conversation_splitter.setSizes([400, 300])
        
        cp_lay.addWidget(conversation_splitter, 1)
        # Global loading overlay for chat page
        self.chat_overlay = LoadingOverlay(self.chat_page)

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

    def _toggle_folder_dropdown(self):
        is_visible = self.folder_dropdown.isVisible()
        if is_visible:
            self.folder_dropdown.setVisible(False)
        else:
            # position under button
            g = self.folder_btn.mapToGlobal(self.folder_btn.rect().bottomLeft())
            self.folder_dropdown.move(g.x(), g.y() + 4)
            # refresh list
            self._update_ui_texts()
            self.folder_dropdown.setVisible(True)

    def _add_folder_to_list(self):
        path = QFileDialog.getExistingDirectory(self, "Choose folder", os.path.expanduser("~"))
        if path:
            if path not in self._rag_folders:
                self._rag_folders.append(path)
                self.folder_list.addItem(path)

    def _apply_selected_folders(self):
        selected = [self.folder_list.item(i).text() for i in range(self.folder_list.count()) if self.folder_list.item(i).isSelected()]
        if not selected:
            selected = [self.folder_list.item(i).text() for i in range(self.folder_list.count())]
        self._rag_folders = selected
        try:
            from luma_mod.rag.service import ensure_index_started
            # Replace index with the newly selected folders to strictly scope RAG
            ensure_index_started(self._rag_folders, exclude=["node_modules", "__pycache__", ".git"], replace=True)
            self._add_ai_message("Indexing (fresh) started for selected folders. RAG will only use these folders.")
        except Exception:
            pass
        # Update chips in both search header and chat header
        self._update_folder_chips()
        self.folder_dropdown.setVisible(False)

    def _update_folder_chips(self):
        """Sync folder scope chips (search bar and chat header) with current selection."""
        try:
            if len(self._rag_folders) == 0:
                label = "All folders"; tooltip = "RAG searches all indexed folders"
            elif len(self._rag_folders) == 1:
                import os as _os
                base = _os.path.basename(self._rag_folders[0]) or self._rag_folders[0]
                label = base; tooltip = self._rag_folders[0]
            else:
                label = f"{len(self._rag_folders)} folders"; tooltip = "\n".join(self._rag_folders)
            if hasattr(self, 'folder_chip'):
                self.folder_chip.setText(label); self.folder_chip.setToolTip(tooltip)
            if hasattr(self, 'chat_folder_chip'):
                self.chat_folder_chip.setText(label); self.chat_folder_chip.setToolTip(tooltip)
        except Exception:
            pass

    def _apply_all_folders(self):
        """Switch back to using all indexed folders (clears explicit selection)."""
        self._rag_folders = []
        self._update_folder_chips()
        self.folder_dropdown.setVisible(False)
    
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
            # Hide summarize button in No AI mode
            self.preview.btn_summarize.setVisible(False)
            # Also hide summarize button in conversation preview
            if hasattr(self, 'conversation_preview'):
                self.conversation_preview.btn_summarize.setVisible(False)
            # Update summarize button visibility for both previews
            self.preview.update_summarize_button_visibility(self.ai_mode)
            if hasattr(self, 'conversation_preview'):
                self.conversation_preview.update_summarize_button_visibility(self.ai_mode)
            # Hide folder controls in No AI mode
            if hasattr(self, 'folder_btn'):
                self.folder_btn.setVisible(False)
            if hasattr(self, 'folder_chip'):
                self.folder_chip.setVisible(False)
        elif mode_text == "Private Mode":
            self.ai_mode = "private"
            # Reinitialize AI with private mode
            self.ai = LumaAI(mode=self.ai_mode, openai_api_key=self.openai_api_key)
            # Clear conversation and switch to conversation page
            self._clear_conversation()
            self._switch_to_conversation_mode()
            # Show summarize button in Private mode
            self.preview.btn_summarize.setVisible(True)
            # Also show summarize button in conversation preview
            if hasattr(self, 'conversation_preview'):
                self.conversation_preview.btn_summarize.setVisible(True)
            # Update summarize button visibility for both previews
            self.preview.update_summarize_button_visibility(self.ai_mode)
            if hasattr(self, 'conversation_preview'):
                self.conversation_preview.update_summarize_button_visibility(self.ai_mode)
            # Show folder controls in AI modes
            if hasattr(self, 'folder_btn'):
                self.folder_btn.setVisible(True)
            if hasattr(self, 'folder_chip'):
                self.folder_chip.setVisible(True)
            # Show folder controls in AI modes
            if hasattr(self, 'chat_folder_btn'):
                self.chat_folder_btn.setVisible(True)
            if hasattr(self, 'chat_folder_chip'):
                self.chat_folder_chip.setVisible(True)
            # Warm up the AI mode
            try:
                QTimer.singleShot(50, self._warmup_ai)
            except Exception:
                pass
        elif mode_text == "Cloud Mode":
            self.ai_mode = "cloud"
            # Reinitialize AI with cloud mode
            self.ai = LumaAI(mode=self.ai_mode, openai_api_key=self.openai_api_key)
            # Clear conversation and switch to conversation page
            self._clear_conversation()
            self._switch_to_conversation_mode()
            # Show summarize button in Cloud mode
            self.preview.btn_summarize.setVisible(True)
            # Also show summarize button in conversation preview
            if hasattr(self, 'conversation_preview'):
                self.conversation_preview.btn_summarize.setVisible(True)
            # Update summarize button visibility for both previews
            self.preview.update_summarize_button_visibility(self.ai_mode)
            if hasattr(self, 'conversation_preview'):
                self.conversation_preview.update_summarize_button_visibility(self.ai_mode)
            # Show folder controls in AI modes
            if hasattr(self, 'folder_btn'):
                self.folder_btn.setVisible(True)
            if hasattr(self, 'folder_chip'):
                self.folder_chip.setVisible(True)
            # Show folder controls in AI modes
            if hasattr(self, 'chat_folder_btn'):
                self.chat_folder_btn.setVisible(True)
            if hasattr(self, 'chat_folder_chip'):
                self.chat_folder_chip.setVisible(True)
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
        # If the query supplied a folder scope, hard-scope to it; otherwise use defaults
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
        # Remember keywords for conditional rerank logic
        self._last_keywords = kws[:]
        
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption(); self._worker.quit(); self._worker.wait(50)
        self.preview.hide(); self.spinner.start()
        # Store metadata for reranker guardrails
        self._last_time_range = tr
        self._last_file_types = allow_exts
        self._last_folders = target_folders
        self._last_folder_depth = info.get("folder_depth", "any")
        
        self._worker=SearchWorker(target_folders, kws, allow_exts, tr, tattr, semantic_keywords, file_patterns)
        if self.ai_mode != "none":
            self._worker.results_ready.connect(lambda hits, q=self.search.text().strip(): self._maybe_rerank(q, hits))
        else:
            self._worker.results_ready.connect(lambda hits: self._apply_hits(self._conditioned_rerank(hits)))
        self._worker.start()

    def _perform_search(self):
        q=self.search.text().strip()
        
        # Don't perform search if query is empty - this ensures UI stays collapsed
        if not q:
            return
        
        if self.ai_mode == "none":
            # No AI: never use RAG; always local filename listing with strict ext when user says ppt/powerpoint
            info = self.ai.parse_query_nonai(q)
            import re as _re
            if _re.search(r"\b(pptx?|power\s*point|powerpoint)\b", q, _re.IGNORECASE):
                allow_exts = ['.ppt', '.pptx']
                info['file_types'] = allow_exts
            self._start_search_with_info(info, "User")
        else:
            # For AI modes, switch to conversation and handle the query there
            self._switch_to_conversation_mode()
            # In AI modes: if cross-doc, run RAG; else do AI-assisted listing
            route = self.ai.route_query(q)
            if route == "rag":
                try:
                    self.chat_view.clear()
                    self.chat_view.append("<div style='margin:6px 0 12px 0; color:#6b7280;'>Asking across your documents…</div>")
                    # Show loading indicator (overlay + small spinner) while RAG runs
                    try:
                        self.chat_spinner.start()
                        self._show_loading("AI is thinking…")
                        self.chat_view.append("AI is thinking…\n")
                    except Exception:
                        pass
                    res = self.ai.crossdoc_answer(q, n_ctx=12)
                    ans = (res.get("answer") or "").replace("\n","<br>")
                    hits = res.get("hits", [])
                    low = bool(res.get("low_confidence", False))
                    # Stop spinner and clear the thinking line
                    try:
                        self.chat_spinner.stop()
                        self._clear_thinking_line()
                    except Exception:
                        pass
                    self._add_ai_message(ans)
                    for i, (score, meta) in enumerate(hits, start=1):
                        path = str(meta.get("path", ""))
                        page = meta.get("page")
                        tag = f"{path}:p{page}" if page else path
                        snippet = str(meta.get("text", ""))[:320].replace("\n", " ")
                        card_html = (
                            f"<div style='border:1px solid #e5e7eb; border-radius:10px; padding:10px; margin:8px 20% 8px 0;'>"
                            f"<div style='font-weight:600; margin-bottom:6px;'>[{i}] {tag}</div>"
                            f"<div style='color:#374151; font-size:0.95em;'>{snippet}</div>"
                            f"</div>"
                        )
                        self.chat_view.append(card_html)
                    # Append structured Sources block
                    if hits:
                        sources_html = "<div style='margin:8px 0 4px 0; color:#6b7280; font-weight:600;'>Sources</div>"
                        self.chat_view.append(sources_html)
                        for i, (score, meta) in enumerate(hits, start=1):
                            path = str(meta.get("path", ""))
                            page = meta.get("page")
                            tag = f"{path}:p{page}" if page else path
                            from urllib.parse import quote
                            qp = quote(path)
                            snippet = str(meta.get("text", ""))[:220].replace("\n", " ")
                            block = (
                                f"<div style='border:1px solid #e5e7eb; border-radius:10px; padding:10px; margin:6px 20% 6px 0;'>"
                                f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;'>"
                                f"<div style='font-weight:600;'>[{i}] {tag}</div>"
                                f"<div>"
                                f"<a href='luma://select?path={qp}' style='margin-right:8px;'>Preview</a>"
                                f"<a href='luma://select?path={qp}' onclick='return false;' style='margin-right:0;'>Open</a>"
                                f"</div>"
                                f"</div>"
                                f"<div style='color:#374151; font-size:0.95em;'>{snippet}</div>"
                                f"</div>"
                            )
                            self.chat_view.append(block)
                    if low:
                        self.chat_view.append(
                            "<div style='background:#fef3c7; color:#92400e; padding:10px; border-radius:10px; border-left:4px solid #f59e0b; margin:8px 20% 0 0;'>Not enough info in your files</div>"
                        )
                    return
                except Exception:
                    # If RAG fails, fallback to AI listing flow
                    try:
                        self.chat_spinner.stop()
                        self._clear_thinking_line()
                    except Exception:
                        pass
                    pass
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
        
        # Show loading indicator (overlay + small spinner)
        self.chat_spinner.start()
        self._show_loading("AI is thinking…")
        self.chat_view.append("AI is thinking…\n")
        
        # Route: cross-document questions use RAG; otherwise use AI understanding + listing
        try:
            route = self.ai.route_query(query)
        except Exception:
            route = "list"
        # Reset RAG context if user explicitly asks for files/folders → switch to listing
        import re
        if re.search(r"\b(show|list|open)\b.*\b(folder|directory|under|in)\b", query, re.IGNORECASE):
            route = "list"
        # Force RAG summary when the user asks for a summary/what/which without file-browse intent
        if route != "rag" and re.search(r"\b(summary|summar(ize|ise)|what\b|which\b)", query, re.IGNORECASE):
            route = "rag"
        if route == "rag":
            try:
                # If index seems empty, show onboarding banner with 1-click init
                try:
                    from luma_mod.rag.query import search as rag_search
                    probe = rag_search("__probe__", k=1)
                except Exception:
                    probe = []
                if not probe:
                    banner = (
                        "<div style='background:#eef2ff; color:#3730a3; padding:12px; border-radius:12px; border-left:4px solid #6366f1; margin:8px 20% 12px 0;'>"
                        "Build your private index to answer from your files. "
                        "<a href='luma://rag?action=init'>Index now</a>"
                        "</div>"
                    )
                    self.chat_view.append(banner)
                res = self.ai.crossdoc_answer(query, n_ctx=12)
                ans = (res.get("answer") or "").replace("\n","<br>")
                hits = res.get("hits", [])
                low = bool(res.get("low_confidence", False))
                # Stop spinner and clear the thinking line
                self.chat_spinner.stop()
                self._clear_thinking_line()
                # Show answer with citations
                self._add_ai_message(ans)
                for i, (score, meta) in enumerate(hits, start=1):
                    path = str(meta.get("path", ""))
                    page = meta.get("page")
                    tag = f"{path}:p{page}" if page else path
                    snippet = str(meta.get("text", ""))[:320].replace("\n", " ")
                    card_html = (
                        f"<div style='border:1px solid #e5e7eb; border-radius:10px; padding:10px; margin:8px 20% 8px 0;'>"
                        f"<div style='font-weight:600; margin-bottom:6px;'>[{i}] {tag}</div>"
                        f"<div style='color:#374151; font-size:0.95em;'>{snippet}</div>"
                        f"</div>"
                    )
                    self.chat_view.append(card_html)
                if low:
                    self.chat_view.append(
                        "<div style='background:#fef3c7; color:#92400e; padding:10px; border-radius:10px; border-left:4px solid #f59e0b; margin:8px 20% 0 0;'>Not enough info in your files</div>"
                    )
                return
            except Exception:
                # Fall through to AI understanding flow on failure
                pass

        # Process via AI understanding (listing path)
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

    def _clear_thinking_line(self):
        try:
            cursor = self.chat_view.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            if "AI is thinking…" in cursor.selectedText():
                cursor.removeSelectedText()
                cursor.deletePreviousChar()
        except Exception:
            pass
        # Always hide overlay when clearing thinking line
        self._hide_loading()

    def _show_loading(self, text: str):
        try:
            if hasattr(self, 'chat_overlay') and self.chat_overlay:
                self.chat_overlay.show_overlay(text)
        except Exception:
            pass

    def _hide_loading(self):
        try:
            if hasattr(self, 'chat_overlay') and self.chat_overlay:
                self.chat_overlay.hide_overlay()
        except Exception:
            pass
        
    def _add_user_message(self, message: str):
        """Add a grouped Q/A card container with the user's message and an AI placeholder."""
        from datetime import datetime
        self._turn_idx += 1

        # Convert file/folder paths to clickable links
        clickable_message = make_paths_clickable(message)
        timestamp = datetime.now().strftime("%H:%M")

        # Unique placeholder token for this turn. We'll replace it when AI responds.
        placeholder = f"<!--AI_SLOT_{self._turn_idx}-->"

        # Q/A card wrapper with rounded corners and subtle border
        qa_card_html = f"""
        <div id='qa-{self._turn_idx}' style='background:#ffffff; border:1px solid #e5e7eb; border-radius:16px; padding:14px 16px; margin:12px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.05);'>
            <div style='margin-bottom: 10px; display: flex; justify-content: flex-end;'>
                <div style='background: #3b82f6; color: white; border-radius: 12px; padding: 10px 14px; max-width: 88%; box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>
                    <div style='display: flex; align-items: center; margin-bottom: 4px;'>
                        <span style='background:#1d4ed8; color:#fff; border-radius:8px; font-size:11px; padding:2px 6px; margin-right:8px;'>#{self._turn_idx}</span>
                        <span style='font-weight: 600;'>You</span>
                        <span style='color: rgba(255,255,255,0.85); font-size: 12px; margin-left: 8px;'>{timestamp}</span>
                    </div>
                    <div style='color: #ffffff;'>{clickable_message}</div>
                </div>
            </div>
            {placeholder}
        </div>
        """

        self.chat_view.append(qa_card_html)
        
        
    def _add_ai_message(self, message: str):
        """Insert AI message into the current Q/A card if possible; otherwise append as a standalone bubble."""
        from datetime import datetime

        clickable_message = make_paths_clickable(message)
        timestamp = datetime.now().strftime("%H:%M")

        ai_bubble_html = f"""
        <div style='display: flex; justify-content: flex-start;'>
            <div style='background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 16px; max-width: 88%; box-shadow: 0 1px 3px rgba(0,0,0,0.06);'>
                <div style='display: flex; align-items: center; margin-bottom: 8px;'>
                    <div style='width: 8px; height: 8px; background: #3b82f6; border-radius: 50%; margin-right: 8px;'></div>
                    <span style='background:#e0e7ff; color:#1e293b; border-radius:8px; font-size:11px; padding:2px 6px; margin-right:8px;'>#{self._turn_idx}</span>
                    <span style='font-weight: 600; color: #1e293b;'>AI</span>
                    <span style='color: #64748b; font-size: 12px; margin-left: 8px;'>{timestamp}</span>
                </div>
                <div style='color: #1e293b;'>{clickable_message}</div>
            </div>
        </div>
        """

        # Try to place inside the latest Q/A card placeholder
        placeholder = f"<!--AI_SLOT_{self._turn_idx}-->"
        try:
            current_html = self.chat_view.toHtml()
            if placeholder in current_html:
                updated = current_html.replace(placeholder, ai_bubble_html)
                self.chat_view.setHtml(updated)
                return
        except Exception:
            pass

        # Fallback: append as standalone
        self.chat_view.append(ai_bubble_html)
        
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
        self._hide_loading()
        
        # Remove the "AI is thinking..." message
        cursor = self.chat_view.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        if "AI is thinking…" in cursor.selectedText():
            cursor.removeSelectedText()
            cursor.deletePreviousChar()
        
        # Show AI's understanding to the user
        self._show_ai_understanding(info)
        
        # Start search with AI info; enforce folder scoping and match quality messages
        try:
            folder_hint_present = bool(info.get("folder_hint_present"))
            match_quality = str(info.get("folder_match_quality", "none"))
            # If user asked for a folder but we haven't got any match, return a clear message
            if folder_hint_present and (not info.get("folders")):
                self._add_ai_message("No results: folder hint not found. Please pick the folder via the Folders button or rephrase.")
                return
        except Exception:
            pass
        self._start_search_with_info(info, "User")
        # After dispatching search, show match quality notice if applicable
        try:
            if match_quality == "exact":
                self._add_ai_message("Folder scope: fully match.")
            elif match_quality == "close":
                self._add_ai_message("Folder scope: close match (best-guess).")
        except Exception:
            pass
        
    def _apply_hits(self, hits: List[FileHit]):
        self.spinner.stop()
        
        # Mark that a search has been performed
        self._has_searched = True
        
        # Apply condition-based rerank for both AI and No-AI flows
        try:
            hits = self._conditioned_rerank(hits)
        except Exception:
            pass

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
        """Show search results in conversation mode as a chat turn."""
        # Add AI response with results
        result_count = len(hits)
        if result_count == 1:
            message = f"Found 1 file matching your query:"
        else:
            message = f"Found {result_count} files matching your query:"
        
        # Create AI bubble with results
        self._add_ai_turn_with_results(message, hits)
        
        # Show preview for first file
        if hits:
            self.conversation_preview.set_file(hits[0].path, self.ai_mode)
            self.conversation_preview.show()
            self._current_conversation_hits = hits
            self._current_selected_index = 0
    
    def _result_row_html(self, name: str, path: str, meta: str, icon: str) -> str:
        """Build HTML for a result row with custom link scheme matching main page style."""
        from urllib.parse import quote
        encoded_path = quote(path)
        
        # Truncate path for display (like main page)
        display_path = path
        if len(display_path) > 42:
            display_path = display_path[:39] + "..."
        
        return f"""
        <div style='display: flex; align-items: center; padding: 8px 8px 8px 24px; margin: 3px 0px 3px 0px; border-radius: 12px; cursor: pointer; transition: background-color 0.2s;' 
             onmouseover='this.style.backgroundColor="rgba(59, 130, 246, 0.08)"' 
             onmouseout='this.style.backgroundColor="transparent"'>
            <a href="luma://select?path={encoded_path}" style='display: flex; align-items: center; width: 100%; text-decoration: none; color: inherit;'>
                <div style='width: 16px; height: 16px; margin-right: 12px; display: flex; align-items: center; justify-content: center; font-size: 12px;'>{icon}</div>
                <div style='flex: 1; min-width: 0;'>
                    <div style='font-weight: 600; color: #1e293b; font-size: 14px; margin-bottom: 2px;'>{name}</div>
                    <div style='font-size: 12px; color: #64748b;'>{display_path}  •  {meta}</div>
                </div>
            </a>
            </div>
            """
        
    def _add_ai_turn_with_results(self, message: str, hits: List[FileHit]):
        """Add an AI turn with collapsible folder-grouped results."""
        from datetime import datetime
        
        # Group files by folder
        folder_groups = {}
        for hit in hits:
            folder = os.path.dirname(hit.path)
            if folder not in folder_groups:
                folder_groups[folder] = []
            folder_groups[folder].append(hit)
        
        # Create AI bubble HTML
        timestamp = datetime.now().strftime("%H:%M")
        
        # Start AI bubble
        ai_bubble_html = f"""
        <div style='margin-bottom: 16px; display: flex; justify-content: flex-start;'>
            <div style='background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 16px; max-width: 80%; box-shadow: 0 1px 3px rgba(0,0,0,0.1);'>
                <div style='display: flex; align-items: center; margin-bottom: 8px;'>
                    <div style='width: 8px; height: 8px; background: #3b82f6; border-radius: 50%; margin-right: 8px;'></div>
                    <span style='font-weight: 600; color: #1e293b;'>AI</span>
                    <span style='color: #64748b; font-size: 12px; margin-left: 8px;'>{timestamp}</span>
                </div>
                <div style='color: #1e293b; margin-bottom: 12px;'>{message}</div>
                <div style='background: white; border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); border: 1px solid rgba(0,0,0,0.08); padding: 0px; margin-top: 8px;'>
        """
        
        # Add all files in a clean list (like main page)
        for hit in hits:
            file_name = os.path.basename(hit.path)
            file_size = self._format_file_size(hit.size)
            file_date = self._format_file_date(hit.mtime)
            meta = file_size
            
            # Determine file icon based on extension
            ext = os.path.splitext(hit.path)[1].lower()
            if ext in ['.pdf']:
                icon = "📄"
            elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                icon = "🖼️"
            elif ext in ['.py']:
                icon = "🐍"
            elif ext in ['.js', '.ts', '.jsx', '.tsx']:
                icon = "⚛️"
            elif ext in ['.html', '.css']:
                icon = "🌐"
            elif ext in ['.doc', '.docx']:
                icon = "📝"
            elif ext in ['.xls', '.xlsx']:
                icon = "📊"
            elif ext in ['.json']:
                icon = "📋"
            elif ext in ['.h', '.cpp', '.c']:
                icon = "⚙️"
            elif ext in ['.xcscheme']:
                icon = "🔧"
            else:
                icon = "📄"
            
            ai_bubble_html += self._result_row_html(file_name, hit.path, meta, icon)
        
        # Close the file list container
        ai_bubble_html += """
                </div>
            </div>
        </div>
        """
        
        # Append to chat view
        self.chat_view.append(ai_bubble_html)
    
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
            self._apply_hits(self._conditioned_rerank(hits))
            return
            
        # Launch AI reranking in background; UI stays responsive
        try:
            # Pass metadata for guardrails
            time_window = getattr(self, '_last_time_range', None)
            file_types = getattr(self, '_last_file_types', None)
            folders = getattr(self, '_last_folders', None)
            self._rerank = RerankWorker(self.ai, query, hits, time_window, file_types, folders)
            self._rerank.reranked.connect(lambda hh: self._apply_hits(self._conditioned_rerank(hh)))
            self._rerank.start()
        except Exception:
            self._apply_hits(self._conditioned_rerank(hits))

    def _conditioned_rerank(self, hits: List[FileHit]) -> List[FileHit]:
        try:
            kws = getattr(self, '_last_keywords', []) or []
            exts = set((getattr(self, '_last_file_types', []) or []))
            folders = set((getattr(self, '_last_folders', []) or []))
            tspan = getattr(self, '_last_time_range', None)

            def meets_all(h: FileHit) -> bool:
                if exts and os.path.splitext(h.path)[1].lower() not in exts:
                    return False
                if folders:
                    depth = getattr(self, '_last_folder_depth', 'any')
                    if depth == 'exact':
                        if not any(os.path.dirname(h.path) == f for f in folders):
                            return False
                    else:
                        if not any(h.path.startswith(f + os.sep) or h.path == f for f in folders):
                            return False
                base = os.path.basename(h.path).lower(); parent = os.path.basename(os.path.dirname(h.path)).lower()
                if kws and not any(k.lower() in base or k.lower() in parent for k in kws):
                    return False
                if tspan and isinstance(tspan, tuple) and all(tspan):
                    s, e = tspan
                    if not (s <= h.mtime <= e):
                        return False
                return True

            def meets_partial(h: FileHit) -> int:
                score = 0
                base = os.path.basename(h.path).lower(); parent = os.path.basename(os.path.dirname(h.path)).lower()
                if exts and os.path.splitext(h.path)[1].lower() in exts: score += 1
                if folders:
                    depth = getattr(self, '_last_folder_depth', 'any')
                    if depth == 'exact':
                        if any(os.path.dirname(h.path) == f for f in folders): score += 1
                    else:
                        if any(h.path.startswith(f + os.sep) or h.path == f for f in folders): score += 1
                if kws and any(k.lower() in base or k.lower() in parent for k in kws): score += 1
                if tspan and isinstance(tspan, tuple) and all(tspan):
                    s, e = tspan
                    if s <= h.mtime <= e: score += 1
                return score

            full = []; partial = []; rest = []
            for h in hits:
                if meets_all(h): full.append(h)
                else:
                    p = meets_partial(h)
                    if p > 0: partial.append((p, h))
                    else: rest.append(h)

            partial_sorted = [h for _p, h in sorted(partial, key=lambda x: x[0], reverse=True)]
            ordered = full + partial_sorted + rest
            # If any conditions were specified, hide items that match zero conditions
            if (exts or folders or kws or tspan):
                if not (full or partial):
                    return []
                return full + partial_sorted
            if (exts or folders or kws or tspan) and not (full or partial):
                return []
            return ordered
        except Exception:
            return hits

    def _selected_hit(self)->Optional[FileHit]:
        idx=self.list.currentIndex(); return self.model.item(idx.row()) if idx.isValid() else None
    def _open_selected(self):
        h=self._selected_hit();
        if not h: return
        os_open(h.path)
    def _update_preview(self):
        h=self._selected_hit()
        print(f"DEBUG: _update_preview called, selected hit: {h}")
        if h: 
            print(f"DEBUG: Setting preview file to: {h.path}")
            self.preview.set_file(h.path, self.ai_mode)

    # ---------------- AI Summarization -----------------

    def _summarize_selected(self):
        print(f"DEBUG: _summarize_selected called, ai_mode: {self.ai_mode}")
        # Only allow summarization in AI modes (private or cloud)
        if self.ai_mode == "none":
            print("DEBUG: No AI mode, returning")
            return
        
        # Resolve the target file path to summarize
        target_path = None
        # Prefer the file currently shown in the visible preview pane
        try:
            if self.stack.currentIndex() == 1 and hasattr(self, 'conversation_preview') and getattr(self.conversation_preview, '_current_file', None):
                target_path = self.conversation_preview._current_file  # type: ignore[attr-defined]
                print(f"DEBUG: Using conversation preview current file: {target_path}")
            elif hasattr(self, 'preview') and getattr(self.preview, '_current_file', None):
                target_path = self.preview._current_file  # type: ignore[attr-defined]
                print(f"DEBUG: Using main preview current file: {target_path}")
        except Exception as e:
            print(f"DEBUG: Failed reading current preview file: {e}")
        
        # Check if we're in conversation mode and get the selected file from conversation results
        if not target_path and hasattr(self, '_current_conversation_hits') and self._current_conversation_hits and self.stack.currentIndex() == 1:
            # In conversation mode, get the currently selected file from conversation results
            if hasattr(self, '_current_selected_index') and 0 <= self._current_selected_index < len(self._current_conversation_hits):
                selected_item = self._current_conversation_hits[self._current_selected_index]
                # Handle both FileHit objects and string paths
                if isinstance(selected_item, str):
                    target_path = selected_item
                else:
                    target_path = selected_item.path
            else:
                # If no file selected in conversation, check if there's a file in the conversation preview
                if hasattr(self, 'conversation_preview') and getattr(self.conversation_preview, '_current_file', None):
                    target_path = self.conversation_preview._current_file  # type: ignore[attr-defined]
        
        # If still no file found, try main search mode
        if not target_path:
            sel = self._selected_hit()
            print(f"DEBUG: _selected_hit() returned: {sel}")
            
            # If still no file, try to get from preview pane
            if sel:
                target_path = sel.path
            elif hasattr(self.preview, '_current_file') and getattr(self.preview, '_current_file', None):
                target_path = self.preview._current_file  # type: ignore[attr-defined]
                print(f"DEBUG: Trying to get file from preview pane: {target_path}")
            else:
                print(f"DEBUG: Preview pane _current_file: {getattr(self.preview, '_current_file', 'None')}")
            
            if not target_path: 
                print("DEBUG: No file selected for summarization")
                return
        
        if not target_path:
            print("DEBUG: Missing target_path for summarization")
            return
        
        print(f"DEBUG: Summarizing file: {target_path}")
        
        # Switch to conversation mode if not already there
        if self.stack.currentIndex() != 1:
            self.stack.setCurrentIndex(1)
            self._update_conversation_mode_indicator()
        
        # Add user message about summarization request to chat
        self._add_user_message(f"Please summarize {os.path.basename(target_path)}")
        
        # Add AI processing message to chat
        self._add_ai_message("Summarizing...")
        
        # Show loading indicator in chat
        self.chat_spinner.start()
        
        # Determine which preview pane to use for button state
        if self.stack.currentIndex() == 1:  # Conversation mode
            preview_pane = self.conversation_preview
        else:  # Search mode
            preview_pane = self.preview
        
        # Disable the summarize button during processing
        preview_pane.btn_summarize.setEnabled(False)
        preview_pane.btn_summarize.setText("Processing...")
        
        # Use the selected mode for summarization
        if self.ai_mode == "none":
            use_ai = False  # Use extractive summarization
        elif self.ai_mode == "cloud":
            use_ai = True   # Use OpenAI API
        else:  # private mode
            use_ai = self.ai._ensure_ollama()  # Use local AI if available, otherwise extractive
        
        self._sum_worker = SummarizeWorker(self.ai, target_path, use_ai)
        self._sum_worker.summary_ready.connect(lambda text, path=target_path, name=os.path.basename(target_path): self._display_summary_in_preview(name, path, text))
        self._sum_worker.summary_failed.connect(lambda error_msg: self._handle_summarize_error(error_msg))
        self._sum_worker.start()

    def _display_summary_in_preview(self, name: str, path: str, summary: str):
        """Display the summary in the chat area."""
        # Stop the chat spinner
        self.chat_spinner.stop()
        self._hide_loading()
        
        # Determine which preview pane to use for button state
        if self.stack.currentIndex() == 1:  # Conversation mode
            preview_pane = self.conversation_preview
        else:  # Search mode
            preview_pane = self.preview
        
        # Restore button state
        preview_pane.btn_summarize.setEnabled(True)
        preview_pane.btn_summarize.setText("Summarize")
        
        # Replace the "Summarizing..." message with the actual summary in chat
        current_html = self.chat_view.toHtml()
        
        if summary and summary.strip():
            summary_html = f"Here's a summary of {name}:\n\n{summary}"
        else:
            summary_html = f"Summary unavailable for {name}. The file may not contain text content suitable for summarization."
        
        # Replace the "Summarizing..." message with the summary
        updated_html = current_html.replace("Summarizing...", summary_html)
        
        # Update the chat view with the new content
        self.chat_view.setHtml(updated_html)

    def _handle_summarize_error(self, error_msg: str):
        """Handle summarization errors."""
        # Stop the chat spinner
        self.chat_spinner.stop()
        
        # Determine which preview pane to use for button state
        if self.stack.currentIndex() == 1:  # Conversation mode
            preview_pane = self.conversation_preview
        else:  # Search mode
            preview_pane = self.preview
        
        # Restore button state
        preview_pane.btn_summarize.setEnabled(True)
        preview_pane.btn_summarize.setText("Summarize")
        
        # Replace the "Summarizing..." message with error in chat
        current_html = self.chat_view.toHtml()
        error_html = f"Error: {error_msg}"
        updated_html = current_html.replace("Summarizing...", error_html)
        
        # Update the chat view with the error message
        self.chat_view.setHtml(updated_html)

    def _open_chat_with_summary(self, name: str, path: str, summary: str):
        self.chat_spinner.stop()
        self._current_chat_file = path
        
        # Switch to conversation mode
        self.stack.setCurrentIndex(1)
        self._update_conversation_mode_indicator()
        
        # Replace the "Summarizing…" message with the actual summary
        # Get the current HTML content
        current_html = self.chat_view.toHtml()
        
        # Replace the "Summarizing…" message with the summary
        summary_html = f"Here's a summary of {name}:\n\n{summary}"
        updated_html = current_html.replace("Summarizing…", summary_html)
        
        # Update the chat view with the new content
        self.chat_view.setHtml(updated_html)
        
        # Show file in preview
        self.conversation_preview.set_file(path, self.ai_mode)
        self.conversation_preview.show()

    # QnA worker moved to luma_mod.ui.workers

    def _handle_chat_key_press(self, event: QKeyEvent):
        """Handle keyboard events in chat input."""
        if (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier) and 
            event.key() == Qt.Key.Key_Return):
            # Cmd/Ctrl+Enter submits the query
            self._ask_follow_up()
            event.accept()
        else:
            # Call the original keyPressEvent
            QLineEdit.keyPressEvent(self.chat_input, event)
    
    def handle_chat_link(self, url: QUrl, action="preview"):
        """Handle clicks on chat links."""
        from urllib.parse import parse_qs, unquote
        import subprocess
        import platform
        
        # Parse the custom luma:// URL scheme
        if url.scheme() == "luma":
            if url.host() == "select":
                path = unquote(parse_qs(url.query()).get("path", [""])[0])
                if action == "open":
                    # Open in OS
                    if platform.system() == "Windows":
                        os.startfile(path)  # type: ignore
                    elif platform.system() == "Darwin":  # macOS
                        subprocess.Popen(["open", path])
                    else:  # Linux
                        subprocess.Popen(["xdg-open", path])
                else:
                    # Show preview
                    self._show_preview_for(path)
            elif url.host() == "rag":
                # luma://rag?action=init
                action_param = (parse_qs(url.query()).get("action", [""])[0]).lower()
                if action_param == "init":
                    try:
                        from luma_mod.rag.service import ensure_index_started
                        ensure_index_started(self._folders, exclude=["node_modules", "__pycache__", ".git"])
                        self._add_ai_message("Indexing started. You can keep asking questions; results will improve as indexing progresses.")
                    except Exception:
                        self._add_ai_message("Failed to start indexing. Please try again.")
    
    def _show_preview_for(self, path: str):
        """Show preview for the given file path."""
        if hasattr(self, 'conversation_preview'):
            self.conversation_preview.set_file(path, self.ai_mode)
            self.conversation_preview.show()
            # Update the current selection
            self._current_selected_index = 0
            # Create FileHit object from path
            try:
                from .models import FileHit
                stat_info = os.stat(path)
                file_hit = FileHit(
                    path=path,
                    name=os.path.basename(path),
                    size=stat_info.st_size,
                    mtime=stat_info.st_mtime
                )
                self._current_conversation_hits = [file_hit]
            except Exception:
                self._current_conversation_hits = []

    def _ask_follow_up(self):
        q = self.chat_input.text().strip()
        if not q:
            return
        self.chat_input.clear()
        
        # Handle the query based on context
        if hasattr(self, "_current_chat_file") and self._current_chat_file:
            # File-specific Q&A
            # Add user bubble/spinner only for file-specific path
            self._add_user_message(q)
            self.chat_spinner.start()
            self.chat_view.append("AI is thinking…\n")
            self._qa_worker = QnAWorker(self.ai, self._current_chat_file, q)
            self._qa_worker.answer_ready.connect(self._apply_answer)
            self._qa_worker.start()
        else:
            # General AI query
            # Avoid duplicate bubbles: _handle_ai_query will add them
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
        # Switch back to No AI mode since main page only supports No AI
        self.ai_mode = "none"
        # Switch back to search mode
        self.stack.setCurrentIndex(0)
        # Hide summarize button since we're in No AI mode
        self.preview.btn_summarize.setVisible(False)
        # Also hide summarize button in conversation preview
        if hasattr(self, 'conversation_preview'):
            self.conversation_preview.btn_summarize.setVisible(False)
        # Update summarize button visibility for both previews
        self.preview.update_summarize_button_visibility(self.ai_mode)
        if hasattr(self, 'conversation_preview'):
            self.conversation_preview.update_summarize_button_visibility(self.ai_mode)
        # Hide folder selection controls on No AI page
        if hasattr(self, 'folder_btn'):
            self.folder_btn.setVisible(False)
        if hasattr(self, 'folder_chip'):
            self.folder_chip.setVisible(False)
        if hasattr(self, 'chat_folder_btn'):
            self.chat_folder_btn.setVisible(False)
        if hasattr(self, 'chat_folder_chip'):
            self.chat_folder_chip.setVisible(False)
        if hasattr(self, 'folder_dropdown'):
            self.folder_dropdown.setVisible(False)
        # Resize back to search mode
        self.resize(700, 160)
        self.setMinimumSize(700, 160)
        self.setMaximumSize(700, 800)
        # Update UI texts to reflect No AI mode
        self._update_ui_texts()
        # Update mode display after a short delay to ensure it's not overridden
        QTimer.singleShot(100, self._update_conversation_mode_indicator)

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

        QLabel#folderChip {background: rgba(59,130,246,0.08); border: 1px solid rgba(59,130,246,0.25); border-radius: 10px; padding: 4px 8px; color: #1e40af; font-size: 12px; margin-left: 6px; min-height: 24px;}
        
        QWidget#chatSpinnerHolder {
            background: transparent;
            border: none;
        }
        
        QWidget#conversationWidget {
            background: #ffffff;
            border-radius: 0px;
        }
        
        QTextEdit#conversationView {
            background: #ffffff;
            border: none;
            border-radius: 0px;
            padding: 16px;
            color: #1e293b;
            font-size: 14px;
            line-height: 1.5;
        }
        
        /* Chat bubble styling */
        QTextEdit#conversationView a {
            text-decoration: none;
            color: #3b82f6;
        }
        
        QTextEdit#conversationView a:hover {
            text-decoration: underline;
        }
        
        /* Button styling within chat */
        QTextEdit#conversationView button {
            background: #f1f5f9;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 11px;
            color: #374151;
        }
        
        QTextEdit#conversationView button:hover {
            background: #e5e7eb;
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
    # Warmup worker moved to luma_mod.ui.workers

    def _warmup_ai(self):
        try:
            self._warm = WarmupWorker(self.ai)
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

    def _open_rag_folder_dialog(self):
        """Multi-folder chooser for RAG indexing with clear guidance."""
        pass

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
        # Populate quick folder list with defaults + chosen
        if hasattr(self, 'folder_list'):
            self.folder_list.clear()
            known = list(dict.fromkeys([*self._rag_folders, *DEFAULT_FOLDERS]))
            for p in known:
                self.folder_list.addItem(p)
        
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
            # Force friendly placeholder regardless of previous state
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


