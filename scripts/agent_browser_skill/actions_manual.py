from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any

from agent_browser_skill.actions_generic import action_click, action_fill, action_open
from agent_browser_skill.browser import cdp, dashboard, desktop
from agent_browser_skill.core.args import bool_arg, int_arg, timeout_from
from agent_browser_skill.core.artifacts import artifact_download_files
from agent_browser_skill.core.output import cap_output, metadata
from agent_browser_skill.core.paths import ensure_inside, remember_url, remembered_url
from agent_browser_skill.core.snapshot_artifacts import compact_excerpt, write_json_artifact, write_text_artifact
from agent_browser_skill.core.page_markdown import build_snapshot_from_dom, dom_extraction_script, selector_for_handle
from agent_browser_skill.core.workflow import (
    build_browser_workflow,
    duplicate_read_guard,
    load_workflow_state,
    mark_text_artifact_read,
    pending_text_read,
    remember_pending_text_read,
    remember_pending_markdown_read,
    remember_pending_page_markdown,
    mark_pending_gate_completed,
    markdown_first_policy,
    text_workflow_guard_response,
)
from agent_browser_skill.errors import ToolError
from agent_browser_skill.runtime import dependencies as runtime_deps
from agent_browser_skill.runtime import process as process_runtime


def _state_artifacts(root: Path, paths: dict[str, Path], prefix: str, state: dict[str, Any]) -> tuple[Path, Path]:
    state_file = write_json_artifact(root, paths, prefix, state)
    text_file = write_text_artifact(root, paths, f"{prefix}-text", str(state.get("text") or ""))
    return state_file, text_file


def _state_summary_lines(prefix: str, state: dict[str, Any], state_file: Path, text_file: Path, challenge: bool) -> list[str]:
    return [
        f"{prefix}=true",
        f"challenge_detected: {str(challenge).lower()}",
        f"current_url: {state.get('url')}",
        f"title: {state.get('title')}",
        f"html_length: {state.get('htmlLength')}",
        f"text_length: {len(str(state.get('text') or ''))}",
        f"text_excerpt: {compact_excerpt(state.get('text') or '', 500)}",
        f"state_file: {state_file}",
        f"text_file: {text_file}",
    ]


def _browser_state_output(prefix: str, state: dict[str, Any], state_file: Path, text_file: Path, challenge: bool) -> str:
    return "\n".join(_state_summary_lines(prefix, state, state_file, text_file, challenge))


def _pending_text_directory_guard(root: Path, paths: dict[str, Path], target: Path) -> tuple[str, dict[str, Any]] | None:
    pending = pending_text_read(root, paths)
    if not pending or not target.is_dir():
        return None
    next_call = dict(pending["pending_next_tool_call"])
    meta = {
        "workflow_state": "blocked_until_exact_text_read",
        "guard_reason": "artifact directory was passed while an exact pending text_file must be read first",
        "recommended_next_action": next_call.get("action"),
        "next_tool_call": next_call,
        "required_next_tool_call": next_call,
        "last_text_file": pending.get("last_text_file"),
        "page_kind": pending.get("page_kind"),
        "constraints": {
            "must_read_exact_text_file_first": True,
            "do_not_use_artifact_directory_while_text_file_is_pending": True,
        },
    }
    output = "\n".join(
        [
            "read_artifact_directory_deferred=true",
            "guard_reason: artifact directory was passed while an exact pending text_file must be read first",
            f"artifact_directory: {target}",
            f"pending_text_file: {pending.get('last_text_file')}",
            "next_step: call read_artifact with the exact pending text_file path; do not pass the artifact run directory while text_file is available",
            "required_next_tool_call: " + json.dumps(next_call, ensure_ascii=False),
        ]
    )
    return output, meta


TEXT_EXTRACTION_FORBIDDEN_ACTIONS = [
    "desktop_screenshot",
    "screenshot",
    "evaluate",
    "run",
    "read_file",
    "run_command",
    "fetch_page",
]


TEXT_ARTIFACT_POLICY = {
    "prefer_exact_file": True,
    "avoid_directory_unless_no_file_returned": True,
    "max_chars_default": 3000,
    "max_chars_hard": 12000,
}


TEXT_CONTEXT_POLICY = {
    "avoid_repeating_same_artifact": True,
    "use_query_or_regex_for_dates": True,
    "summarize_before_next_large_read": True,
}


def _text_artifact_workflow(
    *,
    text_file: Path,
    page_kind: str = "generic_page",
    max_chars: int = 3000,
    user_message_hint: str | None = None,
) -> dict[str, Any]:
    meta = build_browser_workflow(
        state="page_ready",
        user_action_required=False,
        recommended_next_action="page_markdown",
        recommended_next_args={},
        next_tool_call={"action": "page_markdown"},
        allowed_next_actions=["page_markdown", "read_artifact", "navigate_pagination", "desktop_snapshot", "wait"],
        forbidden_next_actions=TEXT_EXTRACTION_FORBIDDEN_ACTIONS,
        artifact_policy=TEXT_ARTIFACT_POLICY,
        context_policy=TEXT_CONTEXT_POLICY,
        constraints={
            "prefer_page_markdown_first": True,
            "legacy_text_file_available": True,
            "do_not_use_screenshot_for_text": True,
            "do_not_use_large_raw_evaluate": True,
        },
        user_message_hint=user_message_hint
        or "Use page_markdown as the primary read. The legacy text_file is available for backward compatibility; avoid screenshots/raw evaluate for text.",
    )
    meta["page_kind"] = page_kind
    if page_kind == "forum_thread":
        meta["recommended_followup_after_read"] = {"action": "navigate_pagination", "target": "last"}
        meta["browser_workflow"]["recommended_followup_after_read"] = meta["recommended_followup_after_read"]
    return meta


def _remember_text_workflow(
    root: Path,
    paths: dict[str, Path],
    *,
    text_file: Path,
    state: dict[str, Any],
    page_kind: str,
    max_chars: int = 3000,
) -> None:
    remember_pending_text_read(
        root,
        paths,
        text_file=text_file,
        current_url=state.get("url"),
        title=state.get("title"),
        page_kind=page_kind,
        max_chars=max_chars,
    )


def _page_kind(url: Any, title: Any = "", text: Any = "") -> str:
    haystack = " ".join(str(part or "").lower() for part in (url, title, text[:1000] if isinstance(text, str) else text))
    if "showtopic=" in haystack or "/forum" in haystack or "forum" in haystack:
        return "forum_thread"
    return "generic_page"


def _artifact_excerpt(path: Path, max_chars: int, mode: str) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    if mode == "tail":
        return "..." + text[-max_chars:]
    return text[:max_chars] + "..."


def _artifact_search_excerpt(path: Path, query: str = "", regex: str = "", context_lines: int = 3, max_chars: int = 12000) -> tuple[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    matches: list[tuple[int, str]] = []
    if regex:
        pattern = re.compile(regex, re.IGNORECASE)
        for idx, line in enumerate(lines):
            if pattern.search(line):
                matches.append((idx, line))
    else:
        needle = query.lower()
        for idx, line in enumerate(lines):
            if needle in line.lower():
                matches.append((idx, line))

    if not matches:
        return "", {"artifact_filter_matches": 0}

    selected: list[str] = []
    seen: set[int] = set()
    for idx, _line in matches:
        start = max(0, idx - context_lines)
        end = min(len(lines), idx + context_lines + 1)
        if selected:
            selected.append("---")
        for line_no in range(start, end):
            if line_no in seen:
                continue
            seen.add(line_no)
            selected.append(f"{line_no + 1}: {lines[line_no]}")
        if len("\n".join(selected)) >= max_chars:
            break
    excerpt = "\n".join(selected)
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + "\n...[truncated by agent-browser skill]"
    return excerpt, {
        "artifact_filter_matches": len(matches),
        "artifact_filter_context_lines": context_lines,
    }


def _artifact_directory_candidates(directory: Path) -> list[Path]:
    readable_suffixes = {".txt", ".json", ".html", ".htm", ".csv", ".md"}
    files = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in readable_suffixes
    ]

    def rank(path: Path) -> tuple[int, float]:
        name = path.name.lower()
        if "-text" in name or name.endswith("text.txt"):
            priority = 0
        elif "snapshot" in name:
            priority = 1
        elif "state" in name:
            priority = 2
        else:
            priority = 3
        return priority, -(path.stat().st_mtime if path.exists() else 0)

    return sorted(files, key=rank)


def _resolve_artifact_target(target: Path) -> tuple[Path, Path | None]:
    if not target.is_dir():
        return target, None
    candidates = _artifact_directory_candidates(target)
    if not candidates:
        raise ToolError(
            "read_artifact received an artifact directory, but found no readable text/json/html/csv files: "
            f"{target}"
        )
    return candidates[0], target


def action_challenge_detected(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    url = str(args.get("url") or "").strip()
    handoff = str(args.get("handoff") or "manual_desktop").strip().lower()
    manual_handoff = handoff in {"manual_desktop", "desktop", "novnc", "vnc"}

    snapshot = ""
    detected = False
    screenshot = None
    reusable_manual_access = False
    if url and manual_handoff:
        if desktop.manual_desktop_running(root):
            remember_url(root, paths, url)
            desktop.desktop_navigate(args, url)
            time.sleep(2.0)
            state = desktop.desktop_page_state(args)
            snapshot = desktop.state_snapshot(state)
            detected = desktop.snapshot_needs_manual_action(snapshot)
            url = str(state.get("url") or url)
            reusable_manual_access = desktop.manual_access_running(root)
    elif url:
        open_args = dict(args)
        open_args.setdefault("wait_until", "domcontentloaded")
        action_open(root, paths, open_args)

    if not manual_handoff and not snapshot:
        snapshot = desktop.current_snapshot(root, paths, args)
        detected = desktop.snapshot_needs_manual_action(snapshot)
        screenshot = desktop.save_challenge_screenshot(root, paths, args) if detected or args.get("screenshot", True) else None
    dash_code = 0
    dash_out = ""
    dash_port = dashboard.dashboard_port_from(args)
    dash_url = dashboard.dashboard_url(args, dash_port)
    if manual_handoff:
        try:
            if reusable_manual_access:
                dash_url = dashboard.novnc_url(args, dash_port)
                vnc_password = desktop.manual_access_password(root)
                dash_out = "\n".join(
                    [
                        "manual_desktop_started=true",
                        "manual_desktop_reused=true",
                        f"manual_desktop_url: {dash_url}",
                        f"vnc_passcode: {vnc_password}",
                    ]
                )
            else:
                desktop_out, desktop_meta = action_manual_desktop(root, paths, args)
                dash_url = desktop_meta.get("manual_desktop_url") or desktop_meta.get("dashboard_url") or dash_url
                dash_port = int(desktop_meta.get("dashboard_port") or dash_port)
                dash_out = desktop_out
            try:
                live_check_seconds = max(1.0, min(float(args.get("live_check_seconds") or 10), 30.0))
                live_state, live_detected = desktop.wait_for_clear_desktop_page(args, live_check_seconds)
                live_snapshot = desktop.state_snapshot(live_state)
                snapshot = live_snapshot
                detected = bool(live_detected)
                url = str(live_state.get("url") or url)

                if desktop.state_has_usable_page(live_state) and not live_detected:
                    state_file, text_file = _state_artifacts(root, paths, "challenge-live-state", live_state)
                    checkpoint = desktop.write_challenge_checkpoint(
                        paths,
                        url=str(live_state.get("url") or url),
                        snapshot=live_snapshot,
                        screenshot=None,
                        detected=False,
                    )
                    access_note = process_runtime.stop_manual_access(root)
                    meta = metadata(paths)
                    meta.update(
                        {
                            "challenge_detected": False,
                            "manual_desktop_already_clear": True,
                            "manual_desktop_active": True,
                            "manual_access_closed": True,
                            "checkpoint": str(checkpoint),
                            "dashboard_port": dash_port,
                            "dashboard_url": dash_url,
                            "current_url": live_state.get("url"),
                            "title": live_state.get("title"),
                            "state_file": str(state_file),
                            "text_file": str(text_file),
                        }
                    )
                    meta.update(
                        build_browser_workflow(
                            state="page_ready",
                            user_action_required=False,
                            recommended_next_action="desktop_snapshot",
                            recommended_next_args={"profile": paths["site"].name},
                            next_tool_call={"action": "desktop_snapshot", "profile": paths["site"].name},
                            user_message_hint="The browser page is already usable. Continue with the suggested browser action and do not wait for the user.",
                        )
                    )
                    output = "\n".join(
                        [
                            "challenge_detected=false",
                            "manual_desktop_already_clear=true",
                            "The live noVNC/manual desktop page is already past the challenge.",
                            "Do not ask the user to solve a captcha. Continue this task with action=desktop_snapshot, action=desktop_open, or action=desktop_screenshot using the same site_key/profile.",
                            "Public noVNC/VNC access is now closed. Chrome stays alive internally for CDP actions.",
                            f"current_url: {live_state.get('url')}",
                            f"title: {live_state.get('title')}",
                            f"manual_access: {access_note}",
                            f"checkpoint: {checkpoint}",
                            f"state_file: {state_file}",
                            f"text_file: {text_file}",
                            f"text_excerpt: {compact_excerpt(live_state.get('text') or '', 500)}",
                        ]
                    )
                    return output, meta
                dash_out = "\n".join(
                    part
                    for part in (
                        dash_out,
                        f"live_desktop_check: challenge_detected={str(live_detected).lower()} url={live_state.get('url')} after={live_check_seconds:.0f}s",
                    )
                    if part
                )
            except ToolError as exc:
                dash_out = "\n".join(part for part in (dash_out, f"live_desktop_check_failed: {exc}") if part)
        except ToolError as exc:
            dash_code = 1
            dash_out = f"manual_desktop failed: {exc}"
    else:
        dash_code, dash_out, dash_port, dash_url = dashboard.start_dashboard(root, args)
    checkpoint = desktop.write_challenge_checkpoint(
        paths,
        url=url,
        snapshot=snapshot,
        screenshot=screenshot,
        detected=detected,
    )

    meta = metadata(paths)
    meta.update(
        {
            "challenge_detected": detected,
            "checkpoint": str(checkpoint),
            "screenshot": str(screenshot) if screenshot else None,
            "dashboard_port": dash_port,
            "dashboard_url": dash_url,
        }
    )
    continue_args = {"profile": paths["site"].name}
    if url:
        continue_args["url"] = url
    meta.update(
        build_browser_workflow(
            state="awaiting_user_completion" if detected else "page_ready",
            user_action_required=bool(detected),
            recommended_next_action="continue_after_manual" if detected else "desktop_snapshot",
            recommended_next_args=continue_args if detected else {"profile": paths["site"].name},
            next_tool_call={"action": "continue_after_manual", **continue_args}
            if detected
            else {"action": "desktop_snapshot", "profile": paths["site"].name},
            external_urls={"dashboard_url": dash_url} if dash_url else None,
            user_message_hint=(
                "Wait for the user only if the page still needs manual interaction."
                if detected
                else "No challenge was detected. Continue with browser actions instead of asking the user to confirm."
            ),
        )
    )

    if detected:
        output = "\n".join(
            [
                "challenge_detected=true",
                "Manual action required.",
                "Ask the user to complete the Cloudflare/captcha/login check in the current browser session, then wait for any completion confirmation message.",
                "Do not try to bypass the challenge automatically.",
                f"dashboard_url: {dash_url}",
                f"handoff: {handoff}",
                f"dashboard_status: {'started' if dash_code == 0 else 'start_failed'}",
                f"dashboard_output: {dash_out}",
                f"profile: {paths['profile']}",
                f"checkpoint: {checkpoint}",
                f"screenshot: {screenshot or '(not saved)'}",
                "next_step: wait for the user's next completion confirmation message, then call action=continue_after_manual with the same site_key/url.",
                "",
                "After the user's next confirmation message, immediately call action=continue_after_manual with the same site_key/url. Do not require an exact trigger word and do not rediscover tools first.",
            ]
        )
    else:
        output = "\n".join(
            [
                "challenge_detected=false",
                "No known Cloudflare/captcha challenge text was detected in the current snapshot.",
                f"dashboard_url: {dash_url}",
                f"dashboard_status: {'started' if dash_code == 0 else 'start_failed'}",
                f"checkpoint: {checkpoint}",
            ]
        )
    return output, meta


def action_continue_after_manual(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    url = str(args.get("url") or "").strip()
    if desktop.manual_desktop_running(root):
        try:
            state = desktop.desktop_page_state(args)
            snapshot = desktop.state_snapshot(state)
            still_detected = desktop.snapshot_needs_manual_action(snapshot)
            checkpoint = desktop.write_challenge_checkpoint(
                paths,
                url=str(state.get("url") or url),
                snapshot=snapshot,
                screenshot=None,
                detected=still_detected,
            )
            meta = metadata(paths)
            meta.update(
                {
                    "challenge_detected": still_detected,
                    "checkpoint": str(checkpoint),
                    "manual_desktop_active": True,
                    "current_url": state.get("url"),
                    "title": state.get("title"),
                }
            )
            next_args = {"profile": paths["site"].name}
            current_url = str(state.get("url") or url or "").strip()
            if current_url:
                next_args["url"] = current_url
            meta.update(
                build_browser_workflow(
                    state="awaiting_user_completion" if still_detected else "page_ready",
                    user_action_required=bool(still_detected),
                    recommended_next_action="continue_after_manual" if still_detected else "desktop_snapshot",
                    recommended_next_args=next_args if still_detected else {"profile": paths["site"].name},
                    next_tool_call={"action": "continue_after_manual", **next_args}
                    if still_detected
                    else {"action": "desktop_snapshot", "profile": paths["site"].name},
                    user_message_hint=(
                        "The page still needs manual interaction in the existing browser session."
                        if still_detected
                        else "The page is already usable. Continue with browser automation and do not re-open manual access."
                    ),
                )
            )
            if not still_detected and str(state.get("url") or "") != "about:blank":
                state_file, text_file = _state_artifacts(root, paths, "continue-after-manual-state", state)
                access_note = process_runtime.stop_manual_access(root)
                output = "\n".join(
                    [
                        "challenge_cleared=true",
                        "Manual desktop page is already past the challenge.",
                        "Public noVNC/VNC access is now closed. Chrome stays alive internally for agent CDP actions.",
                        "For the next browser steps use action=desktop_snapshot, action=desktop_open, or action=desktop_screenshot with the same site_key/url.",
                        f"current_url: {state.get('url')}",
                        f"title: {state.get('title')}",
                        f"profile: {paths['profile']}",
                        f"manual_access: {access_note}",
                        f"checkpoint: {checkpoint}",
                        f"state_file: {state_file}",
                        f"text_file: {text_file}",
                        f"text_excerpt: {compact_excerpt(state.get('text') or '', 500)}",
                    ]
                )
                meta["manual_access_closed"] = True
                meta["state_file"] = str(state_file)
                meta["text_file"] = str(text_file)
                return output, meta
            output = "\n".join(
                [
                    "challenge_cleared=false",
                    "The live manual desktop still appears to show a challenge/login page.",
                    "Ask the user to finish it in the already-open noVNC window and wait for any completion confirmation message.",
                    "next_step: wait for the user's next completion confirmation message, then call action=continue_after_manual.",
                    f"current_url: {state.get('url')}",
                    f"title: {state.get('title')}",
                    f"checkpoint: {checkpoint}",
                ]
            )
            return output, meta
        except ToolError:
            pass

    stop_note = process_runtime.stop_manual_desktop(root)
    stale_locks = process_runtime.wait_profile_unlocked(paths["profile"], timeout=5.0)
    removed_after_stop = []
    if stale_locks:
        removed_after_stop = process_runtime.unlock_profile(paths["profile"])

    if url:
        open_args = dict(args)
        open_args.setdefault("wait_until", "domcontentloaded")
        action_open(root, paths, open_args)

    snapshot = desktop.current_snapshot(root, paths, args)
    still_detected = desktop.snapshot_needs_manual_action(snapshot)
    screenshot = desktop.save_challenge_screenshot(root, paths, {**args, "filename": "after-manual.png"})
    checkpoint = desktop.write_challenge_checkpoint(
        paths,
        url=url,
        snapshot=snapshot,
        screenshot=screenshot,
        detected=still_detected,
    )

    meta = metadata(paths)
    meta.update(
        {
            "challenge_detected": still_detected,
            "checkpoint": str(checkpoint),
            "screenshot": str(screenshot) if screenshot else None,
        }
    )
    next_args = {"profile": paths["site"].name}
    if url:
        next_args["url"] = url
    meta.update(
        build_browser_workflow(
            state="awaiting_user_completion" if still_detected else "session_resumable",
            user_action_required=bool(still_detected),
            recommended_next_action="continue_after_manual" if still_detected else "desktop_snapshot",
            recommended_next_args=next_args if still_detected else {"profile": paths["site"].name},
            next_tool_call={"action": "continue_after_manual", **next_args}
            if still_detected
            else {"action": "desktop_snapshot", "profile": paths["site"].name},
            user_message_hint=(
                "The manual check is not done yet. Wait for the user to finish it."
                if still_detected
                else "Manual access can stay closed. Continue with browser automation using the preserved session."
            ),
        )
    )
    if still_detected:
        output = "\n".join(
            [
                "challenge_cleared=false",
                "The challenge/login page is still visible.",
                "Ask the user to finish the manual check and wait for any completion confirmation message.",
                "next_step: wait for the user's next completion confirmation message, then call action=continue_after_manual.",
                f"manual_desktop_stop: {stop_note}",
                f"removed_stale_locks_after_stop: {len(removed_after_stop)}",
                f"checkpoint: {checkpoint}",
                f"screenshot: {screenshot or '(not saved)'}",
            ]
        )
    else:
        snapshot_file = write_text_artifact(root, paths, "continue-after-manual-snapshot", snapshot)
        output = "\n".join(
            [
                "challenge_cleared=true",
                "Manual check appears complete. The current profile/session is preserved and can be reused.",
                f"profile: {paths['profile']}",
                f"manual_desktop_stop: {stop_note}",
                f"removed_stale_locks_after_stop: {len(removed_after_stop)}",
                f"checkpoint: {checkpoint}",
                f"snapshot_file: {snapshot_file}",
                f"snapshot_excerpt: {compact_excerpt(snapshot, 500)}",
            ]
        )
        meta["snapshot_file"] = str(snapshot_file)
    return output, meta


def action_share_session(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    code, out, port, url = dashboard.start_dashboard(root, args)
    meta = metadata(paths)
    meta.update({"dashboard_port": port, "dashboard_url": url})
    if code != 0:
        raise ToolError(f"failed to start dashboard on port {port}: {out}")
    output = "\n".join(
        [
            "dashboard_started=true",
            f"dashboard_url: {url}",
            f"dashboard_port: {port}",
            "Send this URL to the user so they can complete the manual browser challenge.",
            "next_step: after the user's next completion confirmation message, call continue_after_manual with the same site_key/url.",
            "After the user's next confirmation message, call continue_after_manual with the same site_key/url. Do not require an exact trigger word.",
            out,
        ]
    )
    return output, meta


def action_manual_desktop(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    timeout = timeout_from(args)
    url = str(args.get("url") or "").strip()
    if "/vnc.html" in url or "/vnc_auto.html" in url or "/vnc_lite.html" in url:
        url = remembered_url(root, paths)
    if not url:
        url = remembered_url(root, paths)
    if not url:
        if desktop.manual_desktop_running(root):
            public_port = dashboard.dashboard_port_from(args)
            state = desktop.desktop_page_state(args)
            url_out = dashboard.novnc_url(args, public_port)
            vnc_password = desktop.manual_access_password(root)
            meta = metadata(paths)
            meta.update(
                {
                    "manual_desktop_url": url_out,
                    "dashboard_url": url_out,
                    "dashboard_port": public_port,
                    "manual_access_password_required": True,
                    "vnc_passcode": vnc_password,
                    "manual_desktop_active": True,
                    "current_url": state.get("url"),
                    "title": state.get("title"),
                }
            )
            challenge_detected = desktop.state_needs_manual_action(state)
            continue_args = {"profile": paths["site"].name}
            current_url = str(state.get("url") or "").strip()
            if current_url:
                continue_args["url"] = current_url
            meta.update(
                build_browser_workflow(
                    state="awaiting_user_completion" if challenge_detected else "page_ready",
                    user_action_required=bool(challenge_detected),
                    recommended_next_action="continue_after_manual" if challenge_detected else "desktop_snapshot",
                    recommended_next_args=continue_args if challenge_detected else {"profile": paths["site"].name},
                    next_tool_call={"action": "continue_after_manual", **continue_args}
                    if challenge_detected
                    else {"action": "desktop_snapshot", "profile": paths["site"].name},
                    external_urls={"manual_desktop_url": url_out, "dashboard_url": url_out},
                    credentials_to_show_user={"vnc_passcode": vnc_password},
                    user_message_hint=(
                        "Use the existing manual browser window only if the page still needs user input."
                        if challenge_detected
                        else "The page is already usable. Continue with browser automation and do not ask the user to solve a challenge."
                    ),
                )
            )
            output = "\n".join(
                [
                    "manual_desktop_started=true",
                    "manual_desktop_reused=true",
                    f"manual_desktop_url: {url_out}",
                    f"vnc_passcode: {vnc_password}",
                    f"current_url: {state.get('url')}",
                    f"title: {state.get('title')}",
                    f"next_step: {'wait for the user and then call continue_after_manual' if challenge_detected else 'continue with action=desktop_snapshot or action=desktop_open using the same profile'}",
                    "The live manual desktop is already running. Continue with desktop_snapshot/desktop_open.",
                ]
            )
            return output, meta
        raise ToolError("url is required for manual_desktop")
    remember_url(root, paths, url)

    public_port = dashboard.dashboard_port_from(args)
    vnc_port = int(args.get("vnc_port") or 5900)
    cdp_port = desktop.desktop_cdp_port_from(args)
    vnc_password = desktop.manual_access_password(root, reset=True)
    display = str(args.get("display") or ":99")
    width = int(args.get("width") or 1365)
    height = int(args.get("height") or 900)

    runtime_deps.close_agent_browser(root, timeout)
    dashboard.stop_dashboard_proxy(root, public_port)
    dashboard.dashboard_command(root, args, "stop", dashboard.dashboard_internal_port_from(args))
    process_runtime.stop_manual_desktop(root)
    process_runtime.unlock_profile(paths["profile"])

    notes = [
        runtime_deps.install_browser_dependencies(root, timeout, args),
        runtime_deps.install_desktop_dependencies(root, timeout),
    ]

    d = desktop.desktop_dir(root)
    chrome = desktop.find_chrome_binary(root)
    desktop.configure_chrome_downloads(paths["profile"], paths["downloads"])
    env = {
        "DISPLAY": display,
        "LANG": "ru_RU.UTF-8",
        "LC_ALL": "C.UTF-8",
    }

    process_runtime.start_bg(
        root,
        d / "xvfb.pid",
        d / "xvfb.log",
        ["Xvfb", display, "-screen", "0", f"{width}x{height}x24", "-nolisten", "tcp", "-ac"],
        env,
    )
    process_runtime.start_bg(root, d / "openbox.pid", d / "openbox.log", ["openbox"], env)
    process_runtime.start_bg(
        root,
        d / "x11vnc.pid",
        d / "x11vnc.log",
        [
            "x11vnc",
            "-display",
            display,
            "-forever",
            "-shared",
            "-passwdfile",
            str(desktop.desktop_dir(root) / "vnc.pass"),
            "-listen",
            "127.0.0.1",
            "-rfbport",
            str(vnc_port),
        ],
        env,
    )
    process_runtime.start_bg(
        root,
        d / "chrome.pid",
        d / "chrome.log",
        [
            chrome,
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-features=Translate,BackForwardCache",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={paths['profile']}",
            f"--window-size={width},{height}",
            "--lang=ru-RU",
            "--start-maximized",
            url,
        ],
        env,
    )
    web_dir = "/usr/share/novnc"
    if not Path(web_dir).exists():
        web_dir = "/usr/share/novnc/html"
    process_runtime.start_bg(
        root,
        d / "websockify.pid",
        d / "websockify.log",
        [
            "websockify",
            "--web",
            web_dir,
            f"0.0.0.0:{public_port}",
            f"127.0.0.1:{vnc_port}",
        ],
        env,
    )

    url_out = dashboard.novnc_url(args, public_port)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_url": url_out,
            "dashboard_url": url_out,
            "dashboard_port": public_port,
            "vnc_port": vnc_port,
            "desktop_cdp_port": cdp_port,
            "manual_access_password_required": True,
            "display": display,
        }
    )

    live_check_seconds = max(0.0, min(float(args.get("live_check_seconds") or 6), 30.0))
    if live_check_seconds > 0:
        try:
            live_state, live_detected = desktop.wait_for_clear_desktop_page(args, live_check_seconds)
            if desktop.state_has_usable_page(live_state) and not live_detected:
                state_file, text_file = _state_artifacts(root, paths, "manual-desktop-live-state", live_state)
                meta.update(
                    {
                        "manual_desktop_active": True,
                        "manual_desktop_already_clear": True,
                        "challenge_detected": False,
                        "manual_access_closed": False,
                        "current_url": live_state.get("url"),
                        "title": live_state.get("title"),
                        "manual_desktop_url": url_out,
                        "dashboard_url": url_out,
                        "dashboard_port": public_port,
                        "vnc_port": vnc_port,
                        "vnc_passcode": vnc_password,
                        "manual_access_password_required": True,
                        "state_file": str(state_file),
                        "text_file": str(text_file),
                    }
                )
                meta.update(
                    build_browser_workflow(
                        state="page_ready",
                        user_action_required=False,
                        recommended_next_action="desktop_snapshot",
                        recommended_next_args={"profile": paths["site"].name},
                        next_tool_call={"action": "desktop_snapshot", "profile": paths["site"].name},
                        external_urls={"manual_desktop_url": url_out, "dashboard_url": url_out},
                        credentials_to_show_user={"vnc_passcode": vnc_password},
                        user_message_hint="The browser page is already usable. Continue with browser automation and do not wait for the user.",
                    )
                )
                output = "\n".join(
                    [
                        "manual_desktop_started=true",
                        "manual_desktop_already_clear=true",
                        "challenge_detected=false",
                        "The live manual desktop page is already usable. Do not ask the user to solve a captcha or login unless a later snapshot shows a challenge.",
                        "Classic noVNC/VNC access remains open because manual_desktop was requested directly.",
                        f"manual_desktop_url: {url_out}",
                        f"public_port: {public_port}",
                        f"vnc_port: {vnc_port}",
                        f"vnc_passcode: {vnc_password}",
                        f"current_url: {live_state.get('url')}",
                        f"title: {live_state.get('title')}",
                        f"desktop_cdp_port: {cdp_port}",
                        f"profile: {paths['profile']}",
                        f"state_file: {state_file}",
                        f"text_file: {text_file}",
                        f"text_excerpt: {compact_excerpt(live_state.get('text') or '', 500)}",
                        *[f"bootstrap: {note}" for note in notes],
                    ]
                )
                return output, meta
            meta.update(
                {
                    "manual_desktop_active": True,
                    "challenge_detected": bool(live_detected),
                    "current_url": live_state.get("url"),
                    "title": live_state.get("title"),
                }
            )
            next_args = {"profile": paths["site"].name}
            live_url = str(live_state.get("url") or url or "").strip()
            if live_url:
                next_args["url"] = live_url
            meta.update(
                build_browser_workflow(
                    state="awaiting_user_completion" if live_detected else "page_ready",
                    user_action_required=bool(live_detected),
                    recommended_next_action="continue_after_manual" if live_detected else "desktop_snapshot",
                    recommended_next_args=next_args if live_detected else {"profile": paths["site"].name},
                    next_tool_call={"action": "continue_after_manual", **next_args}
                    if live_detected
                    else {"action": "desktop_snapshot", "profile": paths["site"].name},
                    external_urls={"manual_desktop_url": url_out, "dashboard_url": url_out},
                    credentials_to_show_user={"vnc_passcode": vnc_password},
                    user_message_hint=(
                        "Wait for the user only if the live page still needs manual interaction."
                        if live_detected
                        else "The live page is already usable. Continue automatically."
                    ),
                )
            )
        except ToolError as exc:
            meta["live_desktop_check_error"] = str(exc)

    if "workflow_state" not in meta:
        meta.update(
            build_browser_workflow(
                state="awaiting_user_completion",
                user_action_required=True,
                recommended_next_action="continue_after_manual",
                recommended_next_args={"profile": paths["site"].name, "url": url},
                next_tool_call={"action": "continue_after_manual", "profile": paths["site"].name, "url": url},
                external_urls={"manual_desktop_url": url_out, "dashboard_url": url_out},
                credentials_to_show_user={"vnc_passcode": vnc_password},
                user_message_hint="The user must use the manual browser session if the page still shows a login, captcha, or challenge.",
            )
        )

    output = "\n".join(
        [
            "manual_desktop_started=true",
            f"manual_desktop_url: {url_out}",
            f"public_port: {public_port}",
            f"vnc_port: {vnc_port}",
            f"desktop_cdp_port: {cdp_port}",
            f"vnc_passcode: {vnc_password}",
            f"display: {display}",
            f"profile: {paths['profile']}",
            "next_step: wait for the user's next completion confirmation message, then call action=continue_after_manual with the same profile/url if the page still needs manual interaction.",
            "Open the URL, complete the Cloudflare/captcha/login check in the real server-side Chrome window, then wait for the user's next completion confirmation message. Do not require an exact trigger word.",
            *[f"bootstrap: {note}" for note in notes],
        ]
    )
    return output, meta


def action_stop_desktop(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    output = process_runtime.stop_manual_desktop(root)
    return output, metadata(paths)


def action_close_manual_access(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    output = process_runtime.stop_manual_access(root)
    meta = metadata(paths)
    meta["manual_access_closed"] = True
    meta.update(
        build_browser_workflow(
            state="session_resumable",
            user_action_required=False,
            recommended_next_action="desktop_snapshot",
            recommended_next_args={"profile": paths["site"].name},
            next_tool_call={"action": "desktop_snapshot", "profile": paths["site"].name},
        )
    )
    return output, meta


def _page_markdown_next_lines(*, legacy_text_file: Path | None = None) -> list[str]:
    lines = [
        "PRIMARY_NEXT_TOOL_CALL: " + json.dumps({"action": "page_markdown"}, ensure_ascii=False),
        "next_step: call page_markdown, read the Markdown artifact with read_page_md, choose a handle/action from content and UI, then call page_markdown again after page-changing actions",
        "next_tool_call: " + json.dumps({"action": "page_markdown"}, ensure_ascii=False),
        "markdown_first_workflow: use Markdown content plus stable UI handles; specialized date/forum extractors are optional fast paths only when the Markdown indicates they fit",
        "do_not_use_for_text_extraction: desktop_screenshot, read_file, run_command, raw fetch_page, curl, large raw evaluate, action=run",
    ]
    if legacy_text_file is not None:
        lines.insert(1, "legacy_text_file: " + str(legacy_text_file))
    return lines


def action_desktop_open(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    url = str(args.get("url") or "").strip()
    if not url:
        url = remembered_url(root, paths)
    if not url:
        profile = str(args.get("profile") or paths["site"].name)
        raise ToolError(
            f"url is required for desktop_open profile={profile}; no remembered URL is available for this profile. "
            "Recovery path: call desktop_open with the original url, then page_markdown, then read_page_md. "
            f"Keep profile/site_key context as {paths['site'].name}; do not reset to a different profile."
        )
    if not desktop.manual_desktop_running(root):
        remember_url(root, paths, url)
        output, meta = action_manual_desktop(root, paths, args)
        meta["desktop_open_started_manual_desktop"] = True
        meta.update(_markdown_workflow_meta(None, None))
        return "\n".join(["desktop_open_started_manual_desktop=true", output, *_page_markdown_next_lines()]), meta
    remember_url(root, paths, url)
    try:
        desktop.desktop_navigate(args, url)
        time.sleep(2.0)
        state = desktop.desktop_page_state(args)
    except ToolError as exc:
        if "CDP" not in str(exc) and "DevTools" not in str(exc):
            raise
        stop_note = process_runtime.stop_manual_desktop(root)
        process_runtime.unlock_profile(paths["profile"])
        output, meta = action_manual_desktop(root, paths, args)
        meta["desktop_open_started_manual_desktop"] = True
        meta["desktop_open_recovered_stale_cdp"] = True
        meta["stale_cdp_error"] = str(exc)
        meta["manual_desktop_stop"] = stop_note
        meta.update(_markdown_workflow_meta(None, None))
        return "\n".join(
            [
                "desktop_open_started_manual_desktop=true",
                "desktop_open_recovered_stale_cdp=true",
                f"stale_cdp_error: {exc}",
                f"manual_desktop_stop: {stop_note}",
                output,
                *_page_markdown_next_lines(),
            ]
        ), meta
    state_file, text_file = _state_artifacts(root, paths, "desktop-open-state", state)
    page_kind = _page_kind(state.get("url") or url, state.get("title"), state.get("text"))
    if not desktop.state_needs_manual_action(state):
        remember_pending_page_markdown(root, paths, current_url=state.get("url") or url, title=state.get("title"), page_kind=page_kind)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_active": True,
            "desktop_open_recovered_stale_cdp": False,
            "current_url": state.get("url"),
            "title": state.get("title"),
            "state_file": str(state_file),
            "text_file": str(text_file),
        }
    )
    challenge_detected = desktop.state_needs_manual_action(state)
    continue_args = {"profile": paths["site"].name}
    current_url = str(state.get("url") or url).strip()
    if current_url:
        continue_args["url"] = current_url
    meta.update(
        build_browser_workflow(
            state="awaiting_user_completion",
            user_action_required=True,
            recommended_next_action="continue_after_manual",
            recommended_next_args=continue_args,
            next_tool_call={"action": "continue_after_manual", **continue_args},
            user_message_hint="Only wait for the user if the newly opened page still needs manual interaction.",
        )
        if challenge_detected
        else _text_artifact_workflow(
            text_file=text_file,
            page_kind=page_kind,
            user_message_hint=(
                "Read the exact text_file artifact before screenshots, raw evaluate, or other fallbacks; "
                "for forum pages, then use navigate_pagination or site controls until the requested page data is extracted."
            ),
        )
    )
    output = "\n".join(
        _state_summary_lines("desktop_opened", state, state_file, text_file, challenge_detected)
        + (
            [
                "next_step: wait for the user and then call continue_after_manual",
                "next_tool_call: " + json.dumps({"action": "continue_after_manual", **continue_args}, ensure_ascii=False),
            ]
            if challenge_detected
            else _page_markdown_next_lines(legacy_text_file=text_file)
        )
    )
    return output, meta


def action_desktop_snapshot(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call manual_desktop or challenge_detected first")
    state = desktop.desktop_page_state(args)
    challenge = desktop.state_needs_manual_action(state)
    state_file, text_file = _state_artifacts(root, paths, "desktop-snapshot-state", state)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_active": True,
            "challenge_detected": challenge,
            "current_url": state.get("url"),
            "title": state.get("title"),
            "state_file": str(state_file),
            "text_file": str(text_file),
        }
    )
    page_kind = _page_kind(state.get("url"), state.get("title"), state.get("text"))
    if not challenge:
        remember_pending_page_markdown(root, paths, current_url=state.get("url"), title=state.get("title"), page_kind=page_kind)
        meta.update(_markdown_workflow_meta(None, None))
        meta["page_kind"] = page_kind
        meta["legacy_text_file"] = str(text_file)
    output = "\n".join(
        _state_summary_lines("desktop_snapshot", state, state_file, text_file, challenge)
        + ([] if challenge else _page_markdown_next_lines(legacy_text_file=text_file))
    )
    return output, meta


def action_desktop_screenshot(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call manual_desktop or challenge_detected first")
    if not bool_arg(args, "force", False):
        guarded = text_workflow_guard_response(
            root,
            paths,
            attempted_action="desktop_screenshot",
            reason="pending text_file must be read before using screenshots for a textual browser task",
        )
        if guarded:
            return guarded
    target = desktop.screenshot_path(root, paths, args)
    result = cdp.cdp_call(desktop.desktop_cdp_port_from(args), "Page.captureScreenshot", {"format": "png", "fromSurface": True})
    data = result.get("data")
    if not isinstance(data, str) or not data:
        raise ToolError("manual desktop screenshot returned no image data")
    target.write_bytes(base64.b64decode(data))
    meta = metadata(paths)
    meta.update({"manual_desktop_active": True, "screenshot": str(target)})
    return f"desktop screenshot saved: {target}", meta


def action_read_artifact(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw_path = str(args.get("path") or args.get("file") or "").strip()
    if not raw_path:
        raise ToolError("path is required for read_artifact")
    target = ensure_inside(Path(raw_path), root)
    browser_artifacts_root = ensure_inside(root / "browser-artifacts", root)
    if browser_artifacts_root not in target.parents and target != browser_artifacts_root:
        raise ToolError("read_artifact only allows files inside browser-artifacts")
    if not target.exists():
        raise ToolError(f"artifact file not found: {target}")
    original_directory: Path | None = None
    if target.is_dir():
        guarded_directory = _pending_text_directory_guard(root, paths, target)
        if guarded_directory:
            return guarded_directory
        target, original_directory = _resolve_artifact_target(target)
    if not target.is_file():
        raise ToolError("read_artifact requires a file path, not a directory")
    max_chars = max(100, min(int(args.get("max_chars") or 1200), 12000))
    mode = str(args.get("mode") or "head").strip().lower()
    if mode not in {"head", "tail"}:
        mode = "head"
    query = str(args.get("query") or "").strip()
    regex = str(args.get("regex") or "").strip()
    context_lines = max(0, min(int(args.get("context_lines") or 3), 20))
    filter_meta: dict[str, Any] = {}
    if query or regex:
        try:
            excerpt, filter_meta = _artifact_search_excerpt(
                target,
                query=query,
                regex=regex,
                context_lines=context_lines,
                max_chars=max_chars,
            )
        except re.error as exc:
            raise ToolError(f"invalid read_artifact regex: {exc}") from exc
        mode = "filter"
        if not excerpt:
            excerpt = f"No matches found for {'regex' if regex else 'query'}: {regex or query}"
    else:
        excerpt = _artifact_excerpt(target, max_chars, mode)
    duplicate_guard = duplicate_read_guard(
        root,
        paths,
        artifact_file=target,
        mode=mode,
        query=query,
        regex=regex,
    )
    if duplicate_guard:
        meta = metadata(paths)
        meta.update(duplicate_guard)
        output = "\n".join(
            [
                "duplicate_artifact_read_deferred=true",
                f"artifact_file: {target}",
                f"artifact_mode: {mode}",
                f"duplicate_read_count: {duplicate_guard['duplicate_read_count']}",
                "next_step: avoid rereading the same large artifact; use query/regex or navigate pagination",
                "do_not_retry: do not call read_artifact on this same path again without query/regex, and do not change max_chars to bypass this guard",
                "required_next_tool_call: " + json.dumps(duplicate_guard["required_next_tool_call"], ensure_ascii=False),
                "next_tool_call: " + json.dumps(duplicate_guard["next_tool_call"], ensure_ascii=False),
            ]
        )
        return output, meta
    mark_text_artifact_read(root, paths, target)
    meta = metadata(paths)
    meta.update(
        {
            "artifact_file": str(target),
            "artifact_size_bytes": target.stat().st_size,
            "artifact_mode": mode,
            "artifact_excerpt_chars": len(excerpt),
            "artifact_query": query or None,
            "artifact_regex": regex or None,
            **filter_meta,
        }
    )
    output_lines = ["artifact_read_ok=true"]
    if original_directory is not None:
        meta["artifact_directory"] = str(original_directory)
        meta["artifact_directory_resolved_file"] = str(target)
        output_lines.extend(
            [
                f"artifact_directory: {original_directory}",
                f"artifact_directory_resolved_file: {target}",
            ]
        )
    output_lines.extend(
        [
            f"artifact_file: {target}",
            f"artifact_mode: {mode}",
            f"artifact_size_bytes: {target.stat().st_size}",
            f"artifact_excerpt_chars: {len(excerpt)}",
            *( [f"artifact_filter: {'regex' if regex else 'query'}={regex or query}", f"artifact_filter_matches: {filter_meta.get('artifact_filter_matches', 0)}"] if query or regex else [] ),
            "",
            cap_output(excerpt, 12000),
        ]
    )
    output = "\n".join(output_lines)
    return output, meta



def _json_script(payload: dict[str, Any], body: str) -> str:
    return f"""
(() => {{
  const args = {json.dumps(payload, ensure_ascii=False)};
{body}
}})()
"""


def _typed_page_summary(root: Path, paths: dict[str, Path], prefix: str, result: Any) -> tuple[str, dict[str, Any]]:
    result_text = json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else str(result)
    result_file = write_json_artifact(root, paths, prefix, result if isinstance(result, (dict, list)) else {"result": result})
    meta = metadata(paths)
    meta.update({"manual_desktop_active": True, "result_file": str(result_file)})
    return "\n".join([f"{prefix}_ok=true", f"result_file: {result_file}", cap_output(result_text, 4000)]), meta


def action_wait_ready(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return action_wait(root, paths, args)


def action_scroll_until_stable(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    timeout = timeout_from(args)
    script = _json_script({"maxScrolls": int_arg(args, "max_scrolls", 30, 1, 200), "stableRounds": int_arg(args, "stable_rounds", 2, 1, 20), "pauseMs": int_arg(args, "pause_ms", 600, 100, 5000)}, """
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const height = () => Math.max(document.body?.scrollHeight || 0, document.documentElement?.scrollHeight || 0);
  const textLen = () => (document.body?.innerText || '').length;
  let lastHeight = height();
  let lastTextLen = textLen();
  let scrollCount = 0;
  let stableRounds = 0;
  let newContentDetected = false;
  for (; scrollCount < args.maxScrolls && stableRounds < args.stableRounds; scrollCount++) {
    window.scrollTo(0, height());
    await sleep(args.pauseMs);
    const nextHeight = height();
    const nextTextLen = textLen();
    if (nextHeight > lastHeight || nextTextLen > lastTextLen) newContentDetected = true;
    if (nextHeight === lastHeight && nextTextLen === lastTextLen) stableRounds += 1;
    else stableRounds = 0;
    lastHeight = nextHeight; lastTextLen = nextTextLen;
  }
  return {stable: stableRounds >= args.stableRounds, stable_rounds: stableRounds, scroll_count: scrollCount, final_scroll_height: lastHeight, text_length: lastTextLen, new_content_detected: newContentDetected, url: location.href, title: document.title};
""")
    result = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script, timeout=timeout)
    snap = write_json_artifact(root, paths, "scroll-stable-snapshot", result if isinstance(result, dict) else {"result": result})
    out, meta = _typed_page_summary(root, paths, "scroll_until_stable", result)
    meta.update({"snapshot_file": str(snap), "snapshot_id": __import__("agent_browser_skill.core.action_schemas", fromlist=["opaque_id"]).opaque_id(snap, "snap"), "current_url": (result or {}).get("url") if isinstance(result, dict) else None})
    meta.update(_markdown_workflow_meta(None, None))
    return out + f"\nsnapshot_id: {meta['snapshot_id']}\nnext_step: call page_markdown to refresh the Markdown snapshot after scrolling", meta


def action_get_title(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    result = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), "document.title")
    return _typed_page_summary(root, paths, "get_title", {"title": result})


def action_get_page_text(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    max_chars = int_arg(args, "max_chars", 6000, 100, 20000)
    text = str(cdp.cdp_eval(desktop.desktop_cdp_port_from(args), "document.body ? document.body.innerText : ''", timeout=timeout_from(args)) or "")
    text_file = write_text_artifact(root, paths, "page-text", text)
    shown = text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated; read text_file for full content]"
    meta = metadata(paths); meta.update({"text_file": str(text_file), "text_length": len(text), "returned_chars": len(shown)})
    return "\n".join(["get_page_text_ok=true", f"text_length: {len(text)}", f"returned_chars: {len(shown)}", f"text_file: {text_file}", "", cap_output(shown, max_chars + 200)]), meta


def action_extract_links(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    max_links = int_arg(args, "max_links", 100, 1, 1000)
    script = _json_script({"maxLinks": max_links}, """
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const loc = (el) => { const r = el.getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height)}; };
  return Array.from(document.querySelectorAll('a[href]')).slice(0, args.maxLinks).map((a) => ({text: (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 300), href: a.href, visible: visible(a), location: loc(a)}));
""")
    result = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script)
    return _typed_page_summary(root, paths, "extract_links", {"links": result, "count": len(result) if isinstance(result, list) else 0})


def action_extract_blocks(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    script = _json_script({"maxBlocks": int_arg(args, "max_blocks", 80, 1, 500), "maxChars": int_arg(args, "max_chars_per_block", 500, 50, 5000)}, """
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const loc = (el) => { const r = el.getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height)}; };
  const typeOf = (el) => /^H[1-6]$/.test(el.tagName) ? 'heading' : el.tagName === 'P' ? 'paragraph' : el.tagName === 'LI' ? 'list_item' : /TABLE|THEAD|TBODY|TR|TD|TH/.test(el.tagName) ? 'table_like' : /card|item|tile|result|product|article/i.test(el.className || '') ? 'card' : null;
  const out = [];
  for (const el of document.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,table,[role="listitem"],article,section,div')) {
    if (out.length >= args.maxBlocks) break;
    if (!visible(el)) continue;
    const kind = typeOf(el); if (!kind) continue;
    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (text.length < 2) continue;
    out.push({type: kind, tag: el.tagName.toLowerCase(), text: text.slice(0, args.maxChars), chars: text.length, location: loc(el)});
  }
  return out;
""")
    result = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script)
    return _typed_page_summary(root, paths, "extract_blocks", {"blocks": result, "count": len(result) if isinstance(result, list) else 0})


def action_click_text(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    text = str(args.get("text") or args.get("query") or "").strip()
    if not text:
        raise ToolError("text is required for click_text")
    return action_click(root, paths, {**args, "selector": "text=" + text})


def action_click_selector(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return action_click(root, paths, args)


def action_smart_read(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    read_args = dict(args)
    read_args["action"] = "read_artifact"
    if not str(read_args.get("path") or read_args.get("file") or "").strip():
        workflow = pending_text_read(root, paths) or load_workflow_state(root, paths)
        text_file = str(workflow.get("last_text_file") or "").strip()
        if not text_file:
            raise ToolError("smart_read needs a path or an active page text_file from desktop_open/desktop_snapshot")
        read_args["path"] = text_file
    output, meta = action_read_artifact(root, paths, read_args)
    meta["smart_read_used"] = True
    output = "smart_read_ok=true\n" + output
    return output, meta


def action_find_text(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    workflow_state = load_workflow_state(root, paths)
    if args.get("artifact_id") or str(args.get("path") or args.get("file") or "").strip() or pending_text_read(root, paths) or workflow_state.get("markdown_workflow_active"):
        if args.get("artifact_id"):
            from agent_browser_skill.actions_artifacts import action_search_artifact
            output, meta = action_search_artifact(root, paths, args)
            meta["find_text_used"] = True
            return "find_text_ok=true\n" + output, meta
        find_args = dict(args)
        find_args["action"] = "read_artifact"
        if not str(find_args.get("query") or find_args.get("regex") or "").strip():
            raise ToolError("find_text requires query or regex")
        if "context_lines" not in find_args:
            find_args["context_lines"] = 5
        output, meta = action_smart_read(root, paths, find_args)
        meta["find_text_used"] = True
        return "find_text_ok=true\n" + output, meta

    query = str(args.get("query") or args.get("text") or "").strip()
    regex = str(args.get("regex") or "").strip()
    if not query and not regex:
        raise ToolError("find_text requires query or regex")
    max_matches = int_arg(args, "max_matches", 20, 1, 100)
    snippet_chars = int_arg(args, "snippet_chars", 160, 40, 1000)
    script = _json_script({"query": query, "regex": regex, "maxMatches": max_matches, "snippetChars": snippet_chars}, """
  const norm = (s) => (s || '').normalize('NFKC').replace(/\\s+/g, ' ').trim();
  const hay = norm(document.body?.innerText || '');
  const matches = [];
  if (args.regex) {
    const re = new RegExp(args.regex, 'giu');
    let m;
    while ((m = re.exec(hay)) && matches.length < args.maxMatches) {
      const start = Math.max(0, m.index - args.snippetChars / 2);
      matches.push({text: m[0], snippet: hay.slice(start, m.index + m[0].length + args.snippetChars / 2), location: {text_offset: m.index}});
      if (m[0].length === 0) re.lastIndex++;
    }
  } else {
    const needle = norm(args.query).toLocaleLowerCase();
    const lower = hay.toLocaleLowerCase();
    let pos = 0;
    while ((pos = lower.indexOf(needle, pos)) !== -1 && matches.length < args.maxMatches) {
      const start = Math.max(0, pos - args.snippetChars / 2);
      matches.push({text: hay.slice(pos, pos + needle.length), snippet: hay.slice(start, pos + needle.length + args.snippetChars / 2), location: {text_offset: pos}});
      pos += Math.max(needle.length, 1);
    }
  }
  return {query: args.query || null, regex: args.regex || null, matches, count: matches.length};
""")
    result = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script)
    output, meta = _typed_page_summary(root, paths, "find_text", result)
    meta["find_text_used"] = True
    return output, meta

def action_navigate_pagination(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call manual_desktop or challenge_detected first")
    target = str(args.get("target") or "last").strip().lower()
    if target not in {"first", "prev", "next", "last"}:
        raise ToolError("target must be one of: first, prev, next, last")
    script = f"""
(() => {{
  const target = {json.dumps(target)};
  const anchors = Array.from(document.querySelectorAll('a[href]')).map((a) => {{
    const text = (a.textContent || '').replace(/\\s+/g, ' ').trim();
    const rel = (a.getAttribute('rel') || '').toLowerCase();
    const aria = (a.getAttribute('aria-label') || '').toLowerCase();
    return {{
      href: a.href,
      text,
      rel,
      aria,
      page: /^\\d+$/.test(text) ? Number(text) : null,
    }};
  }});
  const choose = (...predicates) => anchors.find((a) => predicates.some((p) => p(a)));
  const byRel = {{
    first: choose((a) => a.rel.includes('first')),
    prev: choose((a) => a.rel.includes('prev')),
    next: choose((a) => a.rel.includes('next')),
    last: choose((a) => a.rel.includes('last')),
  }};
  const byLabel = {{
    first: choose((a) => /first|начал|первая/.test(a.aria), (a) => /^(«|<<|first|первая)$/i.test(a.text)),
    prev: choose((a) => /prev|previous|назад/.test(a.aria), (a) => /^(‹|<|«|prev|previous|назад)$/i.test(a.text)),
    next: choose((a) => /next|след/.test(a.aria), (a) => /^(›|>|»|next|след)$/i.test(a.text)),
    last: choose((a) => /last|конец|послед/.test(a.aria), (a) => /^(»|>>|last|последняя|конец)$/i.test(a.text)),
  }};
  const numbered = anchors.filter((a) => a.page !== null);
  const byNumber = {{
    first: numbered.sort((a, b) => a.page - b.page)[0] || null,
    last: numbered.sort((a, b) => b.page - a.page)[0] || null,
  }};
  const match = byRel[target] || byLabel[target] || byNumber[target] || null;
  return {{
    target,
    href: match ? match.href : null,
    text: match ? match.text : null,
    rel: match ? match.rel : null,
    reason: byRel[target] ? 'rel' : byLabel[target] ? 'label' : byNumber[target] ? 'number' : 'none',
    numbered_pages: numbered.slice(0, 20).map((a) => a.page),
  }};
}})()
"""
    info = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script)
    if not isinstance(info, dict) or not info.get("href"):
        raise ToolError(f"no pagination link found for target={target}")
    href = str(info["href"])
    remember_url(root, paths, href)
    desktop.desktop_navigate(args, href)
    time.sleep(1.5)
    state = desktop.desktop_page_state(args)
    challenge = desktop.state_needs_manual_action(state)
    state_file, text_file = _state_artifacts(root, paths, f"pagination-{target}-state", state)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_active": True,
            "challenge_detected": challenge,
            "current_url": state.get("url"),
            "title": state.get("title"),
            "pagination_target": target,
            "pagination_match": info,
            "state_file": str(state_file),
            "text_file": str(text_file),
        }
    )
    if not challenge:
        meta.update(_markdown_workflow_meta(None, None))
    output = "\n".join(
        [
            f"navigate_pagination_ok=true",
            f"pagination_target: {target}",
            f"pagination_reason: {info.get('reason')}",
            f"pagination_text: {info.get('text')}",
            *_state_summary_lines("desktop_snapshot", state, state_file, text_file, challenge),
            *(
                [
                    "next_step: call page_markdown to refresh the Markdown snapshot before further navigation or answering",
                    "next_tool_call: " + json.dumps({"action": "page_markdown"}, ensure_ascii=False),
                ]
                if not challenge
                else []
            ),
        ]
    )
    return output, meta


def action_evaluate(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    script = str(args.get("script") or args.get("code") or args.get("text") or "").strip()
    if not script:
        raise ToolError("script is required for evaluate")
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call login/manual_desktop first, then evaluate")
    text_like = any(token in script for token in ("innerText", "textContent", "outerHTML", "document.body", "substring("))
    if text_like and not bool_arg(args, "force", False):
        guarded = text_workflow_guard_response(
            root,
            paths,
            attempted_action="evaluate",
            reason="pending text_file must be read before raw DOM text extraction",
        )
        if guarded:
            return guarded
    if not bool_arg(args, "allow_unsafe_eval", False):
        suggested = {"action": "page_markdown" if text_like else "extract_blocks"}
        meta = metadata(paths)
        meta.update({"error_code": "RAW_EVAL_DISABLED", "suggested_next_action": suggested})
        return "\n".join(["RAW_EVAL_DISABLED", "raw evaluate is disabled for normal browsing; use typed actions", "suggested_next_action: " + json.dumps(suggested, ensure_ascii=False)]), meta
    before_downloads = set(paths["downloads"].glob("*")) if paths["downloads"].exists() else set()
    value = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script)
    time.sleep(1.0)
    after_downloads = set(paths["downloads"].glob("*")) if paths["downloads"].exists() else set()
    new_downloads = sorted(after_downloads - before_downloads, key=lambda p: p.stat().st_mtime if p.exists() else 0)
    if isinstance(value, (dict, list)):
        result_text = json.dumps(value, ensure_ascii=False, indent=2)
    elif value is None:
        result_text = "undefined/null"
    else:
        result_text = str(value)
    meta = metadata(paths)
    meta.update(
        {
            "manual_desktop_active": True,
            "result_preview": compact_excerpt(result_text, 400),
            "downloads": [str(p) for p in new_downloads],
        }
    )
    result_file = write_text_artifact(root, paths, "evaluate-result", result_text)
    lines = [
        "evaluate_ok=true",
        f"profile: {paths['profile']}",
        f"downloads_dir: {paths['downloads']}",
        f"result_file: {result_file}",
        f"result_length: {len(result_text)}",
        f"result_excerpt: {compact_excerpt(result_text, 800)}",
    ]
    if new_downloads:
        lines.append("new_downloads:")
        lines.extend(str(p) for p in new_downloads)
    meta["result_file"] = str(result_file)
    meta["result_length"] = len(result_text)
    return "\n".join(lines), meta

def action_downloads(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    pattern = str(args.get("pattern") or args.get("filename") or "*.csv").strip() or "*.csv"
    timeout = timeout_from(args)
    deadline = time.time() + min(timeout, 30)
    files = artifact_download_files(root, paths["site"].name, pattern)
    while not files and time.time() < deadline:
        time.sleep(0.5)
        files = artifact_download_files(root, paths["site"].name, pattern)
    meta = metadata(paths)
    meta.update({"downloads": [str(p) for p in files], "pattern": pattern})
    if not files:
        return f"downloads_found=0\npattern: {pattern}\nsite: {paths['site'].name}", meta
    lines = [
        f"downloads_found={len(files)}",
        f"pattern: {pattern}",
        f"site: {paths['site'].name}",
        "files:",
    ]
    for p in files[:20]:
        size = p.stat().st_size if p.exists() else 0
        lines.append(f"{p} ({size} bytes)")
    return "\n".join(lines), meta


def _markdown_workflow_meta(markdown_file: Path | None = None, artifact_id: str | None = None) -> dict[str, Any]:
    return build_browser_workflow(
        state="markdown_ready" if markdown_file else "read_markdown_next",
        user_action_required=False,
        recommended_next_action="read_page_md" if markdown_file else "page_markdown",
        recommended_next_args={"max_chars": 3000} if markdown_file else {},
        next_tool_call={"action": "read_page_md", "max_chars": 3000} if markdown_file else {"action": "page_markdown"},
        allowed_next_actions=["read_page_md", "read_artifact", "read_artifact_by_id", "click_handle", "fill_handle", "select_handle", "click_text", "click_selector", "scroll_until_stable", "navigate_pagination", "find_text", "search_artifact"],
        forbidden_next_actions=TEXT_EXTRACTION_FORBIDDEN_ACTIONS,
        artifact_policy={**TEXT_ARTIFACT_POLICY, "primary_artifact": "markdown", "artifact_id": artifact_id},
        context_policy={**TEXT_CONTEXT_POLICY, "read_markdown_before_acting": True, "reread_markdown_after_page_change": True},
        constraints={"do_not_use_screenshot_for_text": True, "do_not_use_large_raw_evaluate": True, "do_not_read_artifact_directory_when_markdown_file_is_available": True},
        user_message_hint="Markdown-first: read the Markdown artifact, choose an action from UI handles/content, then call page_markdown again after any page-changing action.",
    ) | {"markdown_first_policy": markdown_first_policy(artifact_id=artifact_id, markdown_file=str(markdown_file) if markdown_file else None)}


def action_page_markdown(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not desktop.manual_desktop_running(root):
        raise ToolError("manual desktop is not running; call desktop_open first")
    max_chars = int_arg(args, "max_chars", 3000, 500, 12000)
    dom = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), dom_extraction_script(int_arg(args, "max_blocks", 220, 20, 1000), int_arg(args, "max_elements", 250, 20, 1000)), timeout=timeout_from(args))
    if not isinstance(dom, dict):
        raise ToolError("page_markdown DOM extraction returned an invalid result")
    snapshot = build_snapshot_from_dom(dom)
    md_file = write_text_artifact(root, paths, "page-md", snapshot["markdown"])
    elements_file = write_json_artifact(root, paths, "page-md-elements", {"url": snapshot["url"], "title": snapshot["title"], "elements": snapshot["elements"], "metadata": snapshot["metadata"]})
    full_file = write_json_artifact(root, paths, "page-markdown", snapshot)
    from agent_browser_skill.core.action_schemas import opaque_id
    artifact_id = opaque_id(md_file, "md")
    elements_id = opaque_id(elements_file, "map")
    mark_pending_gate_completed(root, paths, "page_markdown")
    remember_pending_markdown_read(root, paths, markdown_file=md_file, elements_file=elements_file, artifact_id=artifact_id, current_url=snapshot["url"], title=snapshot["title"], max_chars=max_chars)
    meta = metadata(paths)
    meta.update({"manual_desktop_active": True, "current_url": snapshot["url"], "title": snapshot["title"], "markdown_file": str(md_file), "text_file": str(md_file), "artifact_id": artifact_id, "elements_file": str(elements_file), "elements_artifact_id": elements_id, "page_markdown_file": str(full_file), "revision": snapshot["revision"], "stable": snapshot["stable"], "content_md_length": len(snapshot["content_md"]), "ui_elements_count": len(snapshot["actionable_nodes"]), "warnings": snapshot.get("warnings") or []})
    meta.update(_markdown_workflow_meta(md_file, artifact_id))
    excerpt = snapshot["markdown"][:max_chars] + ("\n...[truncated; read markdown_file artifact for full content]" if len(snapshot["markdown"]) > max_chars else "")
    return "\n".join(["page_markdown_ok=true", f"current_url: {snapshot['url']}", f"title: {snapshot['title']}", f"artifact_id: {artifact_id}", f"markdown_file: {md_file}", f"elements_artifact_id: {elements_id}", f"elements_file: {elements_file}", f"page_markdown_file: {full_file}", f"revision: {snapshot['revision']}", f"stable: {str(snapshot['stable']).lower()}", f"warnings_count: {len(snapshot.get('warnings') or [])}", f"content_md_length: {len(snapshot['content_md'])}", f"ui_elements_count: {len(snapshot['actionable_nodes'])}", "next_step: call read_page_md, reason over content and UI handles, act with click_handle/fill_handle/select_handle, then call page_markdown again after page changes", "next_tool_call: " + json.dumps({"action":"read_page_md","max_chars":max_chars}, ensure_ascii=False), "", cap_output(excerpt, max_chars + 500)]), meta


def action_read_page_md(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    workflow = load_workflow_state(root, paths)
    path = str(workflow.get("last_markdown_file") or "").strip()
    if not path:
        raise ToolError("no pending Markdown artifact found; call page_markdown first")
    read_args = {
        "action": "read_artifact",
        "path": path,
        "mode": args.get("mode") or "head",
        "max_chars": args.get("max_chars") or 3000,
    }
    for key in ("query", "regex", "context_lines"):
        if args.get(key) is not None:
            read_args[key] = args.get(key)
    output, meta = action_read_artifact(root, paths, read_args)
    artifact_id = str(workflow.get("last_markdown_artifact_id") or "")
    meta.update({
        "markdown_file": path,
        "text_file": path,
        "artifact_id": artifact_id or meta.get("artifact_id"),
        "read_page_md_used": True,
        "recommended_next_action": "click_handle",
        "allowed_next_actions": ["click_handle", "fill_handle", "select_handle", "page_markdown", "search_artifact", "read_artifact_slice", "navigate_pagination", "scroll_until_stable", "extract_forum_posts", "summarize_artifact"],
        "next_tool_call": {"action": "page_markdown"},
        "markdown_first_policy": markdown_first_policy(artifact_id=artifact_id or None, markdown_file=path),
    })
    mark_pending_gate_completed(root, paths, "read_page_md")
    return "read_page_md_ok=true\n" + output + "\nnext_step: choose a UI handle/action from the Markdown, or call page_markdown after any page-changing action", meta


def _load_last_handle(root: Path, paths: dict[str, Path], handle: str) -> dict[str, Any]:
    workflow = load_workflow_state(root, paths)
    path = str(workflow.get("last_elements_file") or "").strip()
    if not path:
        raise ToolError("no Markdown handle mapping found; call page_markdown first")
    data = json.loads(ensure_inside(Path(path), root).read_text(encoding="utf-8"))
    for el in data.get("elements") or []:
        if isinstance(el, dict) and el.get("handle") == handle:
            return el
    raise ToolError(f"handle not found in latest Markdown mapping: {handle}")


def action_click_handle(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    handle = str(args.get("handle") or "").strip()
    if not handle:
        raise ToolError("handle is required for click_handle")
    el = _load_last_handle(root, paths, handle)
    output, meta = action_click(root, paths, {**args, "selector": el.get("selector") or selector_for_handle(handle)})
    meta.update(_markdown_workflow_meta(None, None))
    return "click_handle_ok=true\nhandle: " + handle + "\nnext_step: call page_markdown to refresh the Markdown snapshot after this page-changing action\n" + output, meta


def action_fill_handle(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    handle = str(args.get("handle") or "").strip(); text = str(args.get("text") or "")
    if not handle:
        raise ToolError("handle is required for fill_handle")
    if text == "":
        raise ToolError("text is required for fill_handle")
    el = _load_last_handle(root, paths, handle)
    output, meta = action_fill(root, paths, {**args, "selector": el.get("selector") or selector_for_handle(handle), "text": text})
    meta.update(_markdown_workflow_meta(None, None))
    return "fill_handle_ok=true\nhandle: " + handle + "\nnext_step: call page_markdown to refresh the Markdown snapshot after this page-changing action\n" + output, meta


def action_select_handle(root: Path, paths: dict[str, Path], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    handle = str(args.get("handle") or "").strip(); value = str(args.get("value") or args.get("text") or "")
    if not handle or value == "":
        raise ToolError("handle and value are required for select_handle")
    el = _load_last_handle(root, paths, handle)
    selector = el.get("selector") or selector_for_handle(handle)
    script = _json_script({"selector": selector, "value": value}, """
  const el = document.querySelector(args.selector);
  if (!el) return {selected:false, reason:'not_found'};
  const opts = Array.from(el.options || []);
  const opt = opts.find(o => o.value === args.value || (o.textContent || '').trim() === args.value);
  if (opt) el.value = opt.value; else el.value = args.value;
  el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true}));
  return {selected:true, value: el.value};
""")
    result = cdp.cdp_eval(desktop.desktop_cdp_port_from(args), script, timeout=timeout_from(args))
    if not isinstance(result, dict) or not result.get("selected"):
        raise ToolError(f"select_handle failed: {result.get('reason') if isinstance(result, dict) else 'unknown'}")
    meta = metadata(paths); meta.update({"manual_desktop_active": True, "handle": handle, "selector": selector}); meta.update(_markdown_workflow_meta(None, None))
    return "select_handle_ok=true\nhandle: " + handle + f"\nselector: {selector}\nnext_step: call page_markdown to refresh the Markdown snapshot after this page-changing action", meta
