from __future__ import annotations
import os
from typing import Optional


def get_openai_api_key() -> Optional[str]:
    """Read OpenAI API key from environment.

    Environment variable: OPENAI_API_KEY
    Returns None if not set.
    """
    key = os.getenv("OPENAI_API_KEY")
    return key if key else None


def get_default_ai_mode() -> str:
    """Return default AI mode from environment.

    Environment variable: LUMA_AI_MODE (values: none|private|cloud)
    Defaults to "none" for privacy and performance.
    """
    mode = (os.getenv("LUMA_AI_MODE") or "none").strip().lower()
    if mode not in {"none", "private", "cloud"}:
        return "none"
    return mode


