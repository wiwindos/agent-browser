from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .paths import ensure_inside


def structured_logs_dir(root: Path) -> Path:
    path = ensure_inside(root / ".agent-browser" / "logs", root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def tool_runs_log_path(root: Path) -> Path:
    return ensure_inside(structured_logs_dir(root) / "tool-runs.jsonl", root)


def make_run_id() -> str:
    return uuid.uuid4().hex


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_jsonable(inner) for inner in value]
    return value


def append_tool_log(root: Path, event: dict[str, Any]) -> Path:
    payload = dict(event)
    payload.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    payload.setdefault("pid", os.getpid())
    target = tool_runs_log_path(root)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True) + "\n")
    return target
