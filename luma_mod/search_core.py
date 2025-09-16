from __future__ import annotations
import os, time, heapq
import shlex
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
        if base.startswith(k): 
            score+=100  # Highest priority for prefix matches
        elif k in base: 
            score+=60   # Good for substring matches
        elif HAVE_RAPIDFUZZ: 
            # Enhanced fuzzy matching with better scoring
            fuzzy_score = fuzz.partial_ratio(k, base)
            if fuzzy_score > 80:
                score += fuzzy_score * 0.8  # High fuzzy match
            elif fuzzy_score > 60:
                score += fuzzy_score * 0.6  # Medium fuzzy match
            else:
                score += fuzzy_score * 0.3  # Low fuzzy match
    return score/max(1,len(kws))

def intelligent_filename_score(name: str, semantic_keywords: List[str], file_patterns: List[str]) -> float:
    """Enhanced filename scoring using AI understanding."""
    base = name.lower()
    score = 0.0
    
    # Score based on semantic keywords (higher weight)
    for kw in semantic_keywords:
        k = kw.lower()
        if base.startswith(k):
            score += 120  # Highest priority for semantic prefix matches
        elif k in base:
            score += 80   # High priority for semantic substring matches
        elif HAVE_RAPIDFUZZ:
            fuzzy_score = fuzz.partial_ratio(k, base)
            if fuzzy_score > 70:
                score += fuzzy_score * 0.9  # High fuzzy match for semantic terms
    
    # Score based on file patterns (medium weight)
    for pattern in file_patterns:
        p = pattern.lower()
        if base.startswith(p):
            score += 100  # High priority for pattern prefix matches
        elif p in base:
            score += 60   # Medium priority for pattern substring matches
        elif HAVE_RAPIDFUZZ:
            fuzzy_score = fuzz.partial_ratio(p, base)
            if fuzzy_score > 70:
                score += fuzzy_score * 0.7  # Medium fuzzy match for patterns
    
    # Normalize score
    total_terms = len(semantic_keywords) + len(file_patterns)
    if total_terms == 0:
        return 50.0
    return score / total_terms

def recency_boost(mtime: float) -> float:
    age = max(0.0,(time.time()-mtime)/86400.0)
    if age<1: return 40
    if age<7: return 25
    if age<30: return 15
    if age<180: return 8
    return 0

def search_files(folders: List[str], keywords: List[str], allow_exts: List[str],
                 time_range: Optional[Tuple[float,float]], time_attr: str="mtime", 
                 semantic_keywords: List[str] = None, file_patterns: List[str] = None) -> List[Tuple[str,float]]:
    tmin,tmax = (time_range or (None,None))
    allow=[e.lower() for e in allow_exts] if allow_exts else []
    k = MAX_RESULTS if isinstance(MAX_RESULTS, int) and MAX_RESULTS > 0 else 50
    top_heap: list[tuple[float, str]] = []  # min-heap on score
    for root in folders:
        if not os.path.isdir(root): continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Clean up dirnames but keep them for scoring
            original_dirnames = dirnames[:]
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith('.')]
            
            # Score and add directories that match search criteria
            for dirname in dirnames:
                if dirname in IGNORE_DIRS or dirname.startswith('.'):
                    continue
                dir_path = os.path.join(dirpath, dirname)
                
                # Compute directory name score
                if semantic_keywords and file_patterns:
                    base_score = intelligent_filename_score(dirname, semantic_keywords, file_patterns)
                else:
                    base_score = filename_score(dirname, keywords)
                
                if base_score <= 0:
                    continue
                
                # If no time filtering, we can prune by current heap minimum before stat
                if tmin is None and tmax is None and len(top_heap) >= k and base_score <= top_heap[0][0]:
                    continue
                
                try:
                    st = os.stat(dir_path)
                    tstamp = st.st_mtime if time_attr=="mtime" else getattr(st, "st_birthtime", st.st_ctime)
                    if tmin is not None and tmax is not None:
                        d = datetime.fromtimestamp(tstamp).date()
                        min_date = datetime.fromtimestamp(tmin).date()
                        max_date = datetime.fromtimestamp(tmax).date()
                        if not (min_date <= d <= max_date):
                            continue
                    elif tmin is not None and tstamp < tmin: continue
                    elif tmax is not None and tstamp > tmax: continue
                except Exception:
                    continue
                
                score = base_score + recency_boost(st.st_mtime)
                if score <= 0:
                    continue
                if len(top_heap) < k:
                    heapq.heappush(top_heap, (score, dir_path))
                else:
                    if score > top_heap[0][0]:
                        heapq.heapreplace(top_heap, (score, dir_path))
            
            # Score and add files
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                if allow and os.path.splitext(fn)[1].lower() not in allow: continue
                # Compute filename score first to avoid expensive stats when irrelevant
                if semantic_keywords and file_patterns:
                    # Use intelligent scoring with AI understanding
                    base_score = intelligent_filename_score(fn, semantic_keywords, file_patterns)
                else:
                    # Use traditional scoring
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
                        min_date = datetime.fromtimestamp(tmin).date()
                        max_date = datetime.fromtimestamp(tmax).date()
                        if not (min_date <= d <= max_date):
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


