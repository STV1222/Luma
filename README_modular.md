## Luma (Modular) - How to Run

This modular version keeps your original `version2.py` untouched and runnable.
The modular build splits the code into smaller files under `luma_mod/` for easier debugging and UI iteration.

### Files
- `run_modular.py`: Entry point
- `luma_mod/utils.py`: Constants and helpers (paths, sizes, UI helpers)
- `luma_mod/dates.py`: Date parsing and time-window extraction
- `luma_mod/search_core.py`: File walking, scoring, and filtering
- `luma_mod/ai.py`: AI/non-AI query parsing and keyword cleanup; routes cross-document questions to local RAG
- `luma_mod/widgets.py`: Spinner, toggle, and preview pane (with Quick Look/PDF/Images)
- `luma_mod/models.py`: Results model and list delegate
- `luma_mod/main_ui.py`: Assembles the UI
 - `luma_mod/rag/`: Local RAG (embeddings + FAISS) for cross-document Q&A
   - `indexer.py`: extract, chunk (1200/200), embed (MiniLM), store to FAISS + meta.jsonl
   - `query.py`: cosine search via IndexFlatIP, prompt builder with citations
   - `service.py`: CLI and Python API (`ensure_index_started`, `rag_answer`, `get_status`)
   - `watcher.py`: filesystem watcher (optional)

### Requirements
- Python 3.10+
- PyQt6
- Optional: `pdf2image` + Poppler (`brew install poppler` on macOS)
- Optional: `rapidfuzz` for better fuzzy filename matching
- Optional: `Pillow` for image previews
- Optional: `langchain` & an Ollama model if you want AI parsing

Install common deps:
```bash
pip install PyQt6 pdf2image pillow rapidfuzz
# AI (optional)
pip install langchain
```

Additional deps for local RAG:
```bash
pip install sentence-transformers faiss-cpu pypdf python-docx python-pptx watchdog chardet
```

### Run
```bash
python3 run_modular.py
```

### Local RAG quickstart

Initialize the local RAG index (first run can take a while):

```bash
python -m luma_mod.rag.service --init --folders ~/Documents
```

Check status:

```bash
python -m luma_mod.rag.service --status
```

Where the DB lives:

- Index: `~/.luma/rag_db/faiss.index`
- Meta: `~/.luma/rag_db/meta.jsonl`

Privacy: No files are uploaded; only top snippets may be sent to the model at query time (Cloud Mode).

The original app still runs via:
```bash
python3 version2.py
```


