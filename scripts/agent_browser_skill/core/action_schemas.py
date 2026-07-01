from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent_browser_skill.errors import ToolError

ERROR_CODES = {"VALIDATION_ERROR", "NAVIGATION_ERROR", "EXTRACTION_ERROR", "BLOCKED", "BLOCKED_PENDING_WORKFLOW_GATE", "INTERNAL_ERROR"}
PHASES = ["NEW", "OPENED", "READY", "LOADED", "MARKDOWN_READY", "EXTRACTED", "ANSWER_READY", "DONE"]
NEXT_ALLOWED = {
    "NEW": ["open_page", "desktop_open", "list_artifacts"],
    "OPENED": ["wait_ready", "screenshot", "desktop_open"],
    "READY": ["wait_ready", "page_markdown", "read_page_md", "page_markdown.act", "click_handle", "fill_handle", "select_handle", "get_page_text", "get_title", "find_text", "extract_links", "extract_blocks", "extract_article", "extract_table", "extract_search_results", "extract_updates_by_date", "extract_forum_posts", "filter_by_date", "summarize_posts", "scroll_until_stable", "click_text", "click_selector", "read_artifact_by_id", "search_artifact", "read_artifact_slice", "screenshot", "list_artifacts"],
    "LOADED": ["wait_ready", "page_markdown", "read_page_md", "page_markdown.act", "click_handle", "fill_handle", "select_handle", "get_page_text", "get_title", "find_text", "extract_links", "extract_blocks", "extract_article", "extract_table", "extract_search_results", "extract_updates_by_date", "extract_forum_posts", "filter_by_date", "summarize_posts", "scroll_until_stable", "click_text", "click_selector", "read_artifact_by_id", "search_artifact", "read_artifact_slice", "screenshot", "list_artifacts"],
    "MARKDOWN_READY": ["read_page_md", "read_artifact", "read_artifact_by_id", "search_artifact", "read_artifact_slice", "page_markdown.act", "click_handle", "fill_handle", "select_handle", "page_markdown", "scroll_until_stable", "navigate_pagination", "click_text", "click_selector", "find_text", "extract_links", "extract_blocks", "extract_article", "extract_table", "extract_search_results", "extract_updates_by_date", "extract_forum_posts", "filter_by_date", "summarize_posts", "summarize_artifact", "list_artifacts"],
    "EXTRACTED": ["read_page_md", "read_artifact", "read_artifact_by_id", "search_artifact", "read_artifact_slice", "page_markdown.act", "click_handle", "fill_handle", "select_handle", "page_markdown", "scroll_until_stable", "navigate_pagination", "filter_by_date", "summarize_posts", "summarize_artifact", "list_artifacts"],
    "ANSWER_READY": ["list_artifacts", "open_page", "desktop_open"],
    "DONE": ["open_page", "desktop_open", "list_artifacts"],
}

class ValidationError(ToolError):
    pass

@dataclass(frozen=True)
class Field:
    typ: type | tuple[type, ...]
    required: bool = False
    default: Any = None
    choices: set[Any] | None = None
    min_value: int | float | None = None
    max_value: int | float | None = None

@dataclass(frozen=True)
class Schema:
    fields: dict[str, Field] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)

SCHEMAS: dict[str, Schema] = {
    "open_page": Schema({"url": Field(str, True), "profile": Field(str, False, "default"), "wait_until": Field(str, False, "networkidle", {"load", "domcontentloaded", "networkidle"}), "json": Field(bool, False, True)}, {"url_or_page": "url"}),
    "open": Schema({"url": Field(str, True), "profile": Field(str, False, "default"), "wait_until": Field(str, False, "networkidle", {"load", "domcontentloaded", "networkidle"}), "json": Field(bool, False, True)}, {"url_or_page": "url"}),
    "desktop_open": Schema({"url": Field(str), "profile": Field(str, False, "default"), "wait_until": Field(str, False, "domcontentloaded")}, {"url_or_page": "url"}),
    "page_markdown": Schema({"max_chars": Field(int, False, 3000, min_value=500, max_value=12000), "max_blocks": Field(int, False, 220, min_value=20, max_value=1000), "max_elements": Field(int, False, 250, min_value=20, max_value=1000)}),
    "page_markdown.get": Schema({"max_chars": Field(int, False, 3000, min_value=500, max_value=12000), "max_blocks": Field(int, False, 220, min_value=20, max_value=1000), "max_elements": Field(int, False, 250, min_value=20, max_value=1000)}),
    "page_markdown.act": Schema({"node_id": Field(str, True), "node_action": Field(str), "operation": Field(str), "act": Field(str), "revision": Field((int, str)), "text": Field(str), "value": Field(str), "max_chars": Field(int, False, 3000, min_value=500, max_value=12000), "max_blocks": Field(int, False, 220, min_value=20, max_value=1000), "max_elements": Field(int, False, 250, min_value=20, max_value=1000), "settle_seconds": Field((int, float), False, 1, min_value=0, max_value=10)}),
    "read_page_md": Schema({"max_chars": Field(int, False, 3000, min_value=100, max_value=12000), "mode": Field(str, False, "head", {"head", "tail"}), "query": Field(str), "regex": Field(str), "context_lines": Field(int, False, 5, min_value=0, max_value=20)}),
    "read_artifact": Schema({"path": Field(str), "file": Field(str), "artifact_id": Field(str), "mode": Field(str, False, "head", {"head", "tail"}), "max_chars": Field(int, False, 3000, min_value=100, max_value=12000), "query": Field(str), "regex": Field(str), "context_lines": Field(int, False, 5, min_value=0, max_value=20)}),
    "click_handle": Schema({"handle": Field(str, True)}),
    "fill_handle": Schema({"handle": Field(str, True), "text": Field(str, True)}),
    "select_handle": Schema({"handle": Field(str, True), "value": Field(str), "text": Field(str)}),
    "wait_ready": Schema({"wait_until": Field(str, False, "networkidle"), "timeout": Field((int, float), False, 30, min_value=1, max_value=300), "text": Field(str), "url": Field(str), "selector": Field(str)}),
    "find_text": Schema({"query": Field(str), "regex": Field(str), "artifact_id": Field(str), "context_lines": Field(int, False, 5, min_value=0, max_value=20), "max_chars": Field(int, False, 12000, min_value=100, max_value=12000)}, {"text": "query"}),
    "read_artifact_by_id": Schema({"artifact_id": Field(str, True), "mode": Field(str, False, "head", {"head", "tail"}), "max_chars": Field(int, False, 1200, min_value=100, max_value=12000), "query": Field(str), "regex": Field(str), "context_lines": Field(int, False, 3, min_value=0, max_value=20)}, {"text": "query"}),
    "search_artifact": Schema({"artifact_id": Field(str, True), "query": Field(str), "regex": Field(str), "context_lines": Field(int, False, 3, min_value=0, max_value=20), "max_chars": Field(int, False, 12000, min_value=100, max_value=12000)}, {"text": "query"}),
    "read_artifact_slice": Schema({"artifact_id": Field(str, True), "offset": Field(int, False, 0, min_value=0), "limit": Field(int, False, 4000, min_value=1, max_value=12000), "length": Field(int, min_value=1, max_value=12000), "post_ids": Field((list, str))}),
    "list_artifacts": Schema({"limit": Field(int, False, 20, min_value=1, max_value=200), "profile": Field(str)}),
    "screenshot": Schema({"filename": Field(str), "full_page": Field(bool, False, False), "force": Field(bool, False, False)}),
    "scroll_until_stable": Schema({"max_scrolls": Field(int, False, 30, min_value=1, max_value=200), "stable_rounds": Field(int, False, 2, min_value=1, max_value=20), "pause_ms": Field(int, False, 600, min_value=100, max_value=5000), "timeout": Field((int, float), False, 30, min_value=1, max_value=300)}),
    "get_page_text": Schema({"max_chars": Field(int, False, 6000, min_value=100, max_value=20000)}),
    "get_title": Schema({}),
    "extract_links": Schema({"max_links": Field(int, False, 100, min_value=1, max_value=1000)}),
    "extract_blocks": Schema({"max_blocks": Field(int, False, 80, min_value=1, max_value=500), "max_chars_per_block": Field(int, False, 500, min_value=50, max_value=5000)}),
    "click_text": Schema({"text": Field(str), "query": Field(str)}),
    "click_selector": Schema({"selector": Field(str, True)}),
    "evaluate": Schema({"script": Field(str), "code": Field(str), "text": Field(str), "allow_unsafe_eval": Field(bool, False, False), "force": Field(bool, False, False)}),
    "extract_article": Schema({}),
    "extract_table": Schema({}),
    "extract_search_results": Schema({}),
    "extract_updates_by_date": Schema({"date": Field(str, False, "yesterday")}),
    "extract_forum_posts": Schema({"adapter": Field(str, False, "auto", {"auto", "4pda", "generic_forum"}), "date_filter": Field(str), "limit": Field(int, False, 50, min_value=1, max_value=500)}),
    "filter_by_date": Schema({"date": Field(str, False, "yesterday"), "posts": Field((list, dict, str), True)}),
    "summarize_posts": Schema({"posts": Field((list, dict, str), True)}),
    "summarize_artifact": Schema({"artifact_id": Field(str, True), "query": Field(str)}),
}
ACTION_ALIASES = {"open_page": "open", "page_markdown.get": "page_markdown.get"}


def _coerce(name: str, value: Any, field: Field) -> Any:
    if value is None:
        return None
    typ = field.typ
    if typ is bool and isinstance(value, str):
        value = value.lower() in {"1", "true", "yes", "on"}
    elif typ is int and not isinstance(value, bool):
        value = int(value)
    elif typ == (int, float) and not isinstance(value, bool):
        value = float(value)
    elif typ is str:
        value = str(value)
    if not isinstance(value, typ):
        raise ValidationError(f"{name} must be {typ}")
    if isinstance(value, str):
        value = value.strip()
        if field.required and not value:
            raise ValidationError(f"{name} is required")
    if field.choices and value not in field.choices:
        raise ValidationError(f"{name} must be one of: {', '.join(map(str, sorted(field.choices)))}")
    if field.min_value is not None and value < field.min_value:
        raise ValidationError(f"{name} must be >= {field.min_value}")
    if field.max_value is not None and value > field.max_value:
        raise ValidationError(f"{name} must be <= {field.max_value}")
    return value


def normalize_and_validate(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], str]:
    args = dict(args)
    action = str(args.get("action") or "").strip()
    warnings: list[str] = []
    schema = SCHEMAS.get(action)
    if schema:
        for wrong, right in schema.aliases.items():
            if wrong in args and right not in args:
                args[right] = args.pop(wrong)
                warnings.append(f"normalized parameter {wrong} -> {right}")
        for name, field in schema.fields.items():
            if name not in args and field.default is not None:
                args[name] = field.default
            if field.required and name not in args:
                raise ValidationError(f"{name} is required for {action}")
            if name in args:
                args[name] = _coerce(name, args[name], field)
        if action == "find_text" and not str(args.get("query") or args.get("regex") or "").strip():
            raise ValidationError("find_text requires query or regex")
        if action == "search_artifact" and not str(args.get("query") or args.get("regex") or "").strip():
            raise ValidationError("search_artifact requires query or regex")
    internal_action = ACTION_ALIASES.get(action, action)
    args["action"] = internal_action
    args["_requested_action"] = action
    return args, warnings, internal_action


def state_file(root: Path) -> Path:
    p = root / ".agent-browser" / "tool-state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_state(root: Path, session_id: str = "default") -> dict[str, Any]:
    path = state_file(root)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    state = data.get(session_id) if isinstance(data.get(session_id), dict) else {}
    state.setdefault("session_id", session_id)
    state.setdefault("profile", "default")
    state.setdefault("current_url", None)
    state.setdefault("phase", "NEW")
    state.setdefault("artifact_id", None)
    state.setdefault("last_snapshot_id", None)
    state.setdefault("seen_hashes", [])
    state.setdefault("last_error", None)
    state["next_allowed_actions"] = NEXT_ALLOWED.get(state.get("phase", "NEW"), NEXT_ALLOWED["NEW"])
    return state


def save_state(root: Path, state: dict[str, Any]) -> None:
    path = state_file(root)
    data = {}
    if path.exists():
        try: data = json.loads(path.read_text(encoding="utf-8"))
        except Exception: data = {}
    data[state.get("session_id") or "default"] = state
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def phase_after(action: str, success: bool, meta: dict[str, Any]) -> str | None:
    if not success: return None
    if action in {"open_page", "open"}: return "READY" if meta.get("snapshot_file") else "OPENED"
    if action == "desktop_open": return "READY" if meta.get("text_file") else "OPENED"
    if action == "desktop_snapshot": return "READY" if meta.get("text_file") else "OPENED"
    if action in {"page_markdown", "page_markdown.get", "page_markdown.act"}: return "MARKDOWN_READY"
    if action == "read_page_md": return "EXTRACTED"
    if action in {"wait_ready", "wait"}: return "READY"
    if action == "scroll_until_stable": return "LOADED"
    if action in {"read_artifact_by_id", "read_artifact", "search_artifact", "read_artifact_slice", "find_text", "extract_article", "extract_table", "extract_search_results", "extract_updates_by_date", "extract_forum_posts", "filter_by_date"}: return "EXTRACTED"
    if action in {"summarize_posts", "summarize_artifact"}: return "ANSWER_READY"
    return None


def opaque_id(path: str | Path, prefix: str = "art") -> str:
    return f"{prefix}_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
