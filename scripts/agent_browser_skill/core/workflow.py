from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_BROWSER_CONSTRAINTS = {
    "do_not_use_shell": True,
    "do_not_infer_public_host": True,
    "do_not_repeat_tool_discovery": True,
}


def build_browser_workflow(
    *,
    state: str,
    user_action_required: bool,
    recommended_next_action: str | None = None,
    recommended_next_args: dict[str, Any] | None = None,
    next_tool_call: dict[str, Any] | None = None,
    required_next_tool_call: dict[str, Any] | None = None,
    allowed_next_actions: list[str] | None = None,
    forbidden_next_actions: list[str] | None = None,
    artifact_policy: dict[str, Any] | None = None,
    context_policy: dict[str, Any] | None = None,
    external_urls: dict[str, Any] | None = None,
    credentials_to_show_user: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    user_message_hint: str | None = None,
) -> dict[str, Any]:
    merged_constraints = dict(DEFAULT_BROWSER_CONSTRAINTS)
    if constraints:
        merged_constraints.update(constraints)

    workflow: dict[str, Any] = {
        "workflow_state": state,
        "user_action_required": bool(user_action_required),
        "constraints": merged_constraints,
    }
    if recommended_next_action:
        workflow["recommended_next_action"] = recommended_next_action
    if recommended_next_args:
        workflow["recommended_next_args"] = dict(recommended_next_args)
    if next_tool_call:
        workflow["next_tool_call"] = dict(next_tool_call)
    elif recommended_next_action:
        payload = {"action": recommended_next_action}
        if recommended_next_args:
            payload.update(recommended_next_args)
        workflow["next_tool_call"] = payload
    if external_urls:
        workflow["external_urls"] = dict(external_urls)
    if credentials_to_show_user:
        workflow["credentials_to_show_user"] = dict(credentials_to_show_user)
    if user_message_hint:
        workflow["user_message_hint"] = user_message_hint

    meta = {"browser_workflow": workflow}
    meta["workflow_state"] = workflow["workflow_state"]
    meta["user_action_required"] = workflow["user_action_required"]
    meta["constraints"] = workflow["constraints"]
    if "recommended_next_action" in workflow:
        meta["recommended_next_action"] = workflow["recommended_next_action"]
    if "recommended_next_args" in workflow:
        meta["recommended_next_args"] = workflow["recommended_next_args"]
    if "next_tool_call" in workflow:
        meta["next_tool_call"] = workflow["next_tool_call"]
    if required_next_tool_call:
        workflow["required_next_tool_call"] = dict(required_next_tool_call)
        meta["required_next_tool_call"] = workflow["required_next_tool_call"]
    if allowed_next_actions:
        workflow["allowed_next_actions"] = list(allowed_next_actions)
        meta["allowed_next_actions"] = workflow["allowed_next_actions"]
    if forbidden_next_actions:
        workflow["forbidden_next_actions"] = list(forbidden_next_actions)
        meta["forbidden_next_actions"] = workflow["forbidden_next_actions"]
    if artifact_policy:
        workflow["artifact_policy"] = dict(artifact_policy)
        meta["artifact_policy"] = workflow["artifact_policy"]
    if context_policy:
        workflow["context_policy"] = dict(context_policy)
        meta["context_policy"] = workflow["context_policy"]
    if "external_urls" in workflow:
        meta["external_urls"] = workflow["external_urls"]
    if "credentials_to_show_user" in workflow:
        meta["credentials_to_show_user"] = workflow["credentials_to_show_user"]
    if "user_message_hint" in workflow:
        meta["user_message_hint"] = workflow["user_message_hint"]
    return meta


def workflow_state_file(root: Path, site: str) -> Path:
    path = root / ".agent-browser" / "workflow-state" / f"{site}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_workflow_state(root: Path, paths: dict[str, Path]) -> dict[str, Any]:
    path = workflow_state_file(root, paths["site"].name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_workflow_state(root: Path, paths: dict[str, Path], state: dict[str, Any]) -> None:
    path = workflow_state_file(root, paths["site"].name)
    payload = dict(state)
    payload["site_key"] = paths["site"].name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def remember_pending_text_read(
    root: Path,
    paths: dict[str, Path],
    *,
    text_file: Path,
    current_url: Any = None,
    title: Any = None,
    page_kind: str = "generic_page",
    max_chars: int = 3000,
) -> dict[str, Any]:
    state = load_workflow_state(root, paths)
    read_call = {"action": "read_artifact", "path": str(text_file), "max_chars": max_chars}
    state.update(
        {
            "workflow_state": "needs_text_read",
            "pending_next_action": "read_artifact",
            "pending_next_tool_call": read_call,
            "last_text_file": str(text_file),
            "last_url": str(current_url or ""),
            "last_title": str(title or ""),
            "page_kind": page_kind,
            "text_artifact_read": False,
        }
    )
    state.setdefault("artifact_reads", {})
    save_workflow_state(root, paths, state)
    return state


def mark_text_artifact_read(root: Path, paths: dict[str, Path], text_file: Path) -> None:
    state = load_workflow_state(root, paths)
    if str(text_file) == str(state.get("last_text_file") or ""):
        state["text_artifact_read"] = True
        state["workflow_state"] = "text_read"
        state.pop("pending_next_action", None)
        state.pop("pending_next_tool_call", None)
        save_workflow_state(root, paths, state)


def pending_text_read(root: Path, paths: dict[str, Path]) -> dict[str, Any] | None:
    state = load_workflow_state(root, paths)
    pending = state.get("pending_next_tool_call")
    if state.get("workflow_state") == "needs_text_read" and state.get("text_artifact_read") is False and isinstance(pending, dict):
        return state
    return None




def remember_pending_page_markdown(
    root: Path,
    paths: dict[str, Path],
    *,
    current_url: Any = None,
    title: Any = None,
    page_kind: str = "generic_page",
) -> dict[str, Any]:
    state = load_workflow_state(root, paths)
    next_call = {"action": "page_markdown"}
    state.update(
        {
            "workflow_state": "needs_page_markdown",
            "pending_next_action": "page_markdown",
            "pending_next_tool_call": next_call,
            "last_url": str(current_url or ""),
            "last_title": str(title or ""),
            "page_kind": page_kind,
            "markdown_workflow_active": True,
        }
    )
    save_workflow_state(root, paths, state)
    return state


def pending_workflow_gate(root: Path, paths: dict[str, Path]) -> dict[str, Any] | None:
    state = load_workflow_state(root, paths)
    pending = state.get("pending_next_tool_call")
    action = str(state.get("pending_next_action") or "").strip()
    if action and isinstance(pending, dict):
        return state
    return None


def mark_pending_gate_completed(root: Path, paths: dict[str, Path], action: str) -> None:
    state = load_workflow_state(root, paths)
    if str(state.get("pending_next_action") or "") == action:
        state.pop("pending_next_action", None)
        state.pop("pending_next_tool_call", None)
        if action == "page_markdown":
            state["workflow_state"] = "markdown_ready"
        elif action == "read_page_md":
            state["workflow_state"] = "markdown_read"
            state["text_artifact_read"] = True
        save_workflow_state(root, paths, state)


def workflow_gate_guard_response(
    root: Path,
    paths: dict[str, Path],
    *,
    attempted_action: str,
    reason: str = "pending browser workflow gate must be completed first",
) -> tuple[str, dict[str, Any]] | None:
    state = pending_workflow_gate(root, paths)
    if not state:
        return None
    required = str(state.get("pending_next_action") or "")
    if attempted_action == required:
        return None
    next_call = dict(state.get("pending_next_tool_call") or {"action": required})
    meta = {
        "workflow_state": "blocked_until_" + required,
        "attempted_action": attempted_action,
        "guard_reason": reason,
        "recommended_next_action": required,
        "next_tool_call": next_call,
        "required_next_tool_call": next_call,
        "last_markdown_file": state.get("last_markdown_file"),
        "last_text_file": state.get("last_text_file"),
        "page_kind": state.get("page_kind"),
        "constraints": {
            "must_complete_pending_browser_workflow_gate": True,
            "do_not_use_external_fetch_or_shell_for_browser_content": True,
            "do_not_use_parser_write_fallback_for_browser_content": True,
        },
    }
    output = "\n".join([
        f"{attempted_action}_deferred=true",
        f"guard_reason: {reason}",
        f"pending_next_action: {required}",
        "PRIMARY_NEXT_TOOL_CALL: " + json.dumps(next_call, ensure_ascii=False),
        "next_tool_call: " + json.dumps(next_call, ensure_ascii=False),
        "required_next_tool_call: " + json.dumps(next_call, ensure_ascii=False),
    ])
    return output, meta

def markdown_first_policy(*, artifact_id: str | None = None, markdown_file: str | None = None) -> dict[str, Any]:
    return {
        "primary_loop": [
            "desktop_open",
            "page_markdown",
            "reason_over_markdown_and_ui_handles",
            "click_handle/fill_handle/select_handle or other focused action",
            "page_markdown_after_each_page_changing_action",
        ],
        "read_primary_source": "Read the Markdown snapshot artifact first; use query/regex against it for dates and target text.",
        "artifact_id": artifact_id,
        "markdown_file": markdown_file,
        "after_page_change": {"action": "page_markdown"},
        "bounded_autonomy": {
            "max_page_changing_steps": 8,
            "if_not_found": "try pagination, filters, show/load more controls, or scroll_until_stable before returning a partial result",
            "stop_condition": "answer when evidence is found or report partial result after bounded attempts",
        },
        "specialized_extractors": "Optional fast path only when Markdown shows the page matches article/table/search/date/forum patterns.",
    }


def remember_pending_markdown_read(root: Path, paths: dict[str, Path], *, markdown_file: Path, elements_file: Path | None = None, artifact_id: str | None = None, current_url: Any = None, title: Any = None, max_chars: int = 3000) -> dict[str, Any]:
    state = load_workflow_state(root, paths)
    read_call = {"action": "read_page_md", "max_chars": max_chars}
    state.update({
        "workflow_state": "needs_markdown_read",
        "pending_next_action": "read_page_md",
        "pending_next_tool_call": read_call,
        "last_markdown_file": str(markdown_file),
        "last_markdown_artifact_id": artifact_id or "",
        "last_elements_file": str(elements_file or ""),
        "last_text_file": str(markdown_file),
        "last_url": str(current_url or ""),
        "last_title": str(title or ""),
        "page_kind": "markdown_page",
        "text_artifact_read": False,
        "markdown_workflow_active": True,
    })
    state.setdefault("artifact_reads", {})
    save_workflow_state(root, paths, state)
    return state

def duplicate_read_guard(
    root: Path,
    paths: dict[str, Path],
    *,
    artifact_file: Path,
    mode: str,
    query: str = "",
    regex: str = "",
) -> dict[str, Any] | None:
    if query or regex:
        return None
    state = load_workflow_state(root, paths)
    reads = state.setdefault("artifact_reads", {})
    key = f"{artifact_file}|{mode}|{query}|{regex}"
    count = int(reads.get(key) or 0) + 1
    reads[key] = count
    save_workflow_state(root, paths, state)
    if count <= 1:
        return None
    next_call = None
    if state.get("page_kind") == "forum_thread":
        next_call = {"action": "navigate_pagination", "target": "last"}
    required_call = next_call or {"action": "read_artifact", "path": str(artifact_file), "query": "<target text/date>", "context_lines": 5}
    return {
        "duplicate_read_detected": True,
        "duplicate_read_count": count,
        "recommended_next_action": "navigate_pagination" if next_call else "read_artifact",
        "next_tool_call": required_call,
        "required_next_tool_call": required_call,
        "blocked_actions": ["desktop_screenshot", "evaluate", "read_file", "run_command"],
        "constraints": {
            "do_not_retry_same_artifact_without_filter": True,
            "do_not_change_max_chars_to_bypass_guard": True,
            "use_query_regex_or_pagination": True,
        },
    }


def text_workflow_guard_response(
    root: Path,
    paths: dict[str, Path],
    *,
    attempted_action: str,
    reason: str,
) -> tuple[str, dict[str, Any]] | None:
    state = pending_text_read(root, paths)
    if not state:
        return None
    next_call = dict(state["pending_next_tool_call"])
    meta = {
        "workflow_state": "blocked_until_text_read",
        "attempted_action": attempted_action,
        "guard_reason": reason,
        "recommended_next_action": next_call.get("action"),
        "next_tool_call": next_call,
        "required_next_tool_call": next_call,
        "last_text_file": state.get("last_text_file"),
        "page_kind": state.get("page_kind"),
        "constraints": {
            "must_read_exact_text_file_first": True,
            "do_not_use_screenshot_for_text": True,
            "do_not_use_large_raw_evaluate": True,
        },
    }
    output = "\n".join(
        [
            f"{attempted_action}_deferred=true",
            f"guard_reason: {reason}",
            "next_step: read the pending exact text_file before screenshots, raw evaluate, or other fallbacks",
            "required_next_tool_call: " + json.dumps(next_call, ensure_ascii=False),
        ]
    )
    return output, meta
