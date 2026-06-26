from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from agent_browser_skill.errors import ToolError


def emit(success: bool, output: str = "", error: str = "", metadata: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "success": success,
        "output": redact(output),
        "error": redact(error),
    }
    if metadata:
        payload["metadata"] = metadata
    print(json.dumps(payload, ensure_ascii=False))


def redact(value: Any) -> str:
    text = "" if value is None else str(value)
    if not text:
        return text
    text = re.sub(
        r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|authorization|otp|2fa|mfa)\s*[:=]\s*([^\s\"']+)",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]{16,}", "Bearer [REDACTED]", text)
    return text


def cap_output(value: str, limit: int = 12000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated by agent-browser skill]"


def load_request(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def workspace_root(request: dict[str, Any]) -> Path:
    ctx = request.get("context") or {}
    cwd = Path(ctx.get("cwd") or os.getcwd()).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    return cwd


def pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def success_or_raise(code: int, output: str) -> str:
    if code != 0:
        raise ToolError(output or f"agent-browser exited with code {code}")
    return output or "(empty output)"


def metadata(paths: dict[str, Path]) -> dict[str, Any]:
    return {
        "site_key": paths["site"].name,
        "profile": str(paths["profile"]),
        "artifact_dir": str(paths["artifact"]),
        "screenshots_dir": str(paths["screenshots"]),
        "downloads_dir": str(paths["downloads"]),
        "logs_dir": str(paths["logs"]),
    }
