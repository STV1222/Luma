from __future__ import annotations
import re, calendar
from datetime import datetime, timedelta
from typing import Tuple, Optional

DATE_PATTERNS = [
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\s*,?\s*\d{4}\b",
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*,?\s*\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    # Chinese date patterns
    r"\b\d{1,2}/\d{1,2}\b",  # 8/31, 12/25, etc.
    r"\b\d{1,2}-\d{1,2}\b",  # 8-31, 12-25, etc.
    r"\b\d{1,2}月\d{1,2}日\b",  # 8月31日, 12月25日, etc.
    r"\b\d{1,2}月\d{1,2}号\b",  # 8月31号, 12月25号, etc.
]

MONTH_YEAR_PATTERNS = [
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b",
    r"\b\d{4}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\b",
    r"\b(20\d{2})-(0[1-9]|1[0-2])\b",
]

ABS_YEAR = re.compile(r"\b(20\d{2})\b")

REL_TIME_PATTERNS = [
    # English patterns
    (r"\btoday\b", 0),
    (r"\byesterday\b", 1),
    (r"\bday\s+before\s+yesterday\b", 2),
    (r"\blast\s+week\b", 7),
    (r"\blast\s+two\s+weeks\b", 14),
    (r"\bpast\s+two\s+weeks\b", 14),
    (r"\btwo\s+weeks\s+ago\b", 14),
    (r"\blast\s+month\b", 30),
    (r"\bthis\s+week\b", 0),
    (r"\bthis\s+month\b", 0),
    (r"\brecently\b", 7),
    
    # Chinese patterns
    (r"今天", 0),
    (r"昨天", 1),
    (r"前天", 2),
    (r"上週", 7),
    (r"上個月", 30),
    (r"這週", 0),
    (r"這個月", 0),
    (r"最近", 7),
    
    # Spanish patterns
    (r"\bhoy\b", 0),
    (r"\bayer\b", 1),
    (r"\bsemana\s+pasada\b", 7),
    (r"\bmes\s+pasado\b", 30),
    (r"\besta\s+semana\b", 0),
    (r"\beste\s+mes\b", 0),
    (r"\brecientemente\b", 7),
    
    # French patterns
    (r"\baujourd'hui\b", 0),
    (r"\bhier\b", 1),
    (r"\bsemaine\s+dernière\b", 7),
    (r"\bmois\s+dernier\b", 30),
    (r"\bcette\s+semaine\b", 0),
    (r"\bce\s+mois\b", 0),
    (r"\brécemment\b", 7),
    
    # German patterns
    (r"\bheute\b", 0),
    (r"\bgestern\b", 1),
    (r"\bletzte\s+woche\b", 7),
    (r"\bletzten\s+monat\b", 30),
    (r"\bdiese\s+woche\b", 0),
    (r"\bdiesen\s+monat\b", 0),
    (r"\bkürzlich\b", 7),
    
    # Japanese patterns
    (r"今日", 0),
    (r"昨日", 1),
    (r"先週", 7),
    (r"先月", 30),
    (r"今週", 0),
    (r"今月", 0),
    (r"最近", 7),
    
    # Korean patterns
    (r"오늘", 0),
    (r"어제", 1),
    (r"지난주", 7),
    (r"지난달", 30),
    (r"이번주", 0),
    (r"이번달", 0),
    (r"최근", 7),
    
    # Arabic patterns
    (r"اليوم", 0),
    (r"أمس", 1),
    (r"الأسبوع الماضي", 7),
    (r"الشهر الماضي", 30),
    (r"هذا الأسبوع", 0),
    (r"هذا الشهر", 0),
    (r"مؤخراً", 7),
    
    # Russian patterns
    (r"сегодня", 0),
    (r"вчера", 1),
    (r"на прошлой неделе", 7),
    (r"в прошлом месяце", 30),
    (r"на этой неделе", 0),
    (r"в этом месяце", 0),
    (r"недавно", 7),
]

WEEKDAY_MAP = {
    # English weekdays
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    
    # Chinese weekdays
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6,
    "週一": 0, "週二": 1, "週三": 2, "週四": 3, "週五": 4, "週六": 5, "週日": 6,
    
    # Spanish weekdays
    "lunes": 0, "martes": 1, "miércoles": 2, "jueves": 3, "viernes": 4, "sábado": 5, "domingo": 6,
    
    # French weekdays
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
    
    # German weekdays
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4, "samstag": 5, "sonntag": 6,
    
    # Japanese weekdays
    "月曜日": 0, "火曜日": 1, "水曜日": 2, "木曜日": 3, "金曜日": 4, "土曜日": 5, "日曜日": 6,
    "月曜": 0, "火曜": 1, "水曜": 2, "木曜": 3, "金曜": 4, "土曜": 5, "日曜": 6,
    
    # Korean weekdays
    "월요일": 0, "화요일": 1, "수요일": 2, "목요일": 3, "금요일": 4, "토요일": 5, "일요일": 6,
    "월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6,
    
    # Arabic weekdays
    "الاثنين": 0, "الثلاثاء": 1, "الأربعاء": 2, "الخميس": 3, "الجمعة": 4, "السبت": 5, "الأحد": 6,
    
    # Russian weekdays
    "понедельник": 0, "вторник": 1, "среда": 2, "четверг": 3, "пятница": 4, "суббота": 5, "воскресенье": 6,
}

def extract_time_window(q: str) -> Tuple[float, float] | Tuple[None, None]:
    if not q: return (None, None)
    ql = q.lower(); now = datetime.now()
    
    # Handle Chinese date formats like "8/31" or "8-31" (month/day without year)
    m = re.search(r"\b(\d{1,2})[\/-](\d{1,2})\b", q)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        print(f"🔍 Detected Chinese date format: {month}/{day}")
        # Try current year first
        try:
            dt = datetime(now.year, month, day)
            # If the date is in the future, use previous year
            if dt > now:
                dt = datetime(now.year - 1, month, day)
            s = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            e = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            print(f"📅 Parsed date range: {dt.strftime('%Y-%m-%d')} to {(dt + timedelta(days=1)).strftime('%Y-%m-%d')}")
            return (s, e)
        except ValueError:
            print(f"❌ Invalid date: {month}/{day}")
            pass
    
    # Handle Chinese date formats like "8月31日" or "8月31号"
    m = re.search(r"\b(\d{1,2})月(\d{1,2})[日号]\b", q)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            dt = datetime(now.year, month, day)
            # If the date is in the future, use previous year
            if dt > now:
                dt = datetime(now.year - 1, month, day)
            s = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            e = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            return (s, e)
        except ValueError:
            pass
    
    # Handle Chinese relative dates like "八月底" (end of August)
    m = re.search(r"\b(\d{1,2})月底\b", q)
    if m:
        month = int(m.group(1))
        print(f"🔍 Detected Chinese month-end format: {month}月底")
        try:
            # Get the last day of the month
            if month == 12:
                next_month = datetime(now.year + 1, 1, 1)
            else:
                next_month = datetime(now.year, month + 1, 1)
            last_day = (next_month - timedelta(days=1)).day
            
            dt = datetime(now.year, month, last_day)
            # If the date is in the future, use previous year
            if dt > now:
                dt = datetime(now.year - 1, month, last_day)
                if month == 12:
                    next_month = datetime(now.year, 1, 1)
                else:
                    next_month = datetime(now.year, month + 1, 1)
                last_day = (next_month - timedelta(days=1)).day
                dt = datetime(now.year - 1, month, last_day)
            
            s = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            e = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            print(f"📅 Parsed month-end date range: {dt.strftime('%Y-%m-%d')} to {(dt + timedelta(days=1)).strftime('%Y-%m-%d')}")
            return (s, e)
        except ValueError:
            print(f"❌ Invalid month: {month}")
            pass
    
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
            e = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
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
                    e = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
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
                next_month = datetime(year, month + 1, 1) if month < 12 else datetime(year + 1, 1, 1)
                end = next_month
                return (start.timestamp(), end.timestamp())
    # "<Month> this year" or "this <Month>"
    m = re.search(r"\b(?:in\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(?:this|current)\s+year\b", ql)
    if not m:
        m = re.search(r"\b(?:this|current)\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", ql)
    if m:
        try:
            mon = datetime.strptime(m.group(1)[:3].title(), "%b").month
            y = datetime.now().year
            start = datetime(y, mon, 1)
            next_month = datetime(y, mon + 1, 1) if mon < 12 else datetime(y + 1, 1, 1)
            end = next_month
            return (start.timestamp(), end.timestamp())
        except Exception:
            pass
    # "this month" and "this year"
    if re.search(r"\bthis\s+month\b|\bcurrent\s+month\b", ql):
        y, mon = datetime.now().year, datetime.now().month
        start = datetime(y, mon, 1)
        next_month = datetime(y, mon + 1, 1) if mon < 12 else datetime(y + 1, 1, 1)
        end = next_month
        return (start.timestamp(), end.timestamp())
    if re.search(r"\bthis\s+year\b|\bcurrent\s+year\b", ql):
        y = datetime.now().year
        start = datetime(y, 1, 1)
        end = datetime(y + 1, 1, 1)
        return (start.timestamp(), end.timestamp())
    # Check Chinese weekday patterns first (more specific than general time patterns)
    # Chinese last weekday patterns: "上週二" (last Tuesday), "上星期二" (last Tuesday)
    m = re.search(r"上週(一|二|三|四|五|六|日)", q)
    if not m:
        m = re.search(r"上(一|二|三|四|五|六|日)", q)
    if m:
        weekday_name = f"週{m.group(1)}"
        wd = WEEKDAY_MAP.get(weekday_name)
        if wd is not None:
            delta = (now.weekday() - wd) % 7
            if delta == 0:
                delta = 7  # same weekday → last week's
            day = (now - timedelta(days=delta)).date()
            start = datetime.combine(day, datetime.min.time())
            end = datetime.combine(day + timedelta(days=1), datetime.min.time())
            return (start.timestamp(), end.timestamp())
    
    for pat, days_back in REL_TIME_PATTERNS:
        if re.search(pat, ql):
            s = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            return (s, now.timestamp())
    # Specific weekday in this week: "wednesday this week" / "this wednesday"
    m = re.search(r"\b(?:on\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(?:this|current)\s+week\b", ql)
    if not m:
        m = re.search(r"\b(?:this|current)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", ql)
    if m:
        wd = WEEKDAY_MAP.get(m.group(1))
        if wd is not None:
            start_of_week = now - timedelta(days=now.weekday())
            day = (start_of_week + timedelta(days=wd))
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = (day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return (start.timestamp(), end.timestamp())
    
    # Chinese weekday patterns: "這週二" (this Tuesday), "本週二" (this Tuesday)
    m = re.search(r"(?:這|本)週(一|二|三|四|五|六|日)", q)
    if not m:
        m = re.search(r"(?:這|本)週(一|二|三|四|五|六|日)", q)
    if m:
        weekday_name = f"週{m.group(1)}"
        wd = WEEKDAY_MAP.get(weekday_name)
        if wd is not None:
            start_of_week = now - timedelta(days=now.weekday())
            day = (start_of_week + timedelta(days=wd))
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = (day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return (start.timestamp(), end.timestamp())
    
    # This week range (Monday 00:00 → now)
    if re.search(r"\bthis\s+week\b|\bcurrent\s+week\b|這週|本週", ql):
        start_of_week = now - timedelta(days=now.weekday())
        start = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        return (start.timestamp(), now.timestamp())
    
    # Relative weekday: "last monday", etc.
    m = re.search(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", ql)
    if m:
        wd = WEEKDAY_MAP.get(m.group(1))
        if wd is not None:
            delta = (now.weekday() - wd) % 7
            if delta == 0:
                delta = 7  # same weekday → last week's
            day = (now - timedelta(days=delta)).date()
            start = datetime.combine(day, datetime.min.time())
            end = datetime.combine(day + timedelta(days=1), datetime.min.time())
            return (start.timestamp(), end.timestamp())
    m = ABS_YEAR.search(q)
    if m:
        year = int(m.group(1)); s = datetime(year,1,1); e = datetime(year+1,1,1) - timedelta(seconds=1)
        return (s.timestamp(), e.timestamp())
    return (None, None)


