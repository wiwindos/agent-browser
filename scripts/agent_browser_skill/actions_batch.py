from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_browser_skill.core.output import cap_output, metadata, success_or_raise
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime.bootstrap import ab


def normalize_batch_commands(commands: Any) -> list[Any]:
    if not isinstance(commands, list) or not commands:
        raise ToolError("commands must be a non-empty array")
    normalized = []
    for item in commands:
        if isinstance(item, str):
            normalized.append(item)
        elif isinstance(item, list) and item and all(isinstance(part, (str, int, float, bool)) for part in item):
            normalized.append([str(part) for part in item])
        else:
            raise ToolError("each batch command must be a string or a simple array")
    return normalized


def action_batch(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    commands = normalize_batch_commands(args.get("commands"))
    if all(isinstance(item, list) for item in commands):
        code, out = ab(root, paths, args, ["batch", "--json"], input_json=commands)
    else:
        string_commands = [" ".join(item) if isinstance(item, list) else item for item in commands]
        code, out = ab(root, paths, args, ["batch", "--bail"] + string_commands)
    return cap_output(success_or_raise(code, out)), metadata(paths)


def action_run(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    task = str(args.get("task") or "").strip()
    if not task:
        raise ToolError("task is required for run")
    code, out = ab(root, paths, args, ["-q", "chat", task])
    return success_or_raise(code, out), metadata(paths)
