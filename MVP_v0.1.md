# MVP v0.1

# Luma - Desktop Spotlight-Style File Search (MVP v0.1)

## 🔎 Overview

**Luma** is a privacy-first, desktop Spotlight-style file search application that helps you find and open files on your computer using natural language queries.

Unlike traditional search tools (Spotlight, Windows Search), Luma:

- Runs **fully local** (no cloud, no data leaves your computer)
- Features a **modern Spotlight-style UI** with real-time search
- Supports **natural language queries** with smart parsing
- Provides **instant visual feedback** with file previews
- Offers **cross-platform compatibility** with native look and feel

Think of it as **"Spotlight for your files"** with AI-powered natural language understanding.

---

## ✨ Features in MVP v0.1

### 🎨 Modern UI
- **Spotlight-style interface**: Frameless, translucent window with rounded corners
- **Real-time search**: Instant results as you type with debounced search
- **File preview pane**: Visual previews for images and file metadata
- **Keyboard navigation**: Full keyboard support with shortcuts
- **Native file icons**: System-provided file type icons

### 🔍 Smart Search
- **Natural language queries**:
    - Keywords: `find my acme invoice`
    - File types: `show me pdf files`, `find word docs`
    - Time ranges: `find last week's ppt files`, `open yesterday's pdf`
    - Combined queries: `resume pdf from 2023`
- **Fuzzy matching**: Uses rapidfuzz for intelligent filename matching
- **Recency boost**: Recently modified files rank higher
- **File type filtering**: Filter by Documents, Images, Code, etc.

### ⚡ Quick Actions
- **Double-click or Enter**: Open selected file
- **Right-click context menu**: 
    - Open file
    - Reveal in Finder/Explorer
    - Copy path to clipboard
    - Quick Look (macOS)
    - Open with specific app (macOS)
- **Keyboard shortcuts**:
    - `Ctrl/Cmd+F`: Focus search
    - `Ctrl/Cmd+C`: Copy path
    - `Ctrl/Cmd+Y`: Quick Look (macOS)
    - `Escape`: Close application

### 🛡️ Privacy & Performance
- **100% local**: No internet calls, no telemetry, no data collection
- **Threaded search**: Non-blocking UI with background file scanning
- **Smart indexing**: Ignores system directories (.git, node_modules, etc.)
- **Memory efficient**: Only loads file metadata, not content

---

## 🚀 Getting Started

### Requirements

- **Python 3.9+**
- **PyQt6** (for the modern UI)
- **Optional dependencies** for enhanced features:
    - `rapidfuzz` - Better fuzzy matching
    - `Pillow` - Image preview support

### Installation

```bash
# Install required dependencies
pip install PyQt6

# Optional: Enhanced features
pip install rapidfuzz Pillow
```

### Running Luma

```bash
python local_file_copilot.py
```

### Default Search Folders

Luma searches these directories by default:
- `~/Documents`
- `~/Downloads` 
- `~/Desktop`

You can modify the `DEFAULT_FOLDERS` list in the script to customize search locations.

---

## 🎯 Usage Examples

### Basic Search
- Type `invoice` to find files with "invoice" in the name
- Type `pdf` to find PDF files
- Type `today` to find files modified today

### Advanced Queries
- `resume pdf from 2023` - Find PDF files with "resume" from 2023
- `presentation last week` - Find presentation files from last week
- `"project proposal" docx` - Find Word docs with exact phrase "project proposal"

### File Management
- **Open**: Double-click or press Enter
- **Reveal**: Right-click → "Reveal in Finder"
- **Copy Path**: Right-click → "Copy Path" or Ctrl/Cmd+C
- **Quick Look**: Right-click → "Quick Look" (macOS)

---

## 🔧 Technical Details

### Architecture
- **UI Framework**: PyQt6 for cross-platform native look
- **Search Engine**: Custom fuzzy matching with recency scoring
- **Threading**: QThread-based background search to keep UI responsive
- **File System**: os.walk() with intelligent directory filtering

### Performance
- **Debounced search**: 220ms delay to avoid excessive file system calls
- **Smart filtering**: Ignores hidden directories and common build folders
- **Result limiting**: Maximum 50 results to maintain responsiveness
- **Memory efficient**: Only stores file metadata, not content

### Cross-Platform Support
- **macOS**: Native file operations, Quick Look integration
- **Windows**: Explorer integration, native file handling
- **Linux**: xdg-open integration for file operations