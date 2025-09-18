## Luma (Modular)

A privacy‑first, local Spotlight‑style search app with an optional AI assistant and a built‑in private RAG (Retrieval‑Augmented Generation) index for cross‑document Q&A.

### What it is
- Fast local file search with intelligent matching and recency boosts
- Modern, compact UI with split preview and a chat view for AI features
- Optional AI modes:
  - No AI: classic local search only
  - Private Mode: local LLM via Ollama for intent parsing, rerank, summaries, and Q&A
  - Cloud Mode: OpenAI for parsing, summaries, and Q&A (your choice; off by default)
- Private RAG: index your own PDFs, Docs, Slides, and text locally; ask questions with inline citations

No telemetry. Everything runs locally unless you explicitly enable Cloud Mode.

---

## Requirements

- Python 3.10+
- PyQt6
- macOS, Linux, or Windows

Optional (recommended):
- pdf2image + Poppler (for PDF thumbnails)
- Pillow (for image previews)
- rapidfuzz (better fuzzy filename matching)
- sentence-transformers + faiss-cpu (for local RAG)
- pypdf, python-docx, python-pptx, chardet (text extraction for RAG)
- langchain-community + ollama (for Private Mode AI)
- openai (for Cloud Mode AI)

Install core UI:
```bash
pip install PyQt6
```

Add optional features as you need them:
```bash
# Image previews, better fuzzy matching, and PDF thumbs
pip install Pillow rapidfuzz pdf2image
# macOS: required backend for pdf2image
brew install poppler

# Local AI (Private Mode)
pip install langchain-community
# Install and run Ollama separately, then pull a model
# See: https://ollama.com
ollama pull gemma2:2b

# Local RAG (cross‑document Q&A)
pip install sentence-transformers faiss-cpu pypdf python-docx python-pptx chardet watchdog

# Cloud AI (OpenAI)
pip install openai
```

---

## Run

```bash
python3 run_luma.py
# or
python -m luma_mod
```

The main window starts compact. Type to search; the results panel and preview expand automatically when there’s input.

Default search folders (local search only):
- `~/Desktop`, `~/Documents`, `~/Downloads`, `~/Pictures`

You can change these defaults in `luma_mod/utils.py` (`DEFAULT_FOLDERS`).

---

## Configuration

- `LUMA_AI_MODE`: default AI mode at startup. Values: `none` | `private` | `cloud` (default: `none`).
- `OPENAI_API_KEY`: required for Cloud Mode (OpenAI).

Examples:
```bash
export LUMA_AI_MODE=private
export OPENAI_API_KEY=sk-...
```

Notes:
- PDF thumbnails use Poppler; the app auto-detects common locations (`/opt/homebrew/bin`, `/usr/local/bin`, `/usr/bin`). If missing, install via `brew install poppler` (macOS).

---

## Using the app

- Type to search. Results update after ~150ms of inactivity in No AI mode
- Arrow Up/Down to navigate results
- Double‑click a result to open it in your OS
- Select a result to see a rich preview: image/PDF thumbnail and metadata

### AI modes
Use the “Ask AI” button in the search bar to switch modes:
- No AI: local filename search only (fastest)
- Private Mode: uses a local LLM via Ollama for
  - smart intent parsing → better filters and ranking
  - optional re‑ranking with guardrails
  - file summarization
  - cross‑document questions via local RAG with citations
- Cloud Mode: same features but uses OpenAI

Notes:
- Private/Cloud modes switch the UI to a chat‑style page for richer interactions.
- Cmd/Ctrl+Enter in the chat input submits the message.
- Summarize appears only in AI modes and for text‑like files.

### Folder scope chip and RAG folders
- The “Folders” button lets you pick folders for RAG. When you press “Use”, the index is rebuilt to only include those folders.
- A small chip shows the active scope (All folders, one folder name, or a count).

---

## Local RAG (cross‑document Q&A)

The local RAG stores a vector index and metadata sidecar under your home directory:
- Index: `~/.luma/rag_db/faiss.index`
- Meta:  `~/.luma/rag_db/meta.jsonl`

Supported document types for RAG:
- `.pdf`, `.docx`, `.pptx`, `.txt`, `.md`, `.markdown`, `.html`, `.htm`

How to initialize the RAG index from the command line:
```bash
# First build (can take a while)
python -m luma_mod.rag.service --init --folders ~/Documents

# Check status
python -m luma_mod.rag.service --status
```

In the UI (AI modes):
- Click “Folders” → choose folders → “Use” to rebuild the index only for those folders
- Ask a question like “What does the ACME contract say about termination?”
- Answers include inline citations like [1], [2] with source cards
- If RAG confidence is low or the index is empty, the UI will guide you to index

Reset the index:
- Delete `~/.luma/rag_db/faiss.index` and `~/.luma/rag_db/meta.jsonl`, or
- Rebuild from the UI by selecting new folders (the app calls a replace‑style reindex)

Watcher note:
- The CLI `--watch` flag is reserved; a blocking watcher loop isn’t provided in this minimal service. The UI triggers incremental reindexing as needed.

---

## Search behavior (No AI mode)

- Keyword scoring on filenames and directory names
- Optional fuzzy matching via `rapidfuzz`
- Strong boosts for prefix matches and multi‑word phrase hits
- Recency boost favors recently modified items
- Time filtering uses modified time by default; creation time is used when the AI explicitly asks for it in AI modes
- Up to 50 top results (`MAX_RESULTS` in `luma_mod/utils.py`)

In AI modes, the system can:
- Parse intent and propose smarter `file_types`, time windows, and folders
- Re‑rank candidate files using only names/paths with guardrails (time, types, folders)
- Route between local listing and RAG Q&A automatically

---

## Summaries and Q&A about a single file (AI modes)

- Select a result, then click “Summarize” to generate a concise 3‑sentence summary
- In the chat page, you can ask follow‑up questions about the same file
- Private Mode uses a local LLM if available; Cloud Mode uses OpenAI

---

## Translations

The UI includes a language selector under Settings. Available translations live under `luma_mod/translations/`.

---

## CLI reference (RAG)

```bash
python -m luma_mod.rag.service --init --folders <folder1> <folder2> ...
python -m luma_mod.rag.service --status
```

- `--init`: Build/refresh the index for the provided folders. Skips `node_modules`, `__pycache__`, `.git`, and hidden/system directories.
- `--folders`: One or more folders to index recursively. If omitted, defaults to `~/Documents`.
- `--status`: Prints a short JSON‑like status with last update and indexed chunk count.

The UI also calls the same service internally to manage indices.

---

## Architecture map

- Entry: `run_luma.py` or `python -m luma_mod` → `luma_mod.main_ui.SpotlightUI`
- Package entry: `luma_mod/__main__.py`
- Config: `luma_mod/config.py` (env‑based defaults for AI)
- UI: `luma_mod/main_ui.py`
  - Search page with results and preview
  - Chat page for AI modes (Ask AI, Summarize, RAG answers)
  - Settings page (language)
  - Helpers: `luma_mod/ui/chat_browser.py`, `luma_mod/ui/workers.py`
- Search: `luma_mod/search_core.py`
  - File walking, filename scoring, fuzzy matching, recency boost, time filters
- AI: `luma_mod/ai.py`
  - Non‑AI parsing fallback
  - Private Mode via Ollama; Cloud Mode via OpenAI
  - RAG routing and answer prompt with citations
  - Optional AI re‑ranking of filenames/paths
- RAG: `luma_mod/rag/`
  - `indexer.py`: extract text, chunk (1200/200), embed (MiniLM), FAISS store, JSONL meta
  - `query.py`: cosine search via IndexFlatIP; prompt builder with citations
  - `service.py`: CLI and Python API (`ensure_index_started`, `rag_answer`, `get_status`)
  - `watcher.py`: optional filesystem watcher (reserved/auxiliary)
- Widgets/Preview: `luma_mod/widgets.py`
  - PDF thumbnails via `pdf2image`+Poppler, images via Pillow, Quick Look on macOS
- Models: `luma_mod/models.py` (results list and delegate)
- Dates: `luma_mod/dates.py` (absolute/relative time parsing)
- Utils: `luma_mod/utils.py` (defaults, OS helpers, formatting)
- i18n: `luma_mod/i18n.py` + `luma_mod/translations/*`

---

## Tests

Basic tests for the RAG components live under `tests/`.

Run all tests:
```bash
python -m pytest -q
```

Useful target:
```bash
python -m pytest -q tests/test_rag.py
```

---

## Keyboard shortcuts

- Enter: run search (and submit in AI chat)
- Up/Down: move selection
- Double‑click: open selected file in OS
- Cmd/Ctrl+Enter (chat): submit message

---

## Privacy

- Local search, previews, and RAG run on your machine
- Private Mode uses a local LLM via Ollama
- Cloud Mode sends only the necessary text snippets and your prompts to your provider (OpenAI)
- No telemetry

---

## Troubleshooting

- PDF thumbnails are blank on macOS
  - Install Poppler: `brew install poppler`
- RAG says “Not enough info…”
  - Initialize the index and/or add more folders
  - Ensure `faiss-cpu` and `sentence-transformers` are installed
- Local AI doesn’t respond in Private Mode
  - Ensure Ollama is running and a model is available: `ollama run gemma2:2b`
- Cloud Mode doesn’t work
  - Install `openai` and set your API key (the app may also provide a UI field):
    - `export OPENAI_API_KEY=sk-...` (macOS/Linux)
    - `setx OPENAI_API_KEY "sk-..."` (Windows PowerShell)
- Missing previews for Office files on macOS
  - Quick Look is used; if it fails, a generic icon is shown

---

## FAQ

- Where are the RAG files stored?
  - `~/.luma/rag_db/faiss.index` and `~/.luma/rag_db/meta.jsonl`
- How do I rebuild from scratch?
  - Delete the two files above, or re‑select folders in the UI to trigger a fresh index
- Which files are supported by RAG?
  - `.pdf`, `.docx`, `.pptx`, `.txt`, `.md`, `.markdown`, `.html`, `.htm`
- Does search scan system folders?
  - No. `IGNORE_DIRS` filters common system/build/cache directories, and hidden folders are skipped
- Can I still run the original app?
  - Yes, if `version2.py` exists in your repo, it remains runnable: `python3 version2.py`

---

Happy searching!


