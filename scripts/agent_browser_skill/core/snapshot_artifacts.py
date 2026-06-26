from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .paths import ensure_inside


def _stamp(prefix: str) -> str:
    millis = int((time.time() % 1) * 1000)
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{millis:03d}-{prefix}"


def write_text_artifact(root: Path, paths: dict[str, Path], prefix: str, content: str) -> Path:
    target = ensure_inside(paths["logs"] / f"{_stamp(prefix)}.txt", root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def write_json_artifact(root: Path, paths: dict[str, Path], prefix: str, payload: Any) -> Path:
    target = ensure_inside(paths["logs"] / f"{_stamp(prefix)}.json", root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def compact_excerpt(text: Any, limit: int = 500) -> str:
    collapsed = " ".join(str(text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."


def parse_snapshot_json(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None
