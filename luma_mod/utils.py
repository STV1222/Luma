from __future__ import annotations
import os, platform, math, subprocess
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import QWidget, QFrame, QMessageBox
from PyQt6.QtCore import Qt

# ----------------------- constants / config -----------------------
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

STOPWORDS = {"find","show","get","open","the","a","an","me","my","files","file","of","for","about","last","this","that","these","those","recent","latest"}


# ----------------------------- helpers ----------------------------
def is_macos() -> bool: return platform.system().lower().startswith("darwin")
def is_windows() -> bool: return platform.system().lower().startswith("win")

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
    g = w.screen().availableGeometry() if hasattr(w, 'screen') and w.screen() else None
    if not g:
        from PyQt6.QtWidgets import QApplication
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


