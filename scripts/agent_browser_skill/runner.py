from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from agent_browser_skill.actions import ACTIONS, metadata
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


def run_request(request: dict) -> dict:
    action = ""
    run_id = make_run_id()
    started = time.time()
    root = None
    try:
        args = dict(request.get("args") or {})
        args["_context"] = request.get("context") or {}
        action = str(args.get("action") or "").strip()
        if action not in ACTIONS:
            raise ToolError(f"unknown action: {action}")
        root = workspace_root(request)
        append_tool_log(
            root,
            {
                "event": "request_started",
                "run_id": run_id,
                "action": action,
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
        payload = ToolResult.ok(output, meta).to_payload(redact=redact, cap_output=cap_output)
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
    except subprocess.TimeoutExpired:
        payload = ToolResult.fail("agent-browser command timed out").to_payload(redact=redact, cap_output=cap_output)
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
        payload = ToolResult.ok(output, meta, status="busy").to_payload(redact=redact, cap_output=cap_output)
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
        payload = ToolResult.fail(str(exc)).to_payload(redact=redact, cap_output=cap_output)
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
        payload = ToolResult.fail(f"{type(exc).__name__}: {exc}").to_payload(redact=redact, cap_output=cap_output)
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
