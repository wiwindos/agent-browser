from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

MONTHS = {"янв":1,"фев":2,"мар":3,"апр":4,"май":5,"мая":5,"июн":6,"июл":7,"авг":8,"сен":9,"окт":10,"ноя":11,"дек":12}

def normalize_timestamp(raw: Any, *, now: datetime | None = None) -> str | None:
    s = " ".join(str(raw or "").split()).lower()
    if not s:
        return None
    now = now or datetime.now(timezone.utc)
    tm = re.search(r"(\d{1,2}):(\d{2})", s)
    hh, mm = (int(tm.group(1)), int(tm.group(2))) if tm else (0, 0)
    if "вчера" in s or "yesterday" in s:
        d = now - timedelta(days=1)
        return d.replace(hour=hh, minute=mm, second=0, microsecond=0).isoformat()
    if "сегодня" in s or "today" in s:
        return now.replace(hour=hh, minute=mm, second=0, microsecond=0).isoformat()
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", s)
    if m:
        y = int(m.group(3)); y = 2000 + y if y < 100 else y
        try: return datetime(y, int(m.group(2)), int(m.group(1)), hh, mm, tzinfo=timezone.utc).isoformat()
        except ValueError: return None
    m = re.search(r"(\d{1,2})\s+([а-яa-z]{3,})\w*\s+(\d{4})", s)
    if m:
        mon = MONTHS.get(m.group(2)[:3])
        if mon:
            try: return datetime(int(m.group(3)), mon, int(m.group(1)), hh, mm, tzinfo=timezone.utc).isoformat()
            except ValueError: return None
    return None

def short_summary(text: str, limit: int = 220) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:limit] + ("..." if len(clean) > limit else "")

def summarize_posts(posts: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = []
    for p in posts:
        summaries.append({"post_id": p.get("post_id"), "author": p.get("author"), "datetime_iso": p.get("datetime_iso"), "summary": short_summary(str(p.get("text") or ""), 180)})
    authors = sorted({str(p.get("author")) for p in posts if p.get("author")})
    return {"posts": summaries, "summary": f"Structured {len(posts)} posts" + (f" from {', '.join(authors[:5])}" if authors else "")}

def filter_posts_by_date(posts: list[dict[str, Any]], target: str = "yesterday", *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    if target == "yesterday":
        wanted = (now - timedelta(days=1)).date()
    elif target == "today":
        wanted = now.date()
    else:
        wanted = datetime.fromisoformat(target.replace("Z", "+00:00")).date()
    out = []
    for p in posts:
        iso = p.get("datetime_iso") or normalize_timestamp(p.get("datetime_raw"), now=now)
        if not iso: continue
        if datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date() == wanted:
            q = dict(p); q["datetime_iso"] = iso; out.append(q)
    return out
