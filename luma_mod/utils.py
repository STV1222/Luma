from __future__ import annotations
import os, platform, math, subprocess, re
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import QWidget, QFrame, QMessageBox
from PyQt6.QtCore import Qt

# ----------------------- constants / config -----------------------
# User spaces only - exclude system/cache folders
DEFAULT_FOLDERS = [os.path.expanduser("~/Desktop"),
                   os.path.expanduser("~/Documents"),
                   os.path.expanduser("~/Downloads"),
                   os.path.expanduser("~/Pictures")]

# Exclude hidden files, caches, system folders
IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".Trash",
    ".DS_Store", ".localized", "Library", "System", "Applications",
    ".cache", ".tmp", ".temp", "cache", "tmp", "temp"
}
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

def make_paths_clickable(text: str) -> str:
    """Convert file and folder paths in text to clickable HTML links."""
    # Pattern to match file/folder paths
    # Matches paths starting with / or ~ or drive letters (Windows)
    # Also matches relative paths that look like file/folder names
    path_pattern = r'''
        (?:
            # Absolute paths starting with / or ~
            (?:/|~)[^\s<>"']+ |
            # Windows drive paths (C:, D:, etc.)
            [A-Za-z]:[\\/][^\s<>"']+ |
            # Relative paths that look like files/folders
            (?:[a-zA-Z0-9_-]+[\\/])*[a-zA-Z0-9_.-]+(?:\.[a-zA-Z0-9]+)?
        )
        (?=\s|$|[.,;:!?])
    '''
    
    def replace_path(match):
        path = match.group(0).strip()
        
        # Skip if it looks like a URL or email
        if path.startswith(('http://', 'https://', 'ftp://', 'mailto:')):
            return path
            
        # Skip if it's just a single word without path separators
        if '/' not in path and '\\' not in path and not path.startswith('~'):
            # Only consider it a file if it has an extension
            if '.' not in path or path.count('.') > 1:
                return path
        
        # Check if the path exists (file or directory)
        expanded_path = os.path.expanduser(path)
        if os.path.exists(expanded_path):
            # Determine if it's a file or folder
            if os.path.isfile(expanded_path):
                icon = "📄"
                action = "openFile"
            elif os.path.isdir(expanded_path):
                icon = "📁"
                action = "openFolder"
            else:
                return path
                
            # Create clickable link using proper HTML anchor tags
            if os.path.isfile(expanded_path):
                href = f"file://{expanded_path}"
            else:
                href = f"folder://{expanded_path}"
            
            return f'<a href="{href}" style="color: #3b82f6; text-decoration: none; border-bottom: 1px dotted #3b82f6;">{icon} {path}</a>'
        
        return path
    
    # Apply the pattern with the replacement function
    result = re.sub(path_pattern, replace_path, text, flags=re.VERBOSE | re.IGNORECASE)
    return result

# ----------------------------- folder matching ----------------------------
def _folder_similarity(name: str, hint: str) -> float:
    base = name.lower(); h = hint.lower().strip()
    if not h:
        return 0.0
    if h in base:
        return 100.0
    try:
        from rapidfuzz import fuzz  # type: ignore
        return float(fuzz.partial_ratio(h, base))
    except Exception:
        return 0.0

def find_dirs_by_hint(roots: list[str], hint: str, max_hits: int = 8) -> list[str]:
    """Search for directories whose basename matches the hint.
    Only scans under the provided roots, skipping IGNORE_DIRS and hidden dirs.
    Returns up to max_hits directories sorted by similarity.
    """
    if not hint:
        return []
    candidates: list[tuple[float, str]] = []
    # First pass: check immediate children of roots (fast and precise)
    for root in roots:
        try:
            for entry in os.listdir(root):
                p = os.path.join(root, entry)
                if os.path.isdir(p) and not entry.startswith('.') and entry not in IGNORE_DIRS:
                    s = _folder_similarity(entry, hint)
                    if s > 0:
                        candidates.append((s, p))
        except Exception:
            continue
    if candidates:
        top = sorted(candidates, key=lambda x: x[0], reverse=True)[:max_hits]
        return [p for _s, p in top]
    # Second pass: deep scan, but avoid over-pruning root levels
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, _files in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith('.')]
            score = _folder_similarity(os.path.basename(dirpath), hint)
            if score > 0:
                candidates.append((score, dirpath))
            if len(candidates) >= max_hits * 5:
                # Only prune deeper levels; keep top-level traversal so we don't miss obvious matches
                try:
                    depth = os.path.relpath(dirpath, root).count(os.sep)
                except Exception:
                    depth = 0
                if depth >= 1:
                    dirnames[:] = []
    top = sorted(candidates, key=lambda x: x[0], reverse=True)[:max_hits]
    return [p for _s, p in top]

def find_dirs_by_tokens(roots: list[str], tokens: list[str], threshold: float = 85.0, max_hits: int = 3) -> list[str]:
    """Try to match tokens to immediate child folder names of roots.
    Returns directories whose basename matches any token with similarity >= threshold.
    """
    if not tokens:
        return []
    try:
        from rapidfuzz import fuzz  # type: ignore
    except Exception:
        fuzz = None  # type: ignore
    names = []
    for root in roots:
        try:
            for entry in os.listdir(root):
                p = os.path.join(root, entry)
                if os.path.isdir(p) and not entry.startswith('.') and entry not in IGNORE_DIRS:
                    names.append((entry, p))
        except Exception:
            continue
    hits: list[str] = []
    for token in tokens:
        t = token.strip().lower()
        if not t:
            continue
        for entry, path in names:
            base = entry.lower()
            sim = 100.0 if t == base else (_folder_similarity(base, t) if fuzz else (100.0 if t in base else 0.0))
            if sim >= threshold and path not in hits:
                hits.append(path)
    return hits[:max_hits]

def find_exact_folder_match(folder_name: str, search_roots: list[str] = None) -> list[str]:
    """Find exact folder matches using a broader search approach like Raycast.
    Searches recursively in common locations and user directories for exact folder name matches.
    """
    if not folder_name:
        return []
    
    # Define search roots - start with common locations
    if search_roots is None:
        search_roots = [
            os.path.expanduser("~"),  # Home directory
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Documents"), 
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Pictures"),
            os.path.expanduser("~/Music"),
            os.path.expanduser("~/Movies"),
        ]
    
    exact_matches = []
    folder_lower = folder_name.lower().strip()
    
    # First pass: exact matches in immediate children (fastest)
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                if entry.lower() == folder_lower:
                    path = os.path.join(root, entry)
                    if os.path.isdir(path) and path not in exact_matches:
                        exact_matches.append(path)
        except Exception:
            continue
    
    # If we found exact matches in immediate children, return them
    if exact_matches:
        return exact_matches[:3]  # Limit to top 3 exact matches
    
    # Second pass: recursive search for exact matches (like Raycast)
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, dirnames, _files in os.walk(root):
                # Skip hidden directories and common ignore directories
                dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in IGNORE_DIRS]
                
                # Check if current directory matches
                current_dir = os.path.basename(dirpath)
                if current_dir.lower() == folder_lower:
                    if dirpath not in exact_matches:
                        exact_matches.append(dirpath)
                        if len(exact_matches) >= 3:  # Limit to 3 matches
                            break
        except Exception:
            continue
        
        if len(exact_matches) >= 3:
            break
    
    # If we found exact matches, return them
    if exact_matches:
        return exact_matches[:3]
    
    # Third pass: case-insensitive partial matches in immediate children
    partial_matches = []
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                if folder_lower in entry.lower():
                    path = os.path.join(root, entry)
                    if os.path.isdir(path) and path not in partial_matches:
                        partial_matches.append(path)
        except Exception:
            continue
    
    return partial_matches[:3]  # Limit to top 3 partial matches


