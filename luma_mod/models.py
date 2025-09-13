from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, QAbstractListModel, QModelIndex, QSize, QFileInfo
from PyQt6.QtWidgets import QFileIconProvider, QStyledItemDelegate, QStyleOptionViewItem
from PyQt6.QtGui import QIcon

from .utils import human_size, elide_middle


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
        from PyQt6.QtGui import QPainter
        h: FileHit = idx.model().item(idx.row())  # type: ignore
        if not h: return super().paint(p,opt,idx)
        p.save(); r=opt.rect
        icon:QIcon = idx.data(Qt.ItemDataRole.DecorationRole)
        dpr = p.device().devicePixelRatioF() if hasattr(p.device(), 'devicePixelRatioF') else 1.0
        icon_size = 16
        gap_px = 12
        size_px = int(icon_size * dpr)
        pix = icon.pixmap(size_px, size_px)
        try: pix.setDevicePixelRatio(dpr)
        except Exception: pass
        f=p.font(); f.setPointSize(f.pointSize()+1); f.setBold(True); p.setFont(f)
        fm = p.fontMetrics()
        base_y = r.top()+24
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


