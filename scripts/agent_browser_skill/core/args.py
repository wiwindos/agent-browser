from __future__ import annotations

from agent_browser_skill.core.config import BROWSER_TOOL_LOCK_WAIT_SECONDS, DEFAULT_TIMEOUT, MAX_TIMEOUT


def timeout_from(args: dict[str, object]) -> int:
    try:
        timeout = int(args.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return max(1, min(timeout, MAX_TIMEOUT))


def int_arg(
    args: dict[str, object],
    name: str,
    default: int,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    try:
        value = int(args.get(name) if args.get(name) is not None else default)
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def bool_arg(args: dict[str, object], name: str, default: bool = False) -> bool:
    if name not in args:
        return default
    value = args.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on", "РґР°"}:
        return True
    if text in {"0", "false", "no", "n", "off", "РЅРµС‚"}:
        return False
    return default


def lock_wait_seconds_from(args: dict[str, object]) -> float:
    try:
        wait = float(args.get("lock_wait_seconds") or BROWSER_TOOL_LOCK_WAIT_SECONDS)
    except (TypeError, ValueError):
        wait = BROWSER_TOOL_LOCK_WAIT_SECONDS
    return max(0.0, min(wait, 60.0))
