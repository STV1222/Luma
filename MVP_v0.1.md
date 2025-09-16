# MVP v0.1

### Luma — Desktop Spotlight-Style File Search (Modular MVP)

## 🔎 Overview

**Luma** is a privacy‑first, local Spotlight‑style search app. Type a few words (or a date like "Apr 2024" or "last week") and instantly see the top matching files with thumbnails and metadata. Optionally, toggle Ask AI to help parse natural language queries and even summarize a selected file.

- **Fully local**: No data leaves your machine
- **Modern UI**: Frameless, translucent window with split preview
- **Fast**: Debounced search with a lightweight index (filenames + metadata)
- **Helpful AI (optional)**: Local LLM parsing + per‑file summary and Q&A

Think of it as "Spotlight for your files" with optional on‑device AI assistance.

---

## ✨ MVP Features

- **Modern UI**
  - Frameless translucent window with rounded corners
  - Split view: results list + preview pane with file metadata
  - Keyboard navigation (Up/Down), double‑click to open

- **Smart, fast search**
  - Natural language keywords: `find acme invoice`
  - Time ranges: `yesterday`, `last week`, `Apr 2024`, `2023‑08‑14`, `12/09/2025`
    - Combined: `resume from 2023`
  - Fuzzy matching (if `rapidfuzz` is installed)
  - Recency boost favors recently modified files

- **Preview pane**
  - Images: inline thumbnails (Qt/Pillow)
  - PDFs: first‑page thumbnail (`pdf2image` + Poppler)
  - Office/text on macOS: Quick Look thumbnails when available
  - Metadata: name, path, type, size, modified

- **AI (optional)**
  - Ask AI toggle: local LLM helps parse keywords, time range, and file types
  - Summarize button: generate a concise 3‑sentence summary of the selected file
  - Follow‑up Q&A: ask questions about the summarized file in a simple chat view
  - Graceful fallback to non‑AI parsing if AI is unavailable

- **Privacy & performance**
  - 100% local; no telemetry
  - Threaded background work for search and AI tasks
  - Ignores common build/system folders (e.g., `.git`, `node_modules`, `__pycache__`)
  - Returns up to 50 top results to stay responsive

---

## 🚀 How to Run

### Requirements

- Python 3.10+
- PyQt6
- Optional:
    - `rapidfuzz` — better fuzzy matching
    - `Pillow` — image previews
    - `pdf2image` + Poppler — PDF thumbnails (macOS: `brew install poppler`)
  - `langchain-community` + `ollama` — Ask AI, Summarize, and Q&A (local LLM)

### Install

```bash
# Core UI
pip install PyQt6

# Optional features
pip install rapidfuzz Pillow pdf2image langchain-community
# macOS: Poppler for pdf2image backend
brew install poppler

# Optional: Local LLM for Ask AI + Summarize/Q&A
# Install and run Ollama separately, then pull a model (Gemma 2 2B)
ollama pull gemma2:2b
```

### Run the modular app

```bash
python run_modular.py
```

The original single‑file app still runs via:

```bash
python version2.py
```

### Default search folders

- `~/Documents`
- `~/Downloads`
- `~/Desktop`

Change these in `luma_mod/utils.py` (`DEFAULT_FOLDERS`).

---

## 🎯 Usage

- Type to search; results update after ~150ms of inactivity
- Press Enter to search (or to run Ask AI when toggled)
- Use Up/Down to navigate; double‑click to open a file
- Select a file to see preview and metadata
- Click Summarize to get a short summary (requires local AI)
- In the chat view, ask follow‑up questions about the same file; click ← to return

Examples:

- `invoice` — filename contains invoice
- `presentation last week` — recent presentations
- `Apr 2024` or `2024-04-20` — date filters
- `resume from 2023` — year filter

---

## 🧱 Architecture & Code Map

- Entry point: `run_modular.py` → `luma_mod.main_ui.SpotlightUI`
- UI assembly: `luma_mod/main_ui.py`
  - Search input, Ask AI toggle, spinner
  - `SearchWorker` (QThread) → background search
  - `AIWorker` (QThread) → AI query parsing
  - Preview pane (`PreviewPane`) with Summarize button
  - Summary/Q&A chat page with back button
- Models & rendering: `luma_mod/models.py`
  - `FileHit` dataclass
  - `ResultsModel` (Qt list model)
  - `ResultDelegate` for custom list row painting
- Search engine: `luma_mod/search_core.py`
  - `search_files(folders, keywords, allow_exts, time_range, time_attr)`
  - Filename scoring with optional `rapidfuzz`
  - Recency boost and time filtering
  - Directory filtering and top‑K heap for responsiveness
- Dates: `luma_mod/dates.py`
  - Parses absolute dates (multiple formats), months, years, relative ranges (today/yesterday/last week), and weekday phrases
- AI: `luma_mod/ai.py`
  - Non‑AI parsing fallback (keywords + time window)
  - Ollama‑powered parsing, summarization, and file Q&A via `langchain-community`
- Widgets & preview: `luma_mod/widgets.py`
  - `BusySpinner`, `ToggleSwitch`, `PreviewPane` (images/PDF/Quick Look)
- Utilities: `luma_mod/utils.py`
  - Defaults (`DEFAULT_FOLDERS`, `MAX_RESULTS`), platform helpers, sizes, centering, `os_open`

---

## ⚙️ Behaviors & Limits

- Debounced search: 150ms (UI stays snappy while typing)
- Top results: up to 50 (`MAX_RESULTS`)
- Time attribute: modified time by default; AI can switch to created/birth time
- Previews depend on optional deps and OS support
- AI features require a running local Ollama server; otherwise the app uses non‑AI parsing

---

## 🛡️ Privacy

- All search and previews are local
- AI, when enabled, uses a local model via Ollama
- No external telemetry or cloud calls

---

## Repo structure

```
run_modular.py              # Entry point for modular UI
luma_mod/
  main_ui.py               # Assembles UI, search & AI workers, chat view
  models.py                # Qt model and delegate
  search_core.py           # File scanning, scoring, filtering
  dates.py                 # Natural language date parsing
  ai.py                    # AI and non‑AI query parsing; summarize & Q&A
  widgets.py               # Spinner, toggle, preview pane (PDF/images/Quick Look)
  utils.py                 # Defaults, helpers, platform ops
version2.py                # Original single‑file app (still runnable)
```