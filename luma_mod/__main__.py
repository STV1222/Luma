from __future__ import annotations
import os
import sys


def _prime_environment() -> None:
    # Keep heavy libs polite on CPU threads by default
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


def _dependency_warnings() -> None:
    # Optional dependency hints for Cloud Mode
    try:
        import openai  # noqa: F401
        print("OpenAI dependency found ✓")
    except Exception:
        print("Warning: OpenAI not installed. Cloud mode will not work.")
        print("Install with: pip install openai")


def main() -> int:
    _prime_environment()
    _dependency_warnings()

    from PyQt6.QtWidgets import QApplication
    from .main_ui import SpotlightUI

    app = QApplication(sys.argv)
    app.setApplicationName("Luma (Modular)")
    ui = SpotlightUI()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())


