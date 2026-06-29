from __future__ import annotations

import argparse
import json
import subprocess
import re
import time
from pathlib import Path

from agent_browser_skill.actions import ACTIONS, metadata
from agent_browser_skill.core.action_schemas import NEXT_ALLOWED, ValidationError, load_state, normalize_and_validate, opaque_id, phase_after, save_state
from agent_browser_skill.browser.desktop import manual_desktop_running
from agent_browser_skill.core.args import bool_arg, lock_wait_seconds_from
from agent_browser_skill.core.config import LOCKLESS_ACTIONS, MANUAL_BROWSER_ACQUIRE_ACTIONS
from agent_browser_skill.core.config import BROWSER_TOOL_LOCK_WAIT_SECONDS, WORKSPACE_SOFT_LIMIT_BYTES
from agent_browser_skill.core.artifacts import auto_cleanup_if_needed, path_size
from agent_browser_skill.core import locks as core_locks
from agent_browser_skill.core.output import cap_output, load_request, pid_running, redact, workspace_root
from agent_browser_skill.core.paths import paths_for, remembered_url
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


def _unified_payload(payload: dict, action: str, state: dict, root: Path) -> dict:
    meta = _sanitize_value(dict(payload.get("metadata") or {}), root)
    warnings = list(meta.pop("warnings", []) or [])
    output = _sanitize_message(str(payload.get("output") or ""), root)
    sid = state.get("session_id") or "default"
    unified = {
        "success": bool(payload.get("success")),
        "ok": bool(payload.get("success")),
        "action": action,
        "session_id": sid,
        "state": state,
        "error_code": None,
        "message": output,
        "suggested_next_action": (state.get("next_allowed_actions") or [None])[0],
        "next_allowed_actions": state.get("next_allowed_actions") or [],
        "warnings": warnings,
    }
    if meta:
        unified["metadata"] = meta
    return unified


def _error_payload(code: str, message: str, action: str, state: dict, warnings: list[str] | None = None) -> dict:
    state = dict(state or {})
    state.setdefault("next_allowed_actions", [])
    state["last_error"] = message
    return {
        "success": False, "ok": False, "action": action, "session_id": state.get("session_id", "default"),
        "state": state, "error_code": code, "message": message, "suggested_next_action": (state.get("next_allowed_actions") or [None])[0],
        "next_allowed_actions": state.get("next_allowed_actions") or [], "warnings": list(warnings or []), "error": message,
    }


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
        if action not in ACTIONS:
            if action == "send_file":
                raise ToolError(
                    "unknown action: send_file. send_file is not an agent-browser action. "
                    "For textual extraction use action=read_artifact on the returned text_file. "
                    "For screenshots use action=desktop_screenshot, then send the saved file with the platform file tool outside agent-browser."
                )
            raise ToolError(f"unknown action: {action}")
        session_id = str(args.get("session_id") or args.get("_context", {}).get("session_id") or "default")
        state = load_state(root, session_id)
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
        if cleanup_notes and action != "cleanup":
            meta["auto_cleanup"] = {"removed_entries": len(cleanup_notes)}
            if path_size(root) > WORKSPACE_SOFT_LIMIT_BYTES:
                output = "\n".join(
                    [
                        "auto_cleanup ran, but workspace is still above the soft limit.",
                        "Run action=cleanup or remove large non-profile files before heavy browser work.",
                        "",
                        output,
                    ]
                )
        if validation_warnings:
            meta.setdefault("warnings", []).extend(validation_warnings)
        new_phase = phase_after(requested_action, True, meta) or phase_after(action, True, meta)
        if new_phase:
            state["phase"] = new_phase
        state["profile"] = str(meta.get("site_key") or state.get("profile") or "default")
        state["current_url"] = meta.get("current_url") or args.get("url") or state.get("current_url")
        for key, prefix, state_key in (("text_file", "art", "artifact_id"), ("artifact_file", "art", "artifact_id"), ("snapshot_file", "snap", "last_snapshot_id"), ("screenshot", "snap", "last_snapshot_id")):
            if meta.get(key):
                state[state_key] = opaque_id(meta[key], prefix)
        state["next_allowed_actions"] = NEXT_ALLOWED.get(state.get("phase", "NEW"), NEXT_ALLOWED["NEW"])
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
        payload = _error_payload("INTERNAL_ERROR", "agent-browser command timed out", action, load_state(root, "default") if root else {}, current_warnings)
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
        payload = _error_payload(_classify_error(str(exc)), str(exc), action, load_state(root, "default") if root else {}, current_warnings)
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
        payload = _error_payload("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", action, load_state(root, "default") if root else {}, current_warnings)
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
    data = run_request(load_request(Path(ns.request)))
    print(json.dumps(data, ensure_ascii=False))
    return 0 if data.get("success") else 1
