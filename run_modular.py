#!/usr/bin/env python3
from __future__ import annotations
import sys
from PyQt6.QtWidgets import QApplication

# Check for required dependencies
try:
    import openai
    print("OpenAI dependency found ✓")
except ImportError:
    print("Warning: OpenAI not installed. Cloud mode will not work.")
    print("Install with: pip install openai")

from luma_mod.main_ui import SpotlightUI


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Luma (Modular)")
    ui = SpotlightUI()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())



