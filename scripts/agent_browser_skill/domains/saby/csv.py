from __future__ import annotations

import csv
import io
from typing import Any


CSV_HEADERS = ["i", "publishDate", "publishDateKey", "internalId", "link", "raw", "collectedStep"]


def csv_text_for_items(items: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for item in items:
        writer.writerow(item)
    return buf.getvalue()
