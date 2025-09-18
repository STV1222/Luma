from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QMouseEvent, QKeyEvent
from PyQt6.QtWidgets import QTextBrowser


class ChatBrowser(QTextBrowser):
    """Custom QTextBrowser that can handle clicks on file/folder links."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.anchorClicked.connect(self._on_anchor_clicked)
        self._current_focused_element = None

    def _on_anchor_clicked(self, url: QUrl):
        """Handle single-click on links."""
        widget = self.parent()
        while widget and not hasattr(widget, 'handle_chat_link'):
            widget = widget.parent()
        if widget:
            widget.handle_chat_link(url, action="preview")

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double-click on links."""
        cursor = self.cursorForPosition(event.pos())
        if cursor.charFormat().isAnchor():
            href = cursor.charFormat().anchorHref()
            if href:
                widget = self.parent()
                while widget and not hasattr(widget, 'handle_chat_link'):
                    widget = widget.parent()
                if widget:
                    widget.handle_chat_link(QUrl(href), action="open")
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard navigation."""
        if event.key() == Qt.Key.Key_Up or event.key() == Qt.Key.Key_Down:
            self._navigate_results(event.key() == Qt.Key.Key_Down)
            event.accept()
        elif event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if self._current_focused_element:
                widget = self.parent()
                while widget and not hasattr(widget, 'handle_chat_link'):
                    widget = widget.parent()
                if widget:
                    widget.handle_chat_link(QUrl(self._current_focused_element), action="preview")
            event.accept()
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_O:
            if self._current_focused_element:
                widget = self.parent()
                while widget and not hasattr(widget, 'handle_chat_link'):
                    widget = widget.parent()
                if widget:
                    widget.handle_chat_link(QUrl(self._current_focused_element), action="open")
            event.accept()
        else:
            super().keyPressEvent(event)

    def _navigate_results(self, down: bool):
        """Navigate through results using arrow keys."""
        # Simplified placeholder implementation
        pass


