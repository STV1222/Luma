from __future__ import annotations
import os, time, heapq
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Optional

from .utils import IGNORE_DIRS, MAX_RESULTS

try:
    from rapidfuzz import fuzz
    HAVE_RAPIDFUZZ = True
except Exception:
    HAVE_RAPIDFUZZ = False

def filename_score(name: str, kws: List[str]) -> float:
    base = name.lower()
    if not kws: return 50.0
    score=0.0
    for kw in kws:
        k=kw.lower()
        if k in base: score+=60
        elif HAVE_RAPIDFUZZ: score += fuzz.partial_ratio(k, base)*0.6
    return score/max(1,len(kws))

def recency_boost(mtime: float) -> float:
    age = max(0.0,(time.time()-mtime)/86400.0)
    if age<1: return 40
    if age<7: return 25
    if age<30: return 15
    if age<180: return 8
    return 0

def search_files(folders: List[str], keywords: List[str], allow_exts: List[str],
                 time_range: Optional[Tuple[float,float]], time_attr: str="mtime") -> List[Tuple[str,float]]:
    tmin,tmax = (time_range or (None,None))
    allow=[e.lower() for e in allow_exts] if allow_exts else []
    k = MAX_RESULTS if isinstance(MAX_RESULTS, int) and MAX_RESULTS > 0 else 50
    top_heap: list[tuple[float, str]] = []  # min-heap on score
    for root in folders:
        if not os.path.isdir(root): continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith('.')]
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                if allow and os.path.splitext(fn)[1].lower() not in allow: continue
                # Compute filename score first to avoid expensive stats when irrelevant
                base_score = filename_score(fn, keywords)
                if base_score <= 0:
                    continue
                # If no time filtering, we can prune by current heap minimum before stat
                if tmin is None and tmax is None and len(top_heap) >= k and base_score <= top_heap[0][0]:
                    continue
                try:
                    st = os.stat(path)
                    tstamp = st.st_mtime if time_attr=="mtime" else getattr(st, "st_birthtime", st.st_ctime)
                    if tmin is not None and tmax is not None:
                        d = datetime.fromtimestamp(tstamp).date()
                        if not (datetime.fromtimestamp(tmin).date() <= d <= datetime.fromtimestamp(tmax).date()):
                            continue
                    elif tmin is not None and tstamp < tmin: continue
                    elif tmax is not None and tstamp > tmax: continue
                except Exception:
                    continue
                score = base_score + recency_boost(st.st_mtime)
                if score <= 0:
                    continue
                if len(top_heap) < k:
                    heapq.heappush(top_heap, (score, path))
                else:
                    if score > top_heap[0][0]:
                        heapq.heapreplace(top_heap, (score, path))
    top_sorted = sorted(top_heap, key=lambda x: x[0], reverse=True)
    return [(p, s) for s, p in [(sc, pa) for (sc, pa) in top_sorted]]


