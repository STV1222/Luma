## Luma (Modular) - How to Run

This modular version keeps your original `version2.py` untouched and runnable.
The modular build splits the code into smaller files under `luma_mod/` for easier debugging and UI iteration.

### Files
- `run_modular.py`: Entry point
- `luma_mod/utils.py`: Constants and helpers (paths, sizes, UI helpers)
- `luma_mod/dates.py`: Date parsing and time-window extraction
- `luma_mod/search_core.py`: File walking, scoring, and filtering
- `luma_mod/ai.py`: AI/non-AI query parsing and keyword cleanup
- `luma_mod/widgets.py`: Spinner, toggle, and preview pane (with Quick Look/PDF/Images)
- `luma_mod/models.py`: Results model and list delegate
- `luma_mod/main_ui.py`: Assembles the UI

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

### Run
```bash
python3 run_modular.py
```

The original app still runs via:
```bash
python3 version2.py
```


