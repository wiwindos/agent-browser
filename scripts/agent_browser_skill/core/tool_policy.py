from __future__ import annotations

import re
from typing import Any

GENERIC_BROWSER_CONTENT_ACTIONS = {"run_command", "read_file", "list_directory", "search_files", "fetch_page", "write_file"}
BROWSER_FORBIDDEN_FALLBACK_PATTERNS = [
    "curl ",
    "wget ",
    "requests",
    "beautifulsoup",
    "bs4",
    "lxml",
    "fetch_page",
    "pip install",
]
PROTECTED_PATH_PATTERNS = (
    re.compile(r"/workspace(?:/[^\s'\"]*)?"),
    re.compile(r"/data/skills/agent-browser(?:/[^\s'\"]*)?"),
    re.compile(r"(?:^|[\\/\s])browser-artifacts(?:[\\/\s]|$)"),
)
COMMAND_LIKE_PATTERNS = (
    re.compile(r"\bfind\s+/workspace\b", re.I),
    re.compile(r"\bcurl\b[^\n]*(?:https?://|4pda|/workspace|browser-artifacts)", re.I),
    re.compile(r"\bwget\b[^\n]*(?:https?://|4pda|/workspace|browser-artifacts)", re.I),
    re.compile(r"\bpip(?:3)?\s+install\b", re.I),
    re.compile(r"\bpython3?\s+<<\s*['\"]?PYEOF['\"]?", re.I),
    re.compile(r"\b(requests|beautifulsoup|bs4|lxml|fetch_page)\b", re.I),
)
BROWSER_CONTENT_ACTIONS = [
    "page_markdown",
    "read_page_md",
    "read_artifact_by_id",
    "search_artifact",
    "read_artifact_slice",
    "click_handle",
    "fill_handle",
    "select_handle",
    "wait_ready",
    "get_page_text",
    "find_text",
    "extract_forum_posts",
    "extract_article",
    "extract_table",
    "extract_search_results",
    "list_artifacts",
]


def debug_admin_allowed(args: dict[str, Any]) -> bool:
    ctx = args.get("_context") if isinstance(args.get("_context"), dict) else {}
    return bool(
        args.get("debug_admin")
        or args.get("allow_generic_tools")
        or ctx.get("debug_admin")
        or ctx.get("admin_debug")
        or ctx.get("allow_generic_tools")
    )


def active_browser_session(args: dict[str, Any]) -> bool:
    ctx = args.get("_context") if isinstance(args.get("_context"), dict) else {}
    source = str(ctx.get("source") or ctx.get("route") or ctx.get("skill") or "")
    return bool(
        args.get("session_id")
        or ctx.get("session_id")
        or source == "skill_agent-browser_browser"
        or "agent-browser" in source
    )


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for k, v in value.items():
            out.extend(_flatten_strings(k))
            out.extend(_flatten_strings(v))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    return []


def protected_browser_content_request(action: str, args: dict[str, Any]) -> tuple[bool, str | None]:
    if not active_browser_session(args) or debug_admin_allowed(args):
        return False, None
    strings = _flatten_strings({k: v for k, v in args.items() if k != "_context"})
    haystack = "\n".join(strings)
    if action in GENERIC_BROWSER_CONTENT_ACTIONS:
        return True, f"BLOCKED_BROWSER_WORKFLOW_FALLBACK: {action} is blocked for active browser sessions; use browser artifact/extraction actions instead"
    if any(pattern.search(haystack) for pattern in PROTECTED_PATH_PATTERNS):
        return True, "direct access to browser workspace, skill files, or browser-artifacts is blocked for active browser sessions"
    if any(pattern.search(haystack) for pattern in COMMAND_LIKE_PATTERNS):
        return True, "BLOCKED_BROWSER_WORKFLOW_FALLBACK: command-like browser content access is blocked for active browser sessions"
    return False, None


def next_action_for_blocked(action: str, args: dict[str, Any], state: dict[str, Any]) -> str:
    text = "\n".join(_flatten_strings(args)).lower()
    allowed = state.get("next_allowed_actions") or []
    artifact_id = str(state.get("artifact_id") or "")
    markdown_known = artifact_id.startswith("md_") or state.get("phase") == "MARKDOWN_READY"
    if markdown_known:
        for candidate in ("read_page_md", "read_artifact_by_id", "search_artifact"):
            if candidate in allowed or candidate in BROWSER_CONTENT_ACTIONS:
                return candidate
    if "page_markdown" in allowed or state.get("phase") in {"READY", "LOADED", "EXTRACTED"}:
        return "page_markdown"
    if "browser-artifacts" in text or action in {"read_file", "list_directory", "search_files"}:
        return "read_artifact_by_id" if "read_artifact_by_id" in allowed else "search_artifact"
    if "4pda" in text or "forum" in text:
        return "page_markdown"
    if state.get("phase") in {"OPENED", "NEW"}:
        return "wait_ready"
    return allowed[0] if allowed else BROWSER_CONTENT_ACTIONS[0]
