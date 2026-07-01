from __future__ import annotations

import argparse
import contextlib
import io
import sys
import json
import subprocess
import re
import time
from pathlib import Path

from agent_browser_skill.actions import ACTIONS, metadata
from agent_browser_skill.core.action_schemas import NEXT_ALLOWED, ValidationError, load_state, normalize_and_validate, opaque_id, phase_after, save_state
from agent_browser_skill.core.tool_policy import BROWSER_CONTENT_ACTIONS, next_action_for_blocked, protected_browser_content_request
from agent_browser_skill.browser.desktop import manual_desktop_running
from agent_browser_skill.core.args import bool_arg, lock_wait_seconds_from
from agent_browser_skill.core.config import LOCKLESS_ACTIONS, MANUAL_BROWSER_ACQUIRE_ACTIONS
from agent_browser_skill.core.config import BROWSER_TOOL_LOCK_WAIT_SECONDS, WORKSPACE_SOFT_LIMIT_BYTES
from agent_browser_skill.core.artifacts import auto_cleanup_if_needed, path_size
from agent_browser_skill.core import locks as core_locks
from agent_browser_skill.core.output import cap_output, load_request, pid_running, redact, workspace_root
from agent_browser_skill.core.paths import paths_for, remembered_url
from agent_browser_skill.core.profiles import site_key_from
from agent_browser_skill.core.workflow import pending_workflow_gate, workflow_gate_guard_response
from agent_browser_skill.core.structured_logs import append_tool_log, make_run_id
from agent_browser_skill.errors import BrowserBusyError, ToolError
from agent_browser_skill.result import ToolResult
from agent_browser_skill.runtime import process as process_runtime


def _replace_busy_manual_session(root: Path, busy_meta: dict[str, object]) -> dict[str, object]:
    lock = busy_meta.get("manual_browser_lock")
    previous_profile = ""
    if isinstance(lock, dict):
        previous_profile = str(lock.get("profile") or "")
        previous_profile_path = str(lock.get("profile_path") or "").strip()
    else:
        previous_profile_path = ""
    access_note = process_runtime.stop_manual_access(root)
    desktop_note = process_runtime.stop_manual_desktop(root)
    unlocked = []
    if previous_profile_path:
        unlocked = process_runtime.unlock_profile(Path(previous_profile_path))
    core_locks.clear_manual_browser_lock(root)
    return {
        "replaced_busy_session": True,
        "replaced_busy_profile": previous_profile,
        "replace_manual_access": access_note,
        "replace_manual_desktop": desktop_note,
        "replace_unlocked_files": len(unlocked),
    }


def _classify_error(message: str) -> str:
    low = message.lower()
    if "required" in low or "invalid" in low or "must be" in low:
        return "VALIDATION_ERROR"
    if "blocked" in low or "busy" in low or "challenge" in low:
        return "BLOCKED"
    if "navigate" in low or "url" in low or "cdp" in low or "devtools" in low:
        return "NAVIGATION_ERROR"
    if "artifact" in low or "extract" in low or "snapshot" in low:
        return "EXTRACTION_ERROR"
    return "INTERNAL_ERROR"


def _sanitize_value(value, root: Path):
    if isinstance(value, dict):
        return {k: _sanitize_value(v, root) for k, v in value.items() if k not in {"artifact_dir", "screenshots_dir", "downloads_dir", "logs_dir", "profile"}}
    if isinstance(value, list):
        return [_sanitize_value(v, root) for v in value]
    if isinstance(value, str) and str(root) in value:
        return opaque_id(value, "art")
    return value


def _sanitize_message(message: str, root: Path) -> str:
    root_s = re.escape(str(root))
    return re.sub(root_s + r"/[^\s,]+", lambda m: opaque_id(m.group(0), "art"), message)



def _suggested_next_action(action: str, state: dict) -> str | None:
    pending = state.get("pending_next_action")
    if isinstance(pending, str) and pending:
        return pending
    allowed = state.get("next_allowed_actions") or []
    if action in {"open", "open_page"}:
        return "wait_ready" if "wait_ready" in allowed else (allowed[0] if allowed else None)
    if action in {"desktop_open", "desktop_snapshot"}:
        if "page_markdown" in allowed:
            return "page_markdown"
        return "scroll_until_stable" if "scroll_until_stable" in allowed else ("wait_ready" if "wait_ready" in allowed else (allowed[0] if allowed else None))
    if action == "status" and state.get("phase") in {"READY", "LOADED"}:
        for candidate in ("page_markdown", "read_page_md", "search_artifact", "get_page_text", "extract_links", "extract_forum_posts", "screenshot"):
            if candidate in allowed:
                return candidate
    return allowed[0] if allowed else None


def _metadata_suggested_next_action(meta: dict, state: dict) -> str | None:
    candidate = meta.get("recommended_next_action")
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    candidate = candidate.strip()
    allowed = state.get("next_allowed_actions") or []
    if candidate in allowed:
        return candidate
    return None


def _unified_payload(payload: dict, action: str, state: dict, root: Path) -> dict:
    meta = _sanitize_value(dict(payload.get("metadata") or {}), root)
    warnings = list(meta.get("warnings", []) or [])
    output = _sanitize_message(str(payload.get("output") or ""), root)
    if not output.strip():
        output = f"{action} completed" if payload.get("success") else f"{action} failed"
    sid = state.get("session_id") or "default"
    unified = {
        "success": bool(payload.get("success")),
        "ok": bool(payload.get("success")),
        "action": action,
        "session_id": sid,
        "state": state,
        "error_code": None,
        "message": output,
        "suggested_next_action": _metadata_suggested_next_action(meta, state) or _suggested_next_action(action, state),
        "next_allowed_actions": state.get("next_allowed_actions") or [],
        "warnings": warnings,
    }
    if meta:
        unified["metadata"] = meta
    return unified


def _error_payload(
    code: str,
    message: str,
    action: str,
    state: dict,
    warnings: list[str] | None = None,
    *,
    suggested_next_action: str | None = None,
) -> dict:
    state = dict(state or {})
    state.setdefault("next_allowed_actions", [])
    state["last_error"] = message
    suggested = suggested_next_action or _suggested_next_action(action, state)
    return {
        "success": False, "ok": False, "action": action, "session_id": state.get("session_id", "default"),
        "state": state, "error_code": code, "message": message, "suggested_next_action": suggested,
        "next_allowed_actions": state.get("next_allowed_actions") or [], "warnings": list(warnings or []), "error": message,
    }



def _workspace_limit_payload(message: str, action: str, state: dict, warnings: list[str] | None = None) -> dict:
    payload = _error_payload("WORKSPACE_LIMIT_EXCEEDED", message, action, state, warnings, suggested_next_action="cleanup")
    payload["next_tool_call"] = {"action": "cleanup", "aggressive": True, "include_runtime_env": True}
    payload["forbidden_next_actions"] = ["run_command", "rm", "du", "find"]
    payload.setdefault("metadata", {})["next_tool_call"] = payload["next_tool_call"]
    payload["metadata"]["forbidden_next_actions"] = payload["forbidden_next_actions"]
    return payload

def _ensure_visible_markdown_guidance(output: str, action: str) -> str:
    if action not in {"desktop_open", "desktop_snapshot"}:
        return output
    if "PRIMARY_NEXT_TOOL_CALL" in output and "next_tool_call" in output and "page_markdown" in output:
        return output
    from agent_browser_skill.actions_manual import _page_markdown_next_lines
    return "\n".join([output, *_page_markdown_next_lines()])


def _apply_pending_gate_to_state(state: dict, meta: dict, completed_action: str) -> None:
    bw = meta.get("browser_workflow") if isinstance(meta.get("browser_workflow"), dict) else {}
    pending_call = meta.get("required_next_tool_call") or bw.get("required_next_tool_call") or meta.get("next_tool_call") or bw.get("next_tool_call")
    pending_action = meta.get("recommended_next_action") or bw.get("recommended_next_action")
    if isinstance(pending_call, dict) and isinstance(pending_call.get("action"), str):
        pending_action = pending_call.get("action")
    if completed_action in {"desktop_open", "desktop_snapshot", "page_markdown"} and pending_action in {"page_markdown", "read_page_md"}:
        state["pending_next_action"] = pending_action
        state["pending_next_tool_call"] = pending_call if isinstance(pending_call, dict) else {"action": pending_action}
    elif completed_action == "read_page_md":
        state.pop("pending_next_action", None)
        state.pop("pending_next_tool_call", None)



def _state_for_error(root: Path | None, request: dict) -> dict:
    if root is None:
        return {}
    raw = request.get("args") or {}
    ctx = request.get("context") or {}
    session_id = str(raw.get("session_id") or (ctx.get("session_id") if isinstance(ctx, dict) else None) or "default")
    state = load_state(root, session_id)
    profile = raw.get("profile") or raw.get("site_key")
    if profile:
        state["profile"] = str(profile)
    return state

def run_request(request: dict) -> dict:
    action = ""
    run_id = make_run_id()
    started = time.time()
    root = None
    current_warnings: list[str] = []
    try:
        raw_args = dict(request.get("args") or {})
        raw_args["_context"] = request.get("context") or {}
        root = workspace_root(request)
        args, validation_warnings, action = normalize_and_validate(raw_args)
        current_warnings = list(validation_warnings)
        requested_action = str(args.get("_requested_action") or action)
        session_id = str(args.get("session_id") or args.get("_context", {}).get("session_id") or "default")
        state = load_state(root, session_id)
        requested_profile_key = site_key_from(args, root)
        explicit_profile_request = bool(args.get("profile") or args.get("site_key") or args.get("url"))
        if explicit_profile_request and state.get("profile") and state.get("profile") != requested_profile_key:
            state.pop("pending_next_action", None)
            state.pop("pending_next_tool_call", None)
            state.pop("artifact_id", None)
            state.pop("last_snapshot_id", None)
            state["phase"] = "NEW"
        if explicit_profile_request or not state.get("profile"):
            state["profile"] = requested_profile_key
        blocked, block_message = protected_browser_content_request(requested_action, args)
        if blocked:
            state["next_allowed_actions"] = list(dict.fromkeys([*BROWSER_CONTENT_ACTIONS, *(state.get("next_allowed_actions") or [])]))
            suggested = next_action_for_blocked(requested_action, args, state)
            if suggested not in state["next_allowed_actions"]:
                state["next_allowed_actions"].insert(0, suggested)
            payload = _error_payload("BLOCKED", block_message or "blocked by active browser session policy", requested_action, state, current_warnings, suggested_next_action=suggested)
            append_tool_log(
                root,
                {
                    "event": "request_finished",
                    "run_id": run_id,
                    "action": requested_action,
                    "success": False,
                    "duration_ms": int((time.time() - started) * 1000),
                    "error_code": "BLOCKED",
                    "error": payload.get("error"),
                    "policy": "active_browser_session",
                },
            )
            return payload
        debug_admin = bool_arg(args, "debug_admin", False)
        legacy_mode = bool_arg(args, "legacy", False) or bool_arg(args, "allow_legacy_run", False)
        if requested_action in {"command.run", "plugin.run", "plugin run"} or (requested_action == "run" and not (debug_admin or legacy_mode)):
            raise ToolError(f"BLOCKED_SAFE_PROFILE: {requested_action} is not available in the default/safe browser workflow; use page_markdown/page_markdown.act or typed browser actions, or pass debug_admin=true/legacy=true for explicit diagnostics")
        if action == "evaluate" and str(args.get("profile") or "").strip().lower() == "safe":
            raise ToolError("BLOCKED_SAFE_PROFILE: evaluate is not available in the safe browser profile; use page_markdown/page_markdown.act")
        if action not in ACTIONS:
            if action == "send_file":
                raise ToolError(
                    "unknown action: send_file. send_file is not an agent-browser action. "
                    "For textual extraction use action=read_artifact on the returned text_file. "
                    "For screenshots use action=desktop_screenshot, then send the saved file with the platform file tool outside agent-browser."
                )
            raise ToolError(f"unknown action: {action}")
        append_tool_log(
            root,
            {
                "event": "request_started",
                "run_id": run_id,
                "action": requested_action,
                "context": {
                    "source": args.get("_context", {}).get("source"),
                    "session_id": args.get("_context", {}).get("session_id"),
                    "user_id": args.get("_context", {}).get("user_id"),
                    "chat_id": args.get("_context", {}).get("chat_id"),
                },
                "request": {"profile": args.get("profile"), "site_key": args.get("site_key"), "url": args.get("url")},
            },
        )
        if action in LOCKLESS_ACTIONS:
            cleanup_notes = []
            paths = paths_for(root, args)
            pending_gate = pending_workflow_gate(root, paths)
            pending_action = str((pending_gate or {}).get("pending_next_action") or "")
            pending_allowlist = {"page_markdown", "read_page_md", "read_artifact", "read_artifact_by_id", "search_artifact", "read_artifact_slice", "list_artifacts", "status", "cleanup", "close", "recover", "challenge_detected", "continue_after_manual"}
            gated = workflow_gate_guard_response(root, paths, attempted_action=requested_action)
            if gated and pending_action in {"page_markdown", "read_page_md"} and requested_action not in pending_allowlist and not (requested_action == "desktop_open" and not manual_desktop_running(root)):
                output, meta = gated
                base_meta = metadata(paths)
                base_meta.update(meta)
                state["pending_next_action"] = meta.get("recommended_next_action")
                state["pending_next_tool_call"] = meta.get("next_tool_call")
                state["next_allowed_actions"] = list(dict.fromkeys([str(meta.get("recommended_next_action") or "page_markdown"), *(state.get("next_allowed_actions") or [])]))
                payload = _error_payload("BLOCKED_PENDING_WORKFLOW_GATE", output, requested_action, state, current_warnings, suggested_next_action=str(meta.get("recommended_next_action") or "page_markdown"))
                payload["metadata"] = base_meta
                return payload
            output, meta = ACTIONS[action](root, paths, args)
        else:
            with core_locks.BrowserToolLock(
                root,
                action,
                timeout=lock_wait_seconds_from(args) or BROWSER_TOOL_LOCK_WAIT_SECONDS,
                pid_running=pid_running,
            ):
                cleanup_notes = auto_cleanup_if_needed(root)
                paths = paths_for(root, args)
                pending_gate = pending_workflow_gate(root, paths)
                pending_action = str((pending_gate or {}).get("pending_next_action") or "")
                pending_allowlist = {"page_markdown", "read_page_md", "read_artifact", "read_artifact_by_id", "search_artifact", "read_artifact_slice", "list_artifacts", "status", "cleanup", "close", "recover", "challenge_detected", "continue_after_manual"}
                gated = workflow_gate_guard_response(root, paths, attempted_action=requested_action)
                if gated and pending_action in {"page_markdown", "read_page_md"} and requested_action not in pending_allowlist and not (requested_action == "desktop_open" and not manual_desktop_running(root)):
                    output, meta = gated
                    base_meta = metadata(paths)
                    base_meta.update(meta)
                    state["pending_next_action"] = meta.get("recommended_next_action")
                    state["pending_next_tool_call"] = meta.get("next_tool_call")
                    state["next_allowed_actions"] = list(dict.fromkeys([str(meta.get("recommended_next_action") or "page_markdown"), *(state.get("next_allowed_actions") or [])]))
                    payload = _error_payload("BLOCKED_PENDING_WORKFLOW_GATE", output, requested_action, state, current_warnings, suggested_next_action=str(meta.get("recommended_next_action") or "page_markdown"))
                    payload["metadata"] = base_meta
                    return payload
                busy = core_locks.guard_manual_browser_resource(
                    root,
                    paths,
                    args,
                    action,
                    manual_desktop_running=manual_desktop_running,
                    bool_arg=bool_arg,
                    remembered_url=remembered_url,
                )
                if busy:
                    output, meta = busy
                    if meta.get("replacement_allowed") and bool_arg(args, "preserve_busy_session", False) is False:
                        replacement_meta = _replace_busy_manual_session(root, meta)
                        busy = core_locks.guard_manual_browser_resource(
                            root,
                            paths,
                            args,
                            action,
                            manual_desktop_running=manual_desktop_running,
                            bool_arg=bool_arg,
                            remembered_url=remembered_url,
                        )
                        if busy:
                            output, meta = busy
                            base_meta = metadata(paths)
                            base_meta.update(meta)
                            base_meta.update(replacement_meta)
                            meta = base_meta
                            output = "\n".join(
                                [
                                    "replaced_busy_session=true",
                                    f"replaced_busy_profile: {replacement_meta.get('replaced_busy_profile') or '(unknown)'}",
                                    f"replace_manual_access: {replacement_meta.get('replace_manual_access')}",
                                    f"replace_manual_desktop: {replacement_meta.get('replace_manual_desktop')}",
                                    f"replace_unlocked_files: {replacement_meta.get('replace_unlocked_files')}",
                                    output,
                                ]
                            )
                        else:
                            try:
                                output, meta = ACTIONS[action](root, paths, args)
                            except Exception:
                                if action in MANUAL_BROWSER_ACQUIRE_ACTIONS:
                                    core_locks.clear_manual_browser_lock(root)
                                raise
                            meta.update(replacement_meta)
                            core_locks.release_manual_browser_if_needed(root, action, meta)
                            output = "\n".join(
                                [
                                    "replaced_busy_session=true",
                                    f"replaced_busy_profile: {replacement_meta.get('replaced_busy_profile') or '(unknown)'}",
                                    f"replace_manual_access: {replacement_meta.get('replace_manual_access')}",
                                    f"replace_manual_desktop: {replacement_meta.get('replace_manual_desktop')}",
                                    f"replace_unlocked_files: {replacement_meta.get('replace_unlocked_files')}",
                                    output,
                                ]
                            )
                    else:
                        base_meta = metadata(paths)
                        base_meta.update(meta)
                        meta = base_meta
                else:
                    try:
                        output, meta = ACTIONS[action](root, paths, args)
                    except Exception:
                        if action in MANUAL_BROWSER_ACQUIRE_ACTIONS:
                            core_locks.clear_manual_browser_lock(root)
                        raise
                    core_locks.release_manual_browser_if_needed(root, action, meta)
        output = _ensure_visible_markdown_guidance(output, requested_action)
        if cleanup_notes and action != "cleanup":
            meta["auto_cleanup"] = {"removed_entries": len(cleanup_notes)}
            if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
                return _workspace_limit_payload(
                    "workspace is above the soft limit after auto-cleanup; use action=cleanup with aggressive=true and include_runtime_env=true before more browser work",
                    requested_action,
                    state,
                    current_warnings,
                )
        if validation_warnings:
            meta.setdefault("warnings", []).extend(validation_warnings)
        new_phase = phase_after(requested_action, True, meta) or phase_after(action, True, meta)
        if new_phase:
            state["phase"] = new_phase
        state["profile"] = str(meta.get("site_key") or requested_profile_key or state.get("profile") or "default")
        state["current_url"] = meta.get("current_url") or args.get("url") or state.get("current_url")
        for key, prefix, state_key in (("text_file", "art", "artifact_id"), ("artifact_file", "art", "artifact_id"), ("snapshot_file", "snap", "last_snapshot_id"), ("screenshot", "snap", "last_snapshot_id")):
            if meta.get(key):
                state[state_key] = opaque_id(meta[key], prefix)
        if meta.get("artifact_id"):
            state["artifact_id"] = meta["artifact_id"]
        state["next_allowed_actions"] = NEXT_ALLOWED.get(state.get("phase", "NEW"), NEXT_ALLOWED["NEW"])
        _apply_pending_gate_to_state(state, meta, requested_action)
        if state.get("pending_next_action"):
            state["next_allowed_actions"] = list(dict.fromkeys([state["pending_next_action"], *state["next_allowed_actions"]]))
        if requested_action == "status" and state.get("phase") in {"READY", "LOADED"}:
            preferred = ["page_markdown", "read_page_md", "search_artifact", "get_page_text", "extract_links", "extract_forum_posts", "screenshot"]
            state["next_allowed_actions"] = list(dict.fromkeys([*preferred, *state["next_allowed_actions"]]))
        state["last_error"] = None
        save_state(root, state)
        payload = ToolResult.ok(output, meta).to_payload(redact=redact, cap_output=cap_output)
        payload = _unified_payload(payload, requested_action, state, root)
        append_tool_log(
            root,
            {
                "event": "request_finished",
                "run_id": run_id,
                "action": action,
                "success": True,
                "duration_ms": int((time.time() - started) * 1000),
                "status": payload.get("metadata", {}).get("status", "ok"),
                "metadata": {
                    "site_key": payload.get("metadata", {}).get("site_key"),
                    "artifact_dir": payload.get("metadata", {}).get("artifact_dir"),
                    "logs_dir": payload.get("metadata", {}).get("logs_dir"),
                },
            },
        )
        return payload
    except ValidationError as exc:
        root = root or workspace_root(request)
        state = load_state(root, str((request.get("args") or {}).get("session_id") or "default"))
        state["last_error"] = str(exc)
        save_state(root, state)
        return _error_payload("VALIDATION_ERROR", str(exc), action or str((request.get("args") or {}).get("action") or ""), state, current_warnings)
    except subprocess.TimeoutExpired:
        payload = _error_payload("INTERNAL_ERROR", "agent-browser command timed out", action, _state_for_error(root, request), current_warnings)
        if root is not None:
            append_tool_log(
                root,
                {
                    "event": "request_finished",
                    "run_id": run_id,
                    "action": action,
                    "success": False,
                    "duration_ms": int((time.time() - started) * 1000),
                    "error": payload.get("error"),
                },
            )
        return payload
    except BrowserBusyError as exc:
        output, meta = core_locks.browser_tool_busy_output(exc.owner, action)
        state = load_state(root, str((request.get("args") or {}).get("session_id") or "default")) if root else {}
        state["last_error"] = output
        payload = _unified_payload(ToolResult.ok(output, meta, status="busy").to_payload(redact=redact, cap_output=cap_output), action, state, root) if root else _error_payload("BLOCKED", output, action, state)
        if root is not None:
            append_tool_log(
                root,
                {
                    "event": "request_finished",
                    "run_id": run_id,
                    "action": action,
                    "success": True,
                    "duration_ms": int((time.time() - started) * 1000),
                    "status": "busy",
                    "metadata": {"busy_owner": exc.owner},
                },
            )
        return payload
    except ToolError as exc:
        if "WORKSPACE_LIMIT_EXCEEDED" in str(exc):
            payload = _workspace_limit_payload(str(exc), action, _state_for_error(root, request), current_warnings)
        else:
            payload = _error_payload(_classify_error(str(exc)), str(exc), action, _state_for_error(root, request), current_warnings)
        if root is not None:
            append_tool_log(
                root,
                {
                    "event": "request_finished",
                    "run_id": run_id,
                    "action": action,
                    "success": False,
                    "duration_ms": int((time.time() - started) * 1000),
                    "error": payload.get("error"),
                },
            )
        return payload
    except Exception as exc:
        payload = _error_payload("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", action, _state_for_error(root, request), current_warnings)
        if root is not None:
            append_tool_log(
                root,
                {
                    "event": "request_finished",
                    "run_id": run_id,
                    "action": action,
                    "success": False,
                    "duration_ms": int((time.time() - started) * 1000),
                    "error": payload.get("error"),
                },
            )
        return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    ns = parser.parse_args()
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    request = load_request(Path(ns.request))
    with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
        data = run_request(request)
    stray_stdout = captured_stdout.getvalue()
    stray_stderr = captured_stderr.getvalue()
    if isinstance(data, dict):
        suppressed = len(stray_stdout.encode("utf-8", errors="replace")) + len(stray_stderr.encode("utf-8", errors="replace"))
        if suppressed:
            data.setdefault("warnings", []).append("suppressed non-JSON runtime output")
            data.setdefault("metadata", {})["suppressed_runtime_output_bytes"] = suppressed
            try:
                root = workspace_root(request)
                append_tool_log(root, {"event": "suppressed_runtime_output", "stdout": stray_stdout, "stderr": stray_stderr, "bytes": suppressed})
            except Exception:
                pass
    print(json.dumps(data, ensure_ascii=False))
    return 0
