from __future__ import annotations
import json
from typing import Any, Dict, Optional
from urllib.request import urlopen
from urllib.error import URLError

from .dates import extract_time_window
from .utils import FILETYPE_MAP
from .content import extract_text_from_file

try:
    from langchain_community.llms import Ollama
    from langchain.callbacks.manager import CallbackManager
    from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
    HAVE_OLLAMA = True
except Exception:
    HAVE_OLLAMA = False

def extract_keywords(q: str):
    import re
    from .utils import STOPWORDS
    quoted = re.findall(r'"([^\"]+)"', q)
    q_wo = re.sub(r'"[^\"]+"', ' ', q)
    words = re.findall(r"[A-Za-z0-9_\-]+", q_wo)
    return [*quoted, *[w for w in words if w.lower() not in STOPWORDS]]

def strip_time_keywords(keywords, original_query, time_range):
    import re
    if not keywords:
        return keywords
    months = {
        "jan","january","feb","february","mar","march","apr","april","may","jun","june",
        "jul","july","aug","august","sep","sept","september","oct","october","nov","november","dec","december"
    }
    noise = {"edited","created","modified","updated","on","in","during","between","from","to","at"}
    has_time = time_range and time_range != (None, None)
    cleaned = []
    for w in keywords:
        wl = w.lower()
        if wl in noise: continue
        if wl in months: continue
        if has_time and re.fullmatch(r"20\d{2}", wl): continue
        cleaned.append(w)
    return cleaned

class LumaAI:
    def __init__(self) -> None:
        self._model = None

    def _ensure(self) -> bool:
        if not HAVE_OLLAMA:
            return False
        # Quick health check to avoid long blocking if Ollama isn't running
        try:
            urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5).read(1)
        except URLError:
            return False
        except Exception:
            return False
        if self._model is None:
            try:
                self._model = Ollama(model="mistral",
                                     callback_manager=CallbackManager([StreamingStdOutCallbackHandler()]))
            except Exception:
                return False
        return True

    def parse_query_nonai(self, query: str) -> Dict[str, Any]:
        tr = extract_time_window(query)
        kws = strip_time_keywords(extract_keywords(query), query, tr)
        return {"keywords": kws, "time_range": None if tr==(None,None) else tr, "file_types": [], "time_attr": "mtime"}

    def parse_query_ai(self, query: str) -> Dict[str, Any]:
        if not self._ensure() or not query.strip():
            return self.parse_query_nonai(query)
        prompt = (
            "Extract a JSON object for a file search UI.\n"
            "Fields: keywords (array), time_range (string date or null), "
            "file_types (array like ['pdf','png'] or []), action ('edited'|'created').\n"
            f"Query: {query}\nJSON:"
        )
        try:
            raw = self._model.invoke(prompt).strip()
            if not raw.startswith("{"): raw = raw[raw.find("{"):]
            if not raw.endswith("}"): raw = raw[:raw.rfind("}")+1]
            data = json.loads(raw)
            tr_model = extract_time_window(str(data.get("time_range","")) or "")
            tr_query = extract_time_window(query)
            def span(t):
                if not t or t==(None,None): return 0
                s,e=t; 
                if s is None or e is None: return 0
                return max(0, e - s)
            tr = tr_query if span(tr_query) > span(tr_model) else tr_model
            allow = ['.'+e.lstrip('.') for e in data.get("file_types", [])]
            time_attr = "birthtime" if str(data.get("action","")).lower().startswith("creat") else "mtime"
            kws = data.get("keywords", []) or extract_keywords(query)
            kws = strip_time_keywords(kws, query, tr)
            return {"keywords": kws, "time_range": None if tr==(None,None) else tr,
                    "file_types": allow, "time_attr": time_attr}
        except Exception:
            return self.parse_query_nonai(query)


    def summarize_file(self, path: str, max_chars: int = 10_000) -> Optional[str]:
        if not self._ensure():
            return None
        text = extract_text_from_file(path)
        if not text:
            return None
        text = text[:max_chars]
        prompt = (
            "You are a helpful assistant. Read the following file content and produce a very concise summary in at most 3 sentences. "
            "Focus on the main purpose, key ideas, and any clear outcomes. Use plain language.\n\n"
            f"CONTENT:\n{text}\n\nSUMMARY:" 
        )
        try:
            out = self._model.invoke(prompt)
            return out.strip()
        except Exception:
            return None

    def answer_about_file(self, path: str, question: str, max_chars: int = 12_000) -> Optional[str]:
        if not self._ensure():
            return None
        base = extract_text_from_file(path)
        if not base:
            return None
        context = base[:max_chars]
        prompt = (
            "You are assisting with questions about a specific file. Use the provided file content as context."
            " If the answer is not clearly present, say you are not sure. Keep answers concise.\n\n"
            f"FILE CONTENT:\n{context}\n\n"
            f"QUESTION: {question}\n\nANSWER:"
        )
        try:
            out = self._model.invoke(prompt)
            return out.strip()
        except Exception:
            return None

