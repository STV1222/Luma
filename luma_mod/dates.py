from __future__ import annotations
import re, calendar
from datetime import datetime, timedelta
from typing import Tuple, Optional

DATE_PATTERNS = [
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\s*,?\s*\d{4}\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*,?\s*\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
]

MONTH_YEAR_PATTERNS = [
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b",
    r"\b\d{4}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\b",
    r"\b(20\d{2})-(0[1-9]|1[0-2])\b",
]

ABS_YEAR = re.compile(r"\b(20\d{2})\b")

REL_TIME_PATTERNS = [
    (r"\btoday\b", 0),
    (r"\byesterday\b", 1),
    (r"\blast\s+week\b", 7),
    (r"\blast\s+month\b", 30),
]

WEEKDAY_MAP = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

def extract_time_window(q: str) -> Tuple[float, float] | Tuple[None, None]:
    if not q: return (None, None)
    ql = q.lower(); now = datetime.now()
    # Handle numeric slash/date formats early: dd/mm/yyyy or mm/dd/yyyy or with dashes
    m = re.search(r"\b(\d{1,2})[\/-](\d{1,2})[\/\s-](\d{4})\b", q)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Disambiguate: if one part >12 it's the day; otherwise default to day-first (DD/MM)
        if a > 12 and 1 <= b <= 12:
            day, month = a, b
        elif b > 12 and 1 <= a <= 12:
            day, month = b, a
        else:
            day, month = a, b  # default DD/MM
        try:
            dt = datetime(y, month, day)
            s = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            e = dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
            return (s, e)
        except ValueError:
            pass
    for pat in DATE_PATTERNS:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            ds = m.group(0)
            for fmt in ["%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d"]:
                try:
                    dt = datetime.strptime(ds, fmt)
                    s = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                    e = dt.replace(hour=23, minute=59, second=59, microsecond=999999).timestamp()
                    return (s, e)
                except ValueError:
                    pass
    for pat in MONTH_YEAR_PATTERNS:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            token = m.group(0)
            year = None; month = None
            mnum = re.match(r"^(20\d{2})-(0[1-9]|1[0-2])$", token)
            if mnum:
                year = int(mnum.group(1)); month = int(mnum.group(2))
            else:
                parts = re.findall(r"(20\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*)", token, re.IGNORECASE)
                if len(parts) >= 2:
                    def to_month(p: str):
                        try: return datetime.strptime(p[:3].title(), "%b").month
                        except Exception: return None
                    if parts[0].isdigit():
                        year = int(parts[0]); month = to_month(parts[1])
                    else:
                        month = to_month(parts[0]); year = int(parts[1]) if parts[1].isdigit() else None
            if year and month:
                start = datetime(year, month, 1)
                last_day = calendar.monthrange(year, month)[1]
                end = datetime(year, month, last_day, 23, 59, 59, 999999)
                return (start.timestamp(), end.timestamp())
    for pat, days_back in REL_TIME_PATTERNS:
        if re.search(pat, ql):
            s = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            return (s, now.timestamp())
    # Relative weekday: "last monday", etc.
    m = re.search(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", ql)
    if m:
        wd = WEEKDAY_MAP.get(m.group(1))
        if wd is not None:
            delta = (now.weekday() - wd) % 7
            if delta == 0:
                delta = 7  # same weekday → last week's
            day = (now - timedelta(days=delta)).date()
            start = datetime(day.year, day.month, day.day)
            end = datetime(day.year, day.month, day.day, 23, 59, 59, 999999)
            return (start.timestamp(), end.timestamp())
    m = ABS_YEAR.search(q)
    if m:
        year = int(m.group(1)); s = datetime(year,1,1); e = datetime(year+1,1,1) - timedelta(seconds=1)
        return (s.timestamp(), e.timestamp())
    return (None, None)


